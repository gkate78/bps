from datetime import date
from typing import Any, Literal, Optional

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
    deducted: Optional[str] = None  # what the GCash/Maya app deducted; blank = the account's discount
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
    # Admin only: own sale, loads without fees; "shop" = paid from shop funds.
    personal: Optional[Literal["paid", "shop"]] = None


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
    fee_mode: Literal["deducted", "paid_in_cash", "included"] = "deducted"
    customer_mobile: Optional[str] = None
    customer_name: Optional[str] = None
    reference: Optional[str] = None
    tendered: Optional[str] = None
    # Admin only: no fee; "shop" = cash-in sent from shop funds.
    personal: Optional[Literal["paid", "shop"]] = None


class JobStatusIn(BaseModel):
    status: Literal["in_progress", "ready"]


class VoidIn(BaseModel):
    reason: str = ""
    admin_pin: str = ""


class ParkIn(BaseModel):
    kind: Literal["sale", "wallet"]
    label: str = ""
    summary: str = ""
    total_cents: int = 0
    data: dict[str, Any]
