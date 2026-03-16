"""
Customer: one row per account (account unique across all billers).
Stores biller, name, phone for lookup when user enters account. Used for BPS-206 and future customer view.
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Customer(SQLModel, table=True):
    __tablename__ = "customer_accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    account: str = Field(max_length=64, index=True, unique=True)
    biller: str = Field(max_length=120, index=True)
    customer_name: str = Field(max_length=160, index=True)
    phone: str = Field(max_length=11, index=True)  # same semantics as cp_number on BillRecord

    # Optional link to app user for customer portal: "bills I've paid"
    user_id: Optional[int] = Field(default=None, foreign_key="user_accounts.id", index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
