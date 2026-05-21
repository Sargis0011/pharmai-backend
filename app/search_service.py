"""Smart multilingual search with exact → alias → fuzzy → analog fallback."""
from typing import List, Tuple
from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from rapidfuzz import process, fuzz

from .models import Medicine, MedicineAlias, UnknownSearch
from .search_utils import normalize


def _exact_match(db: Session, q: str) -> List[Medicine]:
    raw = q.strip().lower()
    norm = normalize(q)
    rows = (
        db.query(Medicine)
        .filter(
            or_(
                func.lower(Medicine.name_hy) == raw,
                func.lower(Medicine.name_ru) == raw,
                func.lower(Medicine.name_en) == raw,
                func.lower(Medicine.active_substance) == raw,
                Medicine.search_blob.like(f"%{norm}%"),
            )
        )
        .limit(20).all()
    )
    # Prefer real name equality first
    rows.sort(key=lambda m: 0 if raw in (
        (m.name_hy or "").lower(), (m.name_ru or "").lower(), (m.name_en or "").lower()
    ) else 1)
    return rows


def _alias_match(db: Session, q: str) -> List[Medicine]:
    norm = normalize(q)
    rows = (
        db.query(Medicine)
        .join(MedicineAlias, MedicineAlias.medicine_id == Medicine.id)
        .filter(or_(
            func.lower(MedicineAlias.alias) == q.strip().lower(),
            MedicineAlias.alias_norm == norm,
            MedicineAlias.alias_norm.like(f"%{norm}%"),
        ))
        .distinct().limit(20).all()
    )
    return rows


def _fuzzy_match(db: Session, q: str, limit: int = 20) -> List[Tuple[Medicine, int]]:
    """RapidFuzz over the normalized search blob."""
    norm_q = normalize(q)
    if not norm_q:
        return []
    # Load lightweight pool (cap to keep it fast on SQLite)
    pool = db.query(Medicine.id, Medicine.search_blob).limit(10000).all()
    choices = {mid: blob or "" for mid, blob in pool}
    matches = process.extract(
        norm_q, choices, scorer=fuzz.WRatio, limit=limit
    )
    # process.extract returns (value, score, key) tuples
    good = [(key, int(score)) for _val, score, key in matches if score >= 60]
    if not good:
        return []
    id_score = {mid: score for mid, score in good}
    rows = db.query(Medicine).filter(Medicine.id.in_(id_score.keys())).all()
    rows.sort(key=lambda m: -id_score.get(m.id, 0))
    return [(m, id_score[m.id]) for m in rows]


def _by_substance(db: Session, substance: str, limit: int = 10) -> List[Medicine]:
    if not substance:
        return []
    norm = normalize(substance)
    return (
        db.query(Medicine)
        .filter(or_(
            func.lower(Medicine.active_substance) == substance.lower(),
            Medicine.search_blob.like(f"%{norm}%"),
        )).limit(limit).all()
    )


def log_unknown(db: Session, q: str, language: str = ""):
    if not q or len(q.strip()) < 2:
        return
    qn = q.strip()[:255]
    row = db.query(UnknownSearch).filter(UnknownSearch.query == qn).first()
    if row:
        row.count += 1
    else:
        db.add(UnknownSearch(query=qn, language=language[:8]))
    db.commit()


def smart_search(db: Session, q: str, language: str = "") -> dict:
    """Returns dict with status, items, suggestions, message."""
    q = (q or "").strip()
    if not q:
        return {"status": "empty", "query": q, "items": [], "suggestions": [], "message": ""}

    # 1) exact
    exact = _exact_match(db, q)
    if exact:
        return {"status": "exact", "query": q, "items": exact, "suggestions": [], "message": ""}

    # 2) alias
    aliased = _alias_match(db, q)
    if aliased:
        return {"status": "alias", "query": q, "items": aliased, "suggestions": [], "message": ""}

    # 3) fuzzy
    fuzzy = _fuzzy_match(db, q, limit=20)
    if fuzzy:
        items = [m for m, _ in fuzzy]
        # Try to infer substance and offer analogs as suggestions
        top = items[0]
        suggestions = [x for x in _by_substance(db, top.active_substance, limit=8)
                       if x.id != top.id]
        return {
            "status": "fuzzy", "query": q, "items": items,
            "suggestions": suggestions,
            "message": "no_exact_match",
        }

    # 4) nothing — log and offer popular unknown queries' best-effort fallback
    log_unknown(db, q, language)
    # Show a few popular medicines as a "did you mean..." cushion
    popular = db.query(Medicine).order_by(Medicine.id).limit(8).all()
    return {
        "status": "empty", "query": q, "items": [],
        "suggestions": popular,
        "message": "no_match",
    }
