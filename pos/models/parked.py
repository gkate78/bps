from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class PosParkedTxn(SQLModel, table=True):
    """A shop sale or GCash/Maya transaction put on hold, unpaid, while the next customer is served.

    No money has moved: it's the register screen saved as-is (`data_json`), removed when resumed or discarded.
    """

    __tablename__ = "pos_parked_txns"

    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = Field(max_length=10)  # sale | wallet
    label: str = Field(max_length=160)  # customer name, or "WALK-IN"
    summary: str = Field(default="", max_length=300)
    total_cents: int = Field(default=0, nullable=False)
    data_json: str
    parked_by_user_id: Optional[int] = Field(default=None)
    parked_at: datetime = Field(default_factory=datetime.now, index=True, nullable=False)
