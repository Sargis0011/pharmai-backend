from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class I18nText(BaseModel):
    hy: str = ""
    ru: str = ""
    en: str = ""


# ---------- Variants ----------
class VariantIn(BaseModel):
    form: str = ""
    dosage: str = ""
    package_info: str = ""


class VariantOut(VariantIn):
    id: int
    medicine_id: int

    class Config:
        from_attributes = True


# ---------- Aliases ----------
class AliasIn(BaseModel):
    alias: str
    medicine_id: int
    active_substance: str = ""


class AliasOut(AliasIn):
    id: int

    class Config:
        from_attributes = True


# ---------- Categories ----------
class CategoryIn(BaseModel):
    key: str
    name_hy: str = ""
    name_ru: str = ""
    name_en: str = ""


class CategoryOut(CategoryIn):
    id: int

    class Config:
        from_attributes = True


# ---------- Medicines ----------
class MedicineBase(BaseModel):
    name_hy: str
    name_ru: str = ""
    name_en: str = ""
    active_substance: str = ""
    form: str = ""
    dosage: str = ""
    manufacturer: str = ""
    country: str = ""
    image_url: str = ""
    category: str = "other"
    registered_in_am: int = 1


class MedicineCreate(MedicineBase):
    description: Dict[str, str] = Field(default_factory=dict)
    indications: Dict[str, str] = Field(default_factory=dict)
    symptoms: Dict[str, str] = Field(default_factory=dict)
    side_effects: Any = Field(default_factory=list)
    contraindications: Any = Field(default_factory=list)
    instruction: Dict[str, str] = Field(default_factory=dict)
    variants: List[VariantIn] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)


class MedicineUpdate(BaseModel):
    name_hy: Optional[str] = None
    name_ru: Optional[str] = None
    name_en: Optional[str] = None
    active_substance: Optional[str] = None
    form: Optional[str] = None
    dosage: Optional[str] = None
    manufacturer: Optional[str] = None
    country: Optional[str] = None
    image_url: Optional[str] = None
    category: Optional[str] = None
    registered_in_am: Optional[int] = None
    description: Optional[Dict[str, str]] = None
    indications: Optional[Dict[str, str]] = None
    symptoms: Optional[Dict[str, str]] = None
    side_effects: Optional[Any] = None
    contraindications: Optional[Any] = None
    instruction: Optional[Dict[str, str]] = None


class MedicineOut(MedicineBase):
    id: int
    description: I18nText = Field(default_factory=I18nText)
    indications: I18nText = Field(default_factory=I18nText)
    symptoms: I18nText = Field(default_factory=I18nText)
    side_effects: Any = Field(default_factory=list)
    contraindications: Any = Field(default_factory=list)
    instruction: I18nText = Field(default_factory=I18nText)
    variants: List[VariantOut] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class MedicineListItem(BaseModel):
    id: int
    name_hy: str
    name_ru: str
    name_en: str
    active_substance: str
    form: str
    dosage: str
    category: str
    manufacturer: str

    class Config:
        from_attributes = True


class PharmacyOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


# ---------- Pharmacy chains + branches ----------
class BranchIn(BaseModel):
    chain_id: Optional[int] = None
    branch_name: str = ""
    city: str = ""
    address: str = ""
    phone: str = ""
    working_hours: str = ""
    status: str = "active"


class BranchOut(BranchIn):
    id: int
    chain_id: int

    class Config:
        from_attributes = True


class ChainIn(BaseModel):
    key: str
    name: str
    description_hy: str = ""
    description_ru: str = ""
    description_en: str = ""
    logo_url: str = ""
    website: str = ""


class ChainOut(ChainIn):
    id: int
    branches_count: int = 0

    class Config:
        from_attributes = True


class ChainDetailOut(ChainOut):
    branches: List[BranchOut] = Field(default_factory=list)


class SearchResponse(BaseModel):
    total: int
    items: List[MedicineListItem]


class SmartSearchResponse(BaseModel):
    status: str  # "exact" | "alias" | "fuzzy" | "analog" | "empty"
    query: str
    total: int
    items: List[MedicineListItem]
    suggestions: List[MedicineListItem] = Field(default_factory=list)
    message: str = ""


class StatsResponse(BaseModel):
    medicines: int
    pharmacies: int
    categories: int
    variants: int = 0
    aliases: int = 0
    chains: int = 0
    branches: int = 0


class UnknownSearchOut(BaseModel):
    id: int
    query: str
    language: str
    count: int

    class Config:
        from_attributes = True


class ImportReport(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: List[str] = Field(default_factory=list)
