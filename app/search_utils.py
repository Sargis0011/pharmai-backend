"""
Normalizaciya teksta dlya poiska:
- lowercase
- ubiraem diakritiku
- transliteraciya armyanskogo -> latinica (priblizhennaya)
- transliteraciya kirillicy -> latinica (GOST-podobno)
Cel': odin obshchiy poiskovyy "blob" rabotaet na hy/ru/en zaprosakh.
"""
import unicodedata

# Armyanskiy -> latinica (chastoye sootvetstvie)
HY_MAP = {
    "ա": "a", "բ": "b", "գ": "g", "դ": "d", "ե": "e", "զ": "z",
    "է": "e", "ը": "y", "թ": "t", "ժ": "zh", "ի": "i", "լ": "l",
    "խ": "kh", "ծ": "ts", "կ": "k", "հ": "h", "ձ": "dz", "ղ": "gh",
    "ճ": "ch", "մ": "m", "յ": "y", "ն": "n", "շ": "sh", "ո": "o",
    "չ": "ch", "պ": "p", "ջ": "j", "ռ": "r", "ս": "s", "վ": "v",
    "տ": "t", "ր": "r", "ց": "ts", "ու": "u", "փ": "p", "ք": "k",
    "օ": "o", "ֆ": "f", "և": "ev",
}

# Kirillica -> latinica
RU_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}


def _translit(text: str) -> str:
    out = []
    i = 0
    low = text.lower()
    while i < len(low):
        # 2-simvol'naya armyanskaya 'ու'
        if i + 1 < len(low) and low[i:i + 2] == "ու":
            out.append("u")
            i += 2
            continue
        ch = low[i]
        if ch in HY_MAP:
            out.append(HY_MAP[ch])
        elif ch in RU_MAP:
            out.append(RU_MAP[ch])
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def normalize(text: str) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    # ubiraem diakritiku (NFKD -> drop combining)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return _translit(text)


def build_search_blob(*parts: str) -> str:
    """
    Sobiraet vse perevody + active_substance v odin normalizovannyy
    blob, gde i original'nye formy, i transliterirovannye.
    """
    pieces = []
    for p in parts:
        if not p:
            continue
        pieces.append(p.lower())
        pieces.append(normalize(p))
    return " | ".join(pieces)


# ---------------------------------------------------------------------------
# Name normalization for "one medicine = one record" rule.
# Strips dosages (mg/ml/g/iu/%), pack info (tab/caps/pcs/шт), forms
# (tablet/capsule/syrup/...), and marketing suffixes (Forte/Plus/Extra/...).
# Keeps the brand identity so duplicates collapse to a single record.
# ---------------------------------------------------------------------------
import re

_FORM_TOKENS = {
    # en
    "tablet", "tablets", "tab", "tabs", "capsule", "capsules", "cap", "caps",
    "syrup", "suspension", "solution", "injection", "ampoule", "ampoules",
    "ampule", "drops", "spray", "ointment", "cream", "gel", "powder", "sachet",
    "sachets", "suppository", "suppositories", "lozenge", "lozenges",
    "granules", "patch", "patches", "film", "elixir",
    # ru
    "таблетка", "таблетки", "таб", "капсула", "капсулы", "капс",
    "сироп", "суспензия", "раствор", "инъекция", "укол", "ампула", "ампулы",
    "капли", "спрей", "мазь", "крем", "гель", "порошок", "пакетик", "пакетики",
    "свеча", "свечи", "суппозиторий", "пастилка", "пастилки", "гранулы",
    "пластырь", "плёнка", "пленка", "эликсир",
    # hy
    "դեղահատ", "դեղահատեր", "հաբ", "հաբեր", "կապսուլա", "կապսուլներ",
    "օշարակ", "լուծույթ", "կաթիլներ", "սփրեյ", "քսուք", "կրեմ", "գել",
    "փոշի", "ամպուլա", "ամպուլներ", "մոմիկ",
}

_MARKETING_TOKENS = {
    "forte", "extra", "plus", "max", "ultra", "advance", "advanced", "rapid",
    "rapidact", "fast", "fastacting", "express", "long", "retard", "sr",
    "xr", "er", "od", "for", "kids", "kid", "junior", "baby", "child",
    "children", "adult", "duo", "trio", "mini", "premium", "complex",
    "active", "actif", "actifast", "soft", "softgel", "chewable",
    "effervescent", "filmcoated",
    # ru
    "форте", "экстра", "плюс", "макс", "ультра", "адванс", "рапид",
    "лонг", "ретард", "детский", "детские", "беби", "малыш", "взрослый",
    "софт", "шипучий", "жевательный",
    # hy
    "ֆորտե", "պլյուս", "մաքս", "մանկական", "երեխա",
}

_DOSAGE_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*"
    r"(?:mg|mcg|µg|ug|g|ml|l|iu|me|ме|мг|мкг|г|мл|л|%)\b"
    r"(?:\s*/\s*\d+(?:[.,]\d+)?\s*(?:mg|ml|г|мл|мг|мкг|l|л))?",
    flags=re.IGNORECASE,
)
_PACK_RE = re.compile(
    r"\b\d+\s*(?:tab|tabs|caps|pcs|шт|n)\b\.?",
    flags=re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*%")
_NUMERIC_TAIL_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_NONWORD = re.compile(r"[^\w\s\u0530-\u058f\u0400-\u04ff-]+", flags=re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_medicine_name(name: str) -> str:
    """Collapse dosage/form/pack/marketing variants of a brand to one canonical form.

    Examples:
        "Nurofen 200mg tablets"      -> "nurofen"
        "Нурофен 400 мг таб."        -> "нурофен"
        "Paracetamol Forte 500 mg"   -> "paracetamol"
        "Aspirin Cardio 75mg"        -> "aspirin cardio"  (Cardio not in marketing list, kept)
    """
    if not name:
        return ""
    s = str(name).strip().lower()
    s = _DOSAGE_RE.sub(" ", s)
    s = _PERCENT_RE.sub(" ", s)
    s = _PACK_RE.sub(" ", s)
    s = _NONWORD.sub(" ", s)
    s = _NUMERIC_TAIL_RE.sub(" ", s)
    # Drop form / marketing tokens
    tokens = [t for t in s.split() if t and t not in _FORM_TOKENS and t not in _MARKETING_TOKENS]
    s = " ".join(tokens)
    s = _WS.sub(" ", s).strip()
    return s


def normalized_key(name: str) -> str:
    """Final canonical key for dedup — transliteration-aware."""
    return normalize(normalize_medicine_name(name))
