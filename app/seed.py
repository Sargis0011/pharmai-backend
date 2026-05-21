"""
Seed-pipeline. Pytaetsya skachat' otkrytye dannye iz reestra
lekarstv Armenii (Scientific Centre of Drug and Medical Technology
Expertise, pharm.am). Esli set' nedostupna ili format ne raspoznan —
padaet na vstroennyy kurirovannyy dataset (~80 preparatov).

Vyzov:
    python -m app.seed
ili avtomaticheski pri pervom starte (lifespan).
"""
import json
import logging
from typing import Iterable

import httpx
from sqlalchemy.orm import Session

from .database import Base, engine, SessionLocal
from .models import (Medicine, Pharmacy, PharmacyStock,
                     PharmacyChain, PharmacyBranch)
from .search_utils import build_search_blob, normalized_key
from .seed_data import FALLBACK_MEDICINES, PHARMACY_NAMES, CHAINS, build_branches_for

log = logging.getLogger("pharmai.seed")

# Otkrytye endpointy (mogut menyat'sya). Fall-back garantirovan.
REGISTRY_CANDIDATES = [
    "https://pharm.am/api/medicines.json",
    "https://www.pharm.am/api/registry.json",
]


def _fetch_registry() -> list[dict] | None:
    for url in REGISTRY_CANDIDATES:
        try:
            r = httpx.get(url, timeout=10.0)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                data = r.json()
                if isinstance(data, list) and data:
                    log.info("Loaded %d records from %s", len(data), url)
                    return data
        except Exception as e:
            log.warning("Registry %s failed: %s", url, e)
    return None


def _normalize_remote(rec: dict) -> dict | None:
    """Privodit zapis' iz reestra k nashemu formatu. Tolerantna k polyam."""
    name_hy = rec.get("name_hy") or rec.get("name") or rec.get("trade_name")
    if not name_hy:
        return None
    return {
        "name_hy": str(name_hy)[:255],
        "name_ru": str(rec.get("name_ru", ""))[:255],
        "name_en": str(rec.get("name_en") or rec.get("inn") or "")[:255],
        "active_substance": str(rec.get("active_substance") or rec.get("inn") or "")[:255],
        "form": str(rec.get("form", ""))[:120],
        "dosage": str(rec.get("dosage", ""))[:120],
        "manufacturer": str(rec.get("manufacturer", ""))[:255],
        "country": str(rec.get("country", ""))[:120],
        "category": str(rec.get("category", "other"))[:64],
        "registered_in_am": 1,
        "description": {},
        "indications": {},
        "side_effects": [],
        "contraindications": [],
    }


def _validate(rec: dict) -> bool:
    return bool(rec.get("name_hy")) and len(rec["name_hy"]) >= 2


def _bulk_insert(db: Session, records: Iterable[dict]) -> int:
    from .models import MedicineVariant, MedicineAlias
    from .search_utils import normalize as _norm
    count = 0
    for r in records:
        if not _validate(r):
            continue
        m = Medicine(
            name_hy=r["name_hy"],
            normalized_name=normalized_key(r.get("name_en") or r["name_hy"]),
            name_ru=r.get("name_ru", ""),
            name_en=r.get("name_en", ""),
            active_substance=r.get("active_substance", ""),
            form=r.get("form", ""),
            dosage=r.get("dosage", ""),
            manufacturer=r.get("manufacturer", ""),
            country=r.get("country", ""),
            image_url=r.get("image_url", ""),
            category=r.get("category", "other"),
            registered_in_am=r.get("registered_in_am", 1),
            description=json.dumps(r.get("description", {}), ensure_ascii=False),
            indications=json.dumps(r.get("indications", {}), ensure_ascii=False),
            symptoms=json.dumps(r.get("symptoms", {}), ensure_ascii=False),
            side_effects=json.dumps(r.get("side_effects", []), ensure_ascii=False),
            contraindications=json.dumps(r.get("contraindications", []), ensure_ascii=False),
            instruction=json.dumps(r.get("instruction", {}), ensure_ascii=False),
            search_blob=build_search_blob(
                r["name_hy"], r.get("name_ru", ""), r.get("name_en", ""),
                r.get("active_substance", ""), r.get("manufacturer", ""),
            ),
        )
        db.add(m)
        db.flush()
        for v in (r.get("variants") or []):
            db.add(MedicineVariant(
                medicine_id=m.id,
                form=str(v.get("form", ""))[:120],
                dosage=str(v.get("dosage", ""))[:120],
                package_info=str(v.get("package_info", ""))[:255],
            ))
        seen_aliases = set()
        for a in (r.get("aliases") or []):
            a = str(a).strip()
            if not a or a.lower() in seen_aliases:
                continue
            seen_aliases.add(a.lower())
            db.add(MedicineAlias(
                alias=a[:255], alias_norm=_norm(a)[:255],
                medicine_id=m.id, active_substance=r.get("active_substance", ""),
            ))
        count += 1
        if count % 200 == 0:
            db.commit()
    db.commit()
    return count


def _seed_pharmacies(db: Session) -> int:
    objs = [Pharmacy(name=n) for n in PHARMACY_NAMES]
    db.bulk_save_objects(objs)
    db.commit()
    return len(objs)


