from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class PosSale(SQLModel, table=True):
    """A shop transaction: service lines and load lines, paid in cash."""

    __tablename__ = "pos_sales"

    id: Optional[int] = Field(default=None, primary_key=True)
    sale_no: Optional[str] = Field(default=None, max_length=20, index=True, unique=True)
    cashier_user_id: int = Field(index=True)
    customer_name: Optional[str] = Field(default=None, max_length=160)
    customer_phone: Optional[str] = Field(default=None, max_length=11)
    bir_invoice_no: Optional[str] = Field(default=None, max_length=40, index=True)

    total_cents: int = Field(default=0, nullable=False)
    # cash: cash_cents/change_cents are used. wallet: the customer sent the total to pay_wallet_id.
    payment_method: str = Field(default="cash", max_length=10, index=True)  # cash | wallet
    pay_wallet_id: Optional[int] = Field(default=None, index=True)
    pay_wallet_name: Optional[str] = Field(default=None, max_length=60)
    payment_reference: Optional[str] = Field(default=None, max_length=60, index=True)
    cash_cents: int = Field(default=0, nullable=False)
    change_cents: int = Field(default=0, nullable=False)
    # Paid at checkout: the total for a regular sale, the down payment for a job order.
    checkout_paid_cents: int = Field(default=0, nullable=False)
    # Paid so far (checkout + balance payments); balance = total - amount_paid.
    amount_paid_cents: int = Field(default=0, nullable=False)

    # Job orders (tarpaulin, invitations, ...): down payment now, balance when the job is done.
    is_job_order: bool = Field(default=False, nullable=False, index=True)
    job_status: Optional[str] = Field(default=None, max_length=12, index=True)  # in_progress | ready | completed
    promised_date: Optional[date] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)

    status: str = Field(default="completed", max_length=12, index=True)  # completed | voided
    void_reason: Optional[str] = Field(default=None, max_length=255)
    voided_by_user_id: Optional[int] = Field(default=None)
    voided_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.now, index=True, nullable=False)

    @property
    def balance_cents(self) -> int:
        return self.total_cents - self.amount_paid_cents


class PosSalePayment(SQLModel, table=True):
    """A later payment on a job order (the balance, or part of it). Counted on the day it's received."""

    __tablename__ = "pos_sale_payments"

    id: Optional[int] = Field(default=None, primary_key=True)
    payment_no: Optional[str] = Field(default=None, max_length=20, index=True, unique=True)
    sale_id: int = Field(index=True, foreign_key="pos_sales.id")
    cashier_user_id: int = Field(index=True)
    amount_cents: int = Field(nullable=False)
    payment_method: str = Field(default="cash", max_length=10)  # cash | wallet
    pay_wallet_id: Optional[int] = Field(default=None)
    pay_wallet_name: Optional[str] = Field(default=None, max_length=60)
    payment_reference: Optional[str] = Field(default=None, max_length=60, index=True)
    cash_cents: int = Field(default=0, nullable=False)
    change_cents: int = Field(default=0, nullable=False)
    balance_after_cents: int = Field(default=0, nullable=False)

    status: str = Field(default="completed", max_length=12, index=True)
    void_reason: Optional[str] = Field(default=None, max_length=255)
    voided_by_user_id: Optional[int] = Field(default=None)
    voided_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.now, index=True, nullable=False)


class PosSaleLine(SQLModel, table=True):
    """
    kind=service: description, qty x unit price.
    kind=load: load_cents is sent from wallet_id, which deducts wallet_cost_cents (after the app's
    discount); line_total_cents is what the customer paid (promo price rounded up + fee), so shop
    income is line_total_cents - cost_cents.
    Names are copied onto the line so later renames don't change old sales.
    """

    __tablename__ = "pos_sale_lines"

    id: Optional[int] = Field(default=None, primary_key=True)
    sale_id: int = Field(index=True, foreign_key="pos_sales.id")
    kind: str = Field(max_length=12)  # service | load
    service_id: Optional[int] = Field(default=None, index=True)
    service_name: str = Field(max_length=60)
    description: Optional[str] = Field(default=None, max_length=160)
    qty: int = Field(default=1, nullable=False)
    unit_price_cents: int = Field(default=0, nullable=False)
    line_total_cents: int = Field(default=0, nullable=False)

    network_id: Optional[int] = Field(default=None)
    network_name: Optional[str] = Field(default=None, max_length=40)
    wallet_id: Optional[int] = Field(default=None, index=True)
    wallet_name: Optional[str] = Field(default=None, max_length=60)
    mobile_no: Optional[str] = Field(default=None, max_length=11)
    is_promo: bool = Field(default=False, nullable=False)
    load_cents: int = Field(default=0, nullable=False)
    wallet_cost_cents: Optional[int] = Field(default=None)  # empty on loads from before discounts: the full load
    fee_cents: int = Field(default=0, nullable=False)
    reference: Optional[str] = Field(default=None, max_length=60)

    @property
    def cost_cents(self) -> int:
        return self.load_cents if self.wallet_cost_cents is None else self.wallet_cost_cents
