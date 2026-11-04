from datetime import date, datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class PosDayClose(SQLModel, table=True):
    """End of day for the one cash drawer (bills + shop): starting cash, the count, and the result."""

    __tablename__ = "pos_day_closes"

    id: Optional[int] = Field(default=None, primary_key=True)
    day: date = Field(index=True, unique=True)
    opening_cash_cents: int = Field(default=0, nullable=False)
    counted_cash_cents: Optional[int] = Field(default=None)
    expected_cash_cents: int = Field(default=0, nullable=False)  # as computed when saved
    notes: Optional[str] = Field(default=None, max_length=500)
    closed_by_user_id: Optional[int] = Field(default=None)
    closed_at: Optional[datetime] = Field(default=None)


class PosDayWallet(SQLModel, table=True):
    """Opening and counted balance of one GCash/Maya account for a day."""

    __tablename__ = "pos_day_wallets"
    __table_args__ = (UniqueConstraint("day", "wallet_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    day: date = Field(index=True)
    wallet_id: int = Field(index=True)
    opening_cents: int = Field(default=0, nullable=False)
    counted_cents: Optional[int] = Field(default=None)
    expected_cents: int = Field(default=0, nullable=False)


class PosCashMovement(SQLModel, table=True):
    """
    Cash taken out of or put into the drawer that isn't a sale: owner pickup, bank deposit,
    buying supplies, adding change; or moving money between the drawer and a GCash/Maya account.
      take_out: drawer -    add: drawer +    to_wallet: drawer -, wallet +    from_wallet: drawer +, wallet -
    """

    __tablename__ = "pos_cash_movements"

    id: Optional[int] = Field(default=None, primary_key=True)
    day: date = Field(index=True)
    kind: str = Field(max_length=12)  # take_out | add | to_wallet | from_wallet
    wallet_id: Optional[int] = Field(default=None)
    wallet_name: Optional[str] = Field(default=None, max_length=60)
    amount_cents: int = Field(nullable=False)
    reason: str = Field(max_length=160)
    user_id: int = Field(index=True)
    status: str = Field(default="completed", max_length=12)  # completed | voided
    voided_by_user_id: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.now, nullable=False)

    @property
    def drawer_delta_cents(self) -> int:
        return self.amount_cents if self.kind in ("add", "from_wallet") else -self.amount_cents