def _seed_stock_links(db: Session) -> None:
    """Privyazyvaem kazhdoe lekarstvo k 3-5 aptekam (psevdo-sluchayno, no detrm.)."""
    meds = db.query(Medicine).all()
    pharms = db.query(Pharmacy).all()
    if not pharms:
        return
    links = []
    for m in meds:
        for i in range(3 + (m.id % 3)):
            p = pharms[(m.id * 7 + i * 11) % len(pharms)]
            links.append(PharmacyStock(pharmacy_id=p.id, medicine_id=m.id))
    db.bulk_save_objects(links)
    db.commit()


DEFAULT_CATEGORIES = [
    ("painkillers",       "Ցավազրկողներ",          "Обезболивающие",       "Painkillers"),
    ("antibiotics",       "Հակաբիոտիկներ",         "Антибиотики",          "Antibiotics"),
    ("antivirals",        "Հակավիրուսային",        "Противовирусные",      "Antivirals"),
    ("cardio",            "Սրտանոթային",            "Сердечно-сосудистые",  "Cardiovascular"),
    ("hypertension",      "Ճնշման համար",           "Для давления",         "Hypertension"),
    ("gastro",            "Ստամոքս-աղիք",          "ЖКТ",                  "GI tract"),
    ("vitamins",          "Վիտամիններ",            "Витамины",             "Vitamins"),
    ("allergy",           "Հակաալերգիկ",            "Антиаллергические",    "Allergy"),
    ("pediatric",         "Մանկական",               "Детские",              "Pediatric"),
    ("dermatology",       "Մաշկաբանական",          "Дерматологические",    "Dermatology"),
    ("neurology",         "Նյարդաբանական",         "Неврологические",      "Neurology"),
    ("hormonal",          "Հորմոնալ",               "Гормональные",         "Hormonal"),
    ("diabetes",          "Շաքարախտ",              "Диабет",               "Diabetes"),
    ("respiratory",       "Շնչառական",             "Дыхательная система",  "Respiratory"),
    ("ophthalmology",     "Աչքի",                   "Глазные",              "Ophthalmology"),
    ("ent",               "ԼՕՌ",                    "ЛОР",                  "ENT"),
    ("immunity",          "Իմունիտետ",             "Иммунитет",            "Immunity"),
    ("antiinflammatory",  "Հակաբորբոքային",        "Противовоспалительные","Anti-inflammatory"),
    # legacy fallbacks kept for back-compat with existing seed data
    ("cold",              "Մրսածություն",          "Простуда и грипп",     "Cold & Flu"),
    ("nervous",           "Նյարդային",             "Нервная система",      "Nervous"),
    ("antiseptics",       "Հակասեպտիկներ",         "Антисептики",          "Antiseptics"),
    ("antispasmodics",    "Հակասպազմոդիկ",         "Спазмолитики",         "Antispasmodics"),
    ("other",             "Այլ",                    "Прочее",               "Other"),
]


def _seed_categories(db: Session) -> None:
    from .models import Category
    existing = {c.key for c in db.query(Category).all()}
    for key, hy, ru, en in DEFAULT_CATEGORIES:
        if key not in existing:
            db.add(Category(key=key, name_hy=hy, name_ru=ru, name_en=en))
    db.commit()


def _seed_chains(db: Session, force: bool = False) -> dict:
    if force:
        db.query(PharmacyBranch).delete()
        db.query(PharmacyChain).delete()
        db.commit()
    if db.query(PharmacyChain).count() > 0:
        return {"chains": db.query(PharmacyChain).count(),
                "branches": db.query(PharmacyBranch).count()}
    for c in CHAINS:
        chain = PharmacyChain(**c)
        db.add(chain); db.flush()
        for b in build_branches_for(c["key"]):
            db.add(PharmacyBranch(chain_id=chain.id, **b))
    db.commit()
    return {"chains": db.query(PharmacyChain).count(),
            "branches": db.query(PharmacyBranch).count()}


def run_seed(force: bool = False) -> dict:
    from .models import MedicineVariant, MedicineAlias
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(Medicine).count()
        _seed_categories(db)
        chains_report = _seed_chains(db, force=force)
        if existing and not force:
            return {"status": "skipped", "medicines": existing, **chains_report}
        if force:
            db.query(MedicineAlias).delete()
            db.query(MedicineVariant).delete()
            db.query(PharmacyStock).delete()
            db.query(Medicine).delete()
            db.query(Pharmacy).delete()
            db.commit()

        remote = _fetch_registry()
        if remote:
            records = [r for r in (_normalize_remote(x) for x in remote) if r]
        else:
            log.info("Using fallback dataset (%d items)", len(FALLBACK_MEDICINES))
            records = FALLBACK_MEDICINES

        inserted = _bulk_insert(db, records)
        ph_count = _seed_pharmacies(db)
        _seed_stock_links(db)
        return {
            "status": "ok",
            "medicines": inserted,
            "pharmacies": ph_count,
            "source": "registry" if remote else "fallback",
            **chains_report,
        }
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_seed(force=True), ensure_ascii=False, indent=2))
