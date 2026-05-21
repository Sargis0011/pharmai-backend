from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from .database import Base


class Medicine(Base):
    """One medicine = one record. Dosages/forms live in MedicineVariant.
    The `form`/`dosage` fields on Medicine are kept as a "primary variant"
    convenience for backward compatibility with the existing API."""
    __tablename__ = "medicines"

    id = Column(Integer, primary_key=True, index=True)

    name_hy = Column(String(255), index=True, nullable=False)
    name_ru = Column(String(255), index=True, default="")
    name_en = Column(String(255), index=True, default="")
    normalized_name = Column(String(255), index=True, default="")

    active_substance = Column(String(255), index=True, default="")

    # Primary/default variant for legacy API
    form = Column(String(120), default="")
    dosage = Column(String(120), default="")

    manufacturer = Column(String(255), default="")
    country = Column(String(120), default="")
    image_url = Column(String(512), default="")

    # Category key — references Category.key (soft FK to keep legacy working)
    category = Column(String(64), index=True, default="other")

    # JSON-serialized {hy,ru,en}
    description = Column(Text, default="{}")
    indications = Column(Text, default="{}")
    symptoms = Column(Text, default="{}")
    side_effects = Column(Text, default="{}")
    contraindications = Column(Text, default="{}")
    instruction = Column(Text, default="{}")

    registered_in_am = Column(Integer, default=1)
    search_blob = Column(Text, index=True, default="")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    variants = relationship("MedicineVariant", back_populates="medicine",
                            cascade="all, delete-orphan")
    aliases = relationship("MedicineAlias", back_populates="medicine",
                           cascade="all, delete-orphan")
    stocks = relationship("PharmacyStock", back_populates="medicine",
                          cascade="all, delete-orphan")


class MedicineVariant(Base):
    """Dosage/form variant. Variants DO NOT create new medicines."""
    __tablename__ = "medicine_variants"

    id = Column(Integer, primary_key=True, index=True)
    medicine_id = Column(Integer, ForeignKey("medicines.id", ondelete="CASCADE"), index=True)
    form = Column(String(120), default="")
    dosage = Column(String(120), default="")
    package_info = Column(String(255), default="")

    medicine = relationship("Medicine", back_populates="variants")


class MedicineAlias(Base):
    """Synonyms / brand names / common misspellings → medicine."""
    __tablename__ = "medicine_aliases"

    id = Column(Integer, primary_key=True, index=True)
    alias = Column(String(255), index=True, nullable=False)
    alias_norm = Column(String(255), index=True, default="")
    medicine_id = Column(Integer, ForeignKey("medicines.id", ondelete="CASCADE"), index=True)
    active_substance = Column(String(255), default="")

    medicine = relationship("Medicine", back_populates="aliases")


class Category(Base):
    """Dynamic, multilingual categories managed via admin panel."""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), unique=True, index=True, nullable=False)
    name_hy = Column(String(120), default="")
    name_ru = Column(String(120), default="")
    name_en = Column(String(120), default="")


class UnknownSearch(Base):
    """Queries that returned no exact result — feeds dataset improvement."""
    __tablename__ = "unknown_searches"

    id = Column(Integer, primary_key=True, index=True)
    query = Column(String(255), index=True, nullable=False)
    language = Column(String(8), default="")
    count = Column(Integer, default=1)
    last_seen = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Pharmacy(Base):
    __tablename__ = "pharmacies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)

    stocks = relationship("PharmacyStock", back_populates="pharmacy",
                          cascade="all, delete-orphan")


class PharmacyStock(Base):
    __tablename__ = "pharmacy_stocks"

    id = Column(Integer, primary_key=True, index=True)
    pharmacy_id = Column(Integer, ForeignKey("pharmacies.id", ondelete="CASCADE"))
    medicine_id = Column(Integer, ForeignKey("medicines.id", ondelete="CASCADE"))

    pharmacy = relationship("Pharmacy", back_populates="stocks")
    medicine = relationship("Medicine", back_populates="stocks")


# ---------------------------------------------------------------------------
# Pharmacy chains + branches (simplified). No search, no filters, no map.
# ---------------------------------------------------------------------------
class PharmacyChain(Base):
    __tablename__ = "pharmacy_chains"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    description_hy = Column(Text, default="")
    description_ru = Column(Text, default="")
    description_en = Column(Text, default="")
    logo_url = Column(String(512), default="")
    website = Column(String(255), default="")
    created_at = Column(DateTime, server_default=func.now())

    branches = relationship(
        "PharmacyBranch",
        back_populates="chain",
        cascade="all, delete-orphan",
        order_by="PharmacyBranch.city, PharmacyBranch.branch_name",
    )


class PharmacyBranch(Base):
    __tablename__ = "pharmacy_branches"

    id = Column(Integer, primary_key=True, index=True)
    chain_id = Column(Integer, ForeignKey("pharmacy_chains.id", ondelete="CASCADE"),
                      index=True, nullable=False)
    branch_name = Column(String(255), default="")
    city = Column(String(120), default="", index=True)
    address = Column(String(512), default="")
    phone = Column(String(64), default="")
    working_hours = Column(String(64), default="")
    status = Column(String(32), default="active")
    created_at = Column(DateTime, server_default=func.now())

    chain = relationship("PharmacyChain", back_populates="branches")
