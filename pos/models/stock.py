"""
Materials stock (DEC-077): paper, lamination film and other consumables.

Each pick list item (pos_service_items) can use materials (pos_item_materials), e.g. XEROX "SHORT BACK TO BACK"
uses 1 short bond paper per copy. A sale takes them off the stock; voiding it puts them back. Restocks add stock
and set the average cost; counts correct it. Every change is a row in pos_stock_moves, so stock can be traced.
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class PosMaterial(SQLModel, table=True):
    __tablename__ = "pos_materials"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=80, unique=True, nullable=False)
    unit: str = Field(default="PC", max_length=20, nullable=False)  # what one counts: SHEET, PC, ...
    stock_qty: float = Field(default=0, nullable=False)
    # Warn when stock is at or below this (0 = no warning).
    low_stock_at: float = Field(default=0, nullable=False)
    # Average cost of one unit, in pesos (from restocks).
    avg_cost: float = Field(default=0, nullable=False)
    # Set by the first restock or count: until then the stock isn't known and no low-stock warning is given.
    counted_at: Optional[datetime] = Field(default=None)
    sort_order: int = Field(default=0, nullable=False)
    is_active: bool = Field(default=True, nullable=False)


class PosItemMaterial(SQLModel, table=True):
    """How much of a material one unit of a pick list item uses (e.g. 1 sheet per copy)."""

    __tablename__ = "pos_item_materials"

    id: Optional[int] = Field(default=None, primary_key=True)
    service_item_id: int = Field(foreign_key="pos_service_items.id", index=True, nullable=False)
    material_id: int = Field(foreign_key="pos_materials.id", index=True, nullable=False)
    qty_per_unit: float = Field(default=1, nullable=False)


class PosStockMove(SQLModel, table=True):
    """
    One change to a material's stock. kind: sale (used, qty < 0), void (a voided sale's use put back),
    restock (bought, qty > 0, with its cost), count (a count's difference), adjust (a correction),
    reject (wasted: misprint, paper jam, customer reprint; qty < 0, with its reason and, if given, the sale it was for).
    """

    __tablename__ = "pos_stock_moves"

    id: Optional[int] = Field(default=None, primary_key=True)
    material_id: int = Field(foreign_key="pos_materials.id", index=True, nullable=False)
    kind: str = Field(max_length=12, nullable=False, index=True)
    qty: float = Field(nullable=False)
    stock_after: float = Field(nullable=False)
    # Cost of this move in centavos: what a restock cost, or the material used by a sale at the average cost.
    cost_cents: int = Field(default=0, nullable=False)
    sale_id: Optional[int] = Field(default=None, index=True)
    sale_line_id: Optional[int] = Field(default=None)
    service_id: Optional[int] = Field(default=None)
    supplier: Optional[str] = Field(default=None, max_length=80)
    reason: Optional[str] = Field(default=None, max_length=20)  # rejects: MISPRINT, PAPER JAM, CUSTOMER REPRINT, OTHER
    note: Optional[str] = Field(default=None, max_length=160)
    user_id: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.now, nullable=False, index=True)
