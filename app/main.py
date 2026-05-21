"""FastAPI application. Backward-compatible API:
  /medicines, /medicines/{id}, /analogs/{id}, /pharmacies, /medicines/categories,
  /medicines/stats, /admin/sync.
Adds smart search, variants, aliases, categories CMS at /admin/*."""
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import (Medicine, Pharmacy, PharmacyStock,
                     MedicineVariant, MedicineAlias, Category,
                     PharmacyChain, PharmacyBranch)
from .schemas import (MedicineOut, MedicineListItem, PharmacyOut,
                      SearchResponse, StatsResponse, I18nText,
                      SmartSearchResponse, VariantOut,
                      ChainOut, ChainDetailOut, BranchOut)
from .search_utils import normalize
from .search_service import smart_search, log_unknown
from .seed import run_seed
from .admin_router import router as admin_router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pharmai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    try:
        result = run_seed(force=False)
        log.info("Seed: %s", result)
    except Exception as e:
        log.warning("Seed failed: %s", e)
    yield


app = FastAPI(
    title="PharmAI API",
    version="3.0.0",
    description="Medicines search and analogs (HY/RU/EN) + CMS.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load(s, default):
    try:
        v = json.loads(s) if s else default
        return v if v is not None else default
    except Exception:
        return default


def _to_out(m: Medicine) -> MedicineOut:
    desc = _load(m.description, {})
    ind = _load(m.indications, {})
    sym = _load(getattr(m, "symptoms", "{}"), {})
    side = _load(m.side_effects, [])
    contra = _load(m.contraindications, [])
    instr = _load(getattr(m, "instruction", "{}"), {})
    return MedicineOut(
        id=m.id,
        name_hy=m.name_hy, name_ru=m.name_ru, name_en=m.name_en,
        active_substance=m.active_substance,
        form=m.form, dosage=m.dosage,
        manufacturer=m.manufacturer, country=m.country,
        image_url=getattr(m, "image_url", "") or "",
        category=m.category, registered_in_am=m.registered_in_am,
        description=I18nText(**desc) if isinstance(desc, dict) else I18nText(),
        indications=I18nText(**ind) if isinstance(ind, dict) else I18nText(),
        symptoms=I18nText(**sym) if isinstance(sym, dict) else I18nText(),
        side_effects=side,
        contraindications=contra,
        instruction=I18nText(**instr) if isinstance(instr, dict) else I18nText(),
        variants=[VariantOut.model_validate(v) for v in m.variants],
        aliases=[a.alias for a in m.aliases],
    )


@app.get("/", tags=["meta"])
def root():
    return {"name": "PharmAI API", "version": "3.0.0"}


@app.get("/medicines", response_model=SearchResponse, tags=["medicines"])
def list_medicines(
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Medicine)
    if category and category != "all":
        query = query.filter(Medicine.category == category)
    if q:
        raw = q.strip().lower()
        norm = normalize(q)
        like_raw = f"%{raw}%"
        like_norm = f"%{norm}%"
        query = query.outerjoin(MedicineAlias, MedicineAlias.medicine_id == Medicine.id).filter(
            or_(
                func.lower(Medicine.name_hy).like(like_raw),
                func.lower(Medicine.name_ru).like(like_raw),
                func.lower(Medicine.name_en).like(like_raw),
                func.lower(Medicine.active_substance).like(like_raw),
                Medicine.search_blob.like(like_norm),
                MedicineAlias.alias_norm.like(like_norm),
            )
        ).distinct()
    total = query.count()
    items = (query.order_by(Medicine.name_en, Medicine.name_hy)
             .offset(offset).limit(limit).all())
    return SearchResponse(
        total=total,
        items=[MedicineListItem.model_validate(m) for m in items],
    )


@app.get("/medicines/categories", tags=["medicines"])
def categories(db: Session = Depends(get_db)):
    # Merge derived (from data) + admin-defined categories
    derived = dict(db.query(Medicine.category, func.count(Medicine.id))
                   .group_by(Medicine.category).all())
    admin = {c.key: 0 for c in db.query(Category).all()}
    keys = sorted(set(derived) | set(admin))
    return [{"key": k, "count": derived.get(k, 0)} for k in keys]


@app.get("/medicines/stats", response_model=StatsResponse, tags=["medicines"])
def stats(db: Session = Depends(get_db)):
    return StatsResponse(
        medicines=db.query(Medicine).count(),
        pharmacies=db.query(Pharmacy).count(),
        categories=db.query(Medicine.category).distinct().count(),
        variants=db.query(MedicineVariant).count(),
        aliases=db.query(MedicineAlias).count(),
        chains=db.query(PharmacyChain).count(),
        branches=db.query(PharmacyBranch).count(),
    )


# ---------------- Pharmacy chains (public, read-only) ----------------
@app.get("/pharmacy-chains", response_model=List[ChainOut], tags=["pharmacies"])
def list_chains(db: Session = Depends(get_db)):
    rows = db.query(PharmacyChain).order_by(PharmacyChain.name).all()
    out = []
    for c in rows:
        out.append(ChainOut(
            id=c.id, key=c.key, name=c.name,
            description_hy=c.description_hy, description_ru=c.description_ru,
            description_en=c.description_en, logo_url=c.logo_url, website=c.website,
            branches_count=len(c.branches),
        ))
    return out


@app.get("/pharmacy-chains/{chain_id}", response_model=ChainDetailOut, tags=["pharmacies"])
def get_chain(chain_id: int, db: Session = Depends(get_db)):
    c = db.query(PharmacyChain).filter(PharmacyChain.id == chain_id).first()
    if not c:
        raise HTTPException(404, "Chain not found")
    return ChainDetailOut(
        id=c.id, key=c.key, name=c.name,
        description_hy=c.description_hy, description_ru=c.description_ru,
        description_en=c.description_en, logo_url=c.logo_url, website=c.website,
        branches_count=len(c.branches),
        branches=[BranchOut.model_validate(b) for b in c.branches],
    )


@app.get("/medicines/{med_id}", response_model=MedicineOut, tags=["medicines"])
def get_medicine(med_id: int, db: Session = Depends(get_db)):
    m = db.query(Medicine).filter(Medicine.id == med_id).first()
    if not m:
        raise HTTPException(404, "Medicine not found")
    return _to_out(m)


@app.get("/analogs/{med_id}", response_model=List[MedicineListItem], tags=["medicines"])
def analogs(med_id: int, db: Session = Depends(get_db)):
    m = db.query(Medicine).filter(Medicine.id == med_id).first()
    if not m:
        raise HTTPException(404, "Medicine not found")
    if not m.active_substance:
        return []
    rows = (db.query(Medicine)
            .filter(Medicine.active_substance == m.active_substance)
            .filter(Medicine.id != m.id)
            .order_by(Medicine.name_en).all())
    return [MedicineListItem.model_validate(x) for x in rows]


@app.get("/search/smart", response_model=SmartSearchResponse, tags=["search"])
def smart(q: str = Query(..., min_length=1),
          language: str = Query(""),
          db: Session = Depends(get_db)):
    """Smart fallback search: exact → alias → fuzzy → empty (with suggestions)."""
    res = smart_search(db, q, language)
    return SmartSearchResponse(
        status=res["status"], query=res["query"],
        total=len(res["items"]),
        items=[MedicineListItem.model_validate(m) for m in res["items"]],
        suggestions=[MedicineListItem.model_validate(m) for m in res["suggestions"]],
        message=res.get("message", ""),
    )


@app.get("/pharmacies", response_model=List[PharmacyOut], tags=["pharmacies"])
def list_pharmacies(db: Session = Depends(get_db)):
    return db.query(Pharmacy).order_by(Pharmacy.name).all()


@app.get("/pharmacies/medicine/{med_id}", response_model=List[PharmacyOut], tags=["pharmacies"])
def pharmacies_for_medicine(med_id: int, db: Session = Depends(get_db)):
    rows = (db.query(Pharmacy)
            .join(PharmacyStock, PharmacyStock.pharmacy_id == Pharmacy.id)
            .filter(PharmacyStock.medicine_id == med_id)
            .order_by(Pharmacy.name).distinct().all())
    return rows


@app.post("/admin/sync", tags=["admin"])
def admin_sync():
    return run_seed(force=True)


# Mount full admin CMS
app.include_router(admin_router)
