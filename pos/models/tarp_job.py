from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class PosTarpJob(SQLModel, table=True):
    """
    A tarpaulin to lay out and have printed, one per sale with a TARPAULIN line. Made when the sale is saved and
    given to the designer set in Settings → Tarpaulin; the designer moves it through the steps until it's claimed.
    """

    __tablename__ = "pos_tarp_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    sale_id: int = Field(index=True, unique=True, foreign_key="pos_sales.id")
    designer_user_id: Optional[int] = Field(default=None, index=True)
    status: str = Field(default="layout", max_length=12, index=True)
    specs: Optional[str] = Field(default=None, max_length=1000)  # what the customer wants, typed at the register
    notes: Optional[str] = Field(default=None, max_length=500)  # the designer's own notes
    created_at: datetime = Field(default_factory=datetime.now, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.now, nullable=False)
    claimed_at: Optional[datetime] = Field(default=None)
