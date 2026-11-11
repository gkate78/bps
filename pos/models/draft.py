from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class PosDraft(SQLModel, table=True):
    """What a cashier is ringing up but hasn't saved yet: the register screen (`data_json`, the same data
    as parking), saved on the server as it changes so a brownout or a closed browser doesn't lose it.

    One per cashier and kind (sale | wallet | bills). Removed when the transaction is saved, parked or
    cleared. No money has moved and nothing counts it.
    """

    __tablename__ = "pos_drafts"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    kind: str = Field(max_length=10)
    label: str = Field(default="", max_length=160)
    summary: str = Field(default="", max_length=300)
    total_cents: int = Field(default=0, nullable=False)
    data_json: str
    updated_at: datetime = Field(default_factory=datetime.now, nullable=False)
