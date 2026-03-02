from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class BillRecord(SQLModel, table=True):
    __tablename__ = "bill_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    txn_datetime: datetime = Field(default_factory=datetime.utcnow, index=True, nullable=False)
    txn_date: date = Field(index=True)
    account: str = Field(max_length=64, index=True)
    biller: str = Field(max_length=120, index=True)
    customer_name: str = Field(max_length=160, index=True)
    cp_number: str = Field(max_length=32)

    bill_amt: float = Field(default=0)
    amt2: float = Field(default=0)
    charge: float = Field(default=0)
    total: float = Field(default=0)
    cash: float = Field(default=0)
    change_amt: float = Field(default=0)

    due_date: Optional[date] = Field(default=None, index=True)
    notes: Optional[str] = Field(default=None, max_length=500)
    reference: Optional[str] = Field(default=None, max_length=120)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
