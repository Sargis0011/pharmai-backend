"""Admin CMS endpoints. Mounted at /admin.
NOTE: No auth in this MVP — gate via reverse proxy in production."""
import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from .database import get_db
from .models import (Medicine, MedicineVariant, MedicineAlias, Category,
                     UnknownSearch, Pharmacy, PharmacyChain, PharmacyBranch)
from .schemas import (MedicineCreate, MedicineUpdate, MedicineOut,
                       VariantIn, VariantOut, AliasIn, AliasOut,
                       CategoryIn, CategoryOut, UnknownSearchOut, ImportReport,
                       ChainIn, ChainOut, BranchIn, BranchOut)
from .search_utils import build_search_blob, normalize
from .import_service import import_records, parse_payload

router = APIRouter(prefix="/admin", tags=["admin"])


def _serialize_med(m: Medicine) -> MedicineOut:
    def _load(s, default):
        try:
            v = json.loads(s) if s else default
            return v if v is not None else default
        except Exception:
            return default

    return MedicineOut(
        id=m.id,
        name_hy=m.name_hy, name_ru=m.name_ru, name_en=m.name_en,
        active_substance=m.active_substance,
        form=m.form, dosage=m.dosage,
        manufacturer=m.manufacturer, country=m.country,
        image_url=m.image_url or "",
        category=m.category, registered_in_am=m.registered_in_am,
        description=_load(m.description, {}),
        indications=_load(m.indications, {}),
        symptoms=_load(m.symptoms, {}),
        side_effects=_load(m.side_effects, []),
        contraindications=_load(m.contraindications, []),
        instruction=_load(m.instruction, {}),
        variants=[VariantOut.model_validate(v) for v in m.variants],
        aliases=[a.alias for a in m.aliases],
    )


