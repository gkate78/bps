from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SaleLineIn(BaseModel):
    kind: Literal["service", "load"]
    # service lines
    service_id: Optional[int] = None
    description: Optional[str] = None
    qty: int = 1
    unit_price: Optional[str] = None
    # load lines
    network_id: Optional[int] = None
    wallet_id: Optional[int] = None
    mobile_no: Optional[str] = None
    amount: Optional[str] = None
    is_promo: bool = False
    reference: Optional[str] = None


class SaleIn(BaseModel):
    lines: list[SaleLineIn] = Field(default_factory=list)
    payment_method: Literal["cash", "wallet"] = "cash"
    pay_wallet_id: Optional[int] = None
    payment_reference: Optional[str] = None
    cash: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    bir_invoice_no: Optional[str] = None
    # Job order: pay only a down payment now, the balance when the job is done.
    is_job_order: bool = False
    down_payment: Optional[str] = None
    promised_date: Optional[date] = None


class BalancePaymentIn(BaseModel):
    amount: Optional[str] = None
    payment_method: Literal["cash", "wallet"] = "cash"
    pay_wallet_id: Optional[int] = None
    payment_reference: Optional[str] = None
    cash: Optional[str] = None


class WalletTxnIn(BaseModel):
    kind: Literal["cash_in", "cash_out"]
    wallet_id: int
    amount: Optional[str] = None
    fee_mode: Literal["deducted", "paid_in_cash"] = "deducted"
    customer_mobile: Optional[str] = None
    customer_name: Optional[str] = None
    reference: Optional[str] = None
    tendered: Optional[str] = None


class JobStatusIn(BaseModel):
    status: Literal["in_progress", "ready"]


class VoidIn(BaseModel):
    reason: str = ""
    admin_pin: str = ""
