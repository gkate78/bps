from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

DEFAULT_RECEIPT_FOOTER = "THIS IS NOT AN OFFICIAL RECEIPT"


class PosSettings(SQLModel, table=True):
    """
    Single row (id=1): register settings and fee rules. The business_* columns are from the
    standalone register; receipts now use the BPS business profile.
    """

    __tablename__ = "pos_settings"

    id: Optional[int] = Field(default=None, primary_key=True)
    business_name: str = Field(default="DITTO DIGITAL PRINTSHOP", max_length=160)
    business_address: str = Field(default="", max_length=255)
    business_phone: Optional[str] = Field(default=None, max_length=40)
    tin_number: Optional[str] = Field(default=None, max_length=64)
    receipt_footer: str = Field(default=DEFAULT_RECEIPT_FOOTER, max_length=255)

    fee_block_cents: int = Field(default=100_000, nullable=False)
    fee_block_fee_cents: int = Field(default=2_000, nullable=False)
    load_small_max_cents: int = Field(default=5_000, nullable=False)
    load_small_fee_cents: int = Field(default=500, nullable=False)
    promo_round_cents: int = Field(default=1_000, nullable=False)
    # End of day: the usual cash the drawer starts with (filled in, can be changed per day).
    default_starting_cash_cents: int = Field(default=0, nullable=False)

    updated_at: datetime = Field(default_factory=datetime.now, nullable=False)


class PosFeeBracket(SQLModel, table=True):
    """Fee on the remainder after full blocks, e.g. ₱1-₱499 -> ₱10."""

    __tablename__ = "pos_fee_brackets"

    id: Optional[int] = Field(default=None, primary_key=True)
    min_cents: int = Field(nullable=False)
    max_cents: int = Field(nullable=False)
    fee_cents: int = Field(nullable=False)


class PosService(SQLModel, table=True):
    """Shop service buttons on the register (Printing, Xerox, ID Picture, ...)."""

    __tablename__ = "pos_services"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=60, unique=True)
    sort_order: int = Field(default=0, nullable=False)
    is_active: bool = Field(default=True, nullable=False)


class PosNetwork(SQLModel, table=True):
    """Mobile networks for loading. Kept for the record; load is sent from a wallet."""

    __tablename__ = "pos_networks"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=40, unique=True)
    sort_order: int = Field(default=0, nullable=False)
    is_active: bool = Field(default=True, nullable=False)


class PosWallet(SQLModel, table=True):
    """The shop's GCash / Maya accounts. Loading and cash-in/cash-out go through these."""

    __tablename__ = "pos_wallets"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=60, unique=True)
    provider: str = Field(max_length=20)  # GCASH | MAYA
    is_active: bool = Field(default=True, nullable=False)