# ---------------- Medicines CRUD ----------------
@router.get("/medicines", response_model=List[MedicineOut])
def list_meds(limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    rows = db.query(Medicine).order_by(Medicine.id).offset(offset).limit(limit).all()
    return [_serialize_med(m) for m in rows]


@router.post("/medicines", response_model=MedicineOut)
def create_med(payload: MedicineCreate, db: Session = Depends(get_db)):
    m = Medicine(
        name_hy=payload.name_hy, name_ru=payload.name_ru, name_en=payload.name_en,
        active_substance=payload.active_substance,
        form=payload.form, dosage=payload.dosage,
        manufacturer=payload.manufacturer, country=payload.country,
        image_url=payload.image_url,
        category=payload.category, registered_in_am=payload.registered_in_am,
        description=json.dumps(payload.description, ensure_ascii=False),
        indications=json.dumps(payload.indications, ensure_ascii=False),
        symptoms=json.dumps(payload.symptoms, ensure_ascii=False),
        side_effects=json.dumps(payload.side_effects, ensure_ascii=False),
        contraindications=json.dumps(payload.contraindications, ensure_ascii=False),
        instruction=json.dumps(payload.instruction, ensure_ascii=False),
    )
    m.search_blob = build_search_blob(m.name_hy, m.name_ru, m.name_en,
                                       m.active_substance, m.manufacturer)
    db.add(m); db.flush()
    for v in payload.variants:
        db.add(MedicineVariant(medicine_id=m.id, **v.model_dump()))
    for a in payload.aliases:
        a = str(a).strip()
        if a:
            db.add(MedicineAlias(alias=a, alias_norm=normalize(a),
                                  medicine_id=m.id,
                                  active_substance=m.active_substance))
    db.commit(); db.refresh(m)
    return _serialize_med(m)


@router.patch("/medicines/{med_id}", response_model=MedicineOut)
def update_med(med_id: int, payload: MedicineUpdate, db: Session = Depends(get_db)):
    m = db.query(Medicine).filter(Medicine.id == med_id).first()
    if not m:
        raise HTTPException(404, "Medicine not found")
    data = payload.model_dump(exclude_unset=True)
    json_fields = {"description", "indications", "symptoms",
                   "side_effects", "contraindications", "instruction"}
    for k, v in data.items():
        if k in json_fields:
            setattr(m, k, json.dumps(v, ensure_ascii=False))
        else:
            setattr(m, k, v)
    m.search_blob = build_search_blob(m.name_hy, m.name_ru, m.name_en,
                                       m.active_substance, m.manufacturer)
    db.commit(); db.refresh(m)
    return _serialize_med(m)


@router.delete("/medicines/{med_id}")
def delete_med(med_id: int, db: Session = Depends(get_db)):
    m = db.query(Medicine).filter(Medicine.id == med_id).first()
    if not m:
        raise HTTPException(404, "Medicine not found")
    db.delete(m); db.commit()
    return {"ok": True}


# ---------------- Variants CRUD ----------------
@router.get("/medicines/{med_id}/variants", response_model=List[VariantOut])
def list_variants(med_id: int, db: Session = Depends(get_db)):
    return db.query(MedicineVariant).filter(MedicineVariant.medicine_id == med_id).all()


@router.post("/medicines/{med_id}/variants", response_model=VariantOut)
def create_variant(med_id: int, payload: VariantIn, db: Session = Depends(get_db)):
    if not db.query(Medicine).filter(Medicine.id == med_id).first():
        raise HTTPException(404, "Medicine not found")
    v = MedicineVariant(medicine_id=med_id, **payload.model_dump())
    db.add(v); db.commit(); db.refresh(v)
    return v


@router.delete("/variants/{vid}")
def delete_variant(vid: int, db: Session = Depends(get_db)):
    v = db.query(MedicineVariant).filter(MedicineVariant.id == vid).first()
    if not v:
        raise HTTPException(404, "Variant not found")
    db.delete(v); db.commit()
    return {"ok": True}


# ---------------- Aliases CRUD ----------------
@router.get("/aliases", response_model=List[AliasOut])
def list_aliases(db: Session = Depends(get_db)):
    return db.query(MedicineAlias).order_by(MedicineAlias.alias).limit(500).all()


@router.post("/aliases", response_model=AliasOut)
def create_alias(payload: AliasIn, db: Session = Depends(get_db)):
    if not db.query(Medicine).filter(Medicine.id == payload.medicine_id).first():
        raise HTTPException(404, "Medicine not found")
    a = MedicineAlias(
        alias=payload.alias.strip(),
        alias_norm=normalize(payload.alias),
        medicine_id=payload.medicine_id,
        active_substance=payload.active_substance,
    )
    db.add(a); db.commit(); db.refresh(a)
    return a


@router.delete("/aliases/{aid}")
def delete_alias(aid: int, db: Session = Depends(get_db)):
    a = db.query(MedicineAlias).filter(MedicineAlias.id == aid).first()
    if not a:
        raise HTTPException(404, "Alias not found")
    db.delete(a); db.commit()
    return {"ok": True}


# ---------------- Categories CRUD ----------------
@router.get("/categories", response_model=List[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.query(Category).order_by(Category.key).all()


@router.post("/categories", response_model=CategoryOut)
def create_category(payload: CategoryIn, db: Session = Depends(get_db)):
    if db.query(Category).filter(Category.key == payload.key).first():
        raise HTTPException(400, "Category already exists")
    c = Category(**payload.model_dump())
    db.add(c); db.commit(); db.refresh(c)
    return c


@router.patch("/categories/{cid}", response_model=CategoryOut)
def update_category(cid: int, payload: CategoryIn, db: Session = Depends(get_db)):
    c = db.query(Category).filter(Category.id == cid).first()
    if not c:
        raise HTTPException(404, "Category not found")
    for k, v in payload.model_dump().items():
        setattr(c, k, v)
    db.commit(); db.refresh(c)
    return c


@router.delete("/categories/{cid}")
def delete_category(cid: int, db: Session = Depends(get_db)):
    c = db.query(Category).filter(Category.id == cid).first()
    if not c:
        raise HTTPException(404, "Category not found")
    db.delete(c); db.commit()
    return {"ok": True}


# ---------------- Pharmacies CRUD ----------------
@router.get("/pharmacies")
def list_pharm(db: Session = Depends(get_db)):
    return db.query(Pharmacy).order_by(Pharmacy.name).all()


@router.post("/pharmacies")
def create_pharm(name: str, db: Session = Depends(get_db)):
    p = Pharmacy(name=name.strip())
    db.add(p); db.commit(); db.refresh(p)
    return p


@router.delete("/pharmacies/{pid}")
def delete_pharm(pid: int, db: Session = Depends(get_db)):
    p = db.query(Pharmacy).filter(Pharmacy.id == pid).first()
    if not p:
        raise HTTPException(404, "Pharmacy not found")
    db.delete(p); db.commit()
    return {"ok": True}


# ---------------- Pharmacy chains CRUD ----------------
def _chain_out(c: PharmacyChain) -> ChainOut:
    return ChainOut(
        id=c.id, key=c.key, name=c.name,
        description_hy=c.description_hy, description_ru=c.description_ru,
        description_en=c.description_en, logo_url=c.logo_url, website=c.website,
        branches_count=len(c.branches),
    )


@router.get("/pharmacy-chains", response_model=List[ChainOut])
def admin_list_chains(db: Session = Depends(get_db)):
    return [_chain_out(c) for c in db.query(PharmacyChain).order_by(PharmacyChain.name).all()]


@router.post("/pharmacy-chains", response_model=ChainOut)
def admin_create_chain(payload: ChainIn, db: Session = Depends(get_db)):
    if db.query(PharmacyChain).filter(PharmacyChain.key == payload.key).first():
        raise HTTPException(400, "Chain already exists")
    c = PharmacyChain(**payload.model_dump())
    db.add(c); db.commit(); db.refresh(c)
    return _chain_out(c)


@router.patch("/pharmacy-chains/{chain_id}", response_model=ChainOut)
def admin_update_chain(chain_id: int, payload: ChainIn, db: Session = Depends(get_db)):
    c = db.query(PharmacyChain).filter(PharmacyChain.id == chain_id).first()
    if not c:
        raise HTTPException(404, "Chain not found")
    for k, v in payload.model_dump().items():
        setattr(c, k, v)
    db.commit(); db.refresh(c)
    return _chain_out(c)


@router.delete("/pharmacy-chains/{chain_id}")
def admin_delete_chain(chain_id: int, db: Session = Depends(get_db)):
    c = db.query(PharmacyChain).filter(PharmacyChain.id == chain_id).first()
    if not c:
        raise HTTPException(404, "Chain not found")
    db.delete(c); db.commit()
    return {"ok": True}


# ---------------- Branches CRUD ----------------
@router.get("/pharmacy-chains/{chain_id}/branches", response_model=List[BranchOut])
def admin_list_branches(chain_id: int, db: Session = Depends(get_db)):
    return db.query(PharmacyBranch).filter(PharmacyBranch.chain_id == chain_id).all()


@router.post("/pharmacy-chains/{chain_id}/branches", response_model=BranchOut)
def admin_create_branch(chain_id: int, payload: BranchIn, db: Session = Depends(get_db)):
    if not db.query(PharmacyChain).filter(PharmacyChain.id == chain_id).first():
        raise HTTPException(404, "Chain not found")
    data = payload.model_dump(); data["chain_id"] = chain_id
    b = PharmacyBranch(**data)
    db.add(b); db.commit(); db.refresh(b)
    return b


@router.patch("/branches/{bid}", response_model=BranchOut)
def admin_update_branch(bid: int, payload: BranchIn, db: Session = Depends(get_db)):
    b = db.query(PharmacyBranch).filter(PharmacyBranch.id == bid).first()
    if not b:
        raise HTTPException(404, "Branch not found")
    for k, v in payload.model_dump().items():
        if k == "chain_id" and v is None:
            continue
        setattr(b, k, v)
    db.commit(); db.refresh(b)
    return b


@router.delete("/branches/{bid}")
def admin_delete_branch(bid: int, db: Session = Depends(get_db)):
    b = db.query(PharmacyBranch).filter(PharmacyBranch.id == bid).first()
    if not b:
        raise HTTPException(404, "Branch not found")
    db.delete(b); db.commit()
    return {"ok": True}


# ---------------- Unknown searches ----------------
@router.get("/unknown-searches", response_model=List[UnknownSearchOut])
def list_unknown(limit: int = 100, db: Session = Depends(get_db)):
    return (db.query(UnknownSearch)
            .order_by(UnknownSearch.count.desc(), UnknownSearch.last_seen.desc())
            .limit(limit).all())


@router.delete("/unknown-searches/{sid}")
def delete_unknown(sid: int, db: Session = Depends(get_db)):
    s = db.query(UnknownSearch).filter(UnknownSearch.id == sid).first()
    if not s:
        raise HTTPException(404, "Not found")
    db.delete(s); db.commit()
    return {"ok": True}


# ---------------- Import ----------------
@router.post("/import", response_model=ImportReport)
async def import_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        content = await file.read()
        records = parse_payload(file.filename or "", content)
    except Exception as e:
        raise HTTPException(400, f"Parse error: {e}")
    report = import_records(db, records)
    return ImportReport(**report)
