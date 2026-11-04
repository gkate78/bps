from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class PosWalletTxn(SQLModel, table=True):
    """
    GCash/Maya cash-in or cash-out. Its own transaction, never mixed with shop sales.
    collect_cents: cash the customer handed over for this transaction (before change).
    give_cents: cash the shop handed to the customer.
    Drawer moves by collect - give; the wallet moves by -amount (cash-in) or +amount (cash-out).
    """

    __tablename__ = "pos_wallet_txns"

    id: Optional[int] = Field(default=None, primary_key=True)
    txn_no: Optional[str] = Field(default=None, max_length=20, index=True, unique=True)
    cashier_user_id: int = Field(index=True)
    kind: str = Field(max_length=10, index=True)  # cash_in | cash_out
    wallet_id: int = Field(index=True)
    wallet_name: str = Field(max_length=60)
    amount_cents: int = Field(nullable=False)
    fee_cents: int = Field(nullable=False)
    fee_mode: str = Field(max_length=14)  # added | deducted | paid_in_cash
    collect_cents: int = Field(default=0, nullable=False)
    give_cents: int = Field(default=0, nullable=False)
    tendered_cents: int = Field(default=0, nullable=False)
    change_cents: int = Field(default=0, nullable=False)
    customer_mobile: str = Field(max_length=11, index=True)
    customer_name: Optional[str] = Field(default=None, max_length=160)
    reference: str = Field(max_length=60, index=True)

    status: str = Field(default="completed", max_length=12, index=True)
    void_reason: Optional[str] = Field(default=None, max_length=255)
    voided_by_user_id: Optional[int] = Field(default=None)
    voided_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.now, index=True, nullable=False)
