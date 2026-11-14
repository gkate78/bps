from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SaleLineIn(BaseModel):
    # Besides services and loads, a sale can carry what the customer pays (or gets) together with it;
    # each is saved in its own records, linked to the sale:
    # cash_in: a GCash/Maya cash-in (wallet_id, mobile_no, amount; reference once it's sent).
    # cash_out: a GCash/Maya cash-out (wallet_id it was received in, mobile_no, amount, fee_mode, reference).
    # bill: a bill (BPS bill_records).
    # payback: the customer pays back a bill the shop paid twice to the biller (reference = that bill's BPS reference).
    kind: Literal["service", "load", "cash_in", "cash_out", "bill", "payback"]
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
    fee_mode: Literal["deducted", "paid_in_cash", "included"] = "deducted"  # cash-out lines
    bill: Optional["BillIn"] = None  # bill lines


class SaleIn(BaseModel):
    lines: list[SaleLineIn] = Field(default_factory=list)
    # cash, the shop's GCash/Maya (pay_wallet_id) or its bank account (bank).
    payment_method: Literal["cash", "wallet", "bank"] = "cash"
    pay_wallet_id: Optional[int] = None
    bank: Optional[Literal["BDO", "BPI"]] = None
    payment_reference: Optional[str] = None
    # Paid by GCash/Maya and the customer sent more: the extra is a cash-out with its fee included.
    amount_sent: Optional[str] = None
    cash: Optional[str] = None
    # Cash sale, part paid to the shop's GCash/Maya: that account, the amount sent and its reference no.
    split_wallet_id: Optional[int] = None
    split_amount: Optional[str] = None
    split_reference: Optional[str] = None
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


class BillIn(BaseModel):
    """One bill in a register bills checkout; saved to bill_records like a bill from the entry form."""

    account: str = ""
    biller: str = ""
    customer_name: str = ""
    cp_number: str = ""
    due_date: Optional[date] = None
    bill_amt: Optional[str] = None
    payment_reference: Optional[str] = None  # from the biller, if it's paid to the biller right away
    late_charge: Optional[str] = None  # typed from the printed bill when overdue; empty = the biller rule's


class BillsCheckoutIn(BaseModel):
    """Several bills (any billers and accounts) paid together in one payment."""

    bills: list[BillIn] = Field(default_factory=list)
    payment_method: Literal["CASH", "GCASH", "MAYA", "BDO", "BPI"] = "CASH"
    # The customer's GCash/Maya/bank transfer reference no. (one transfer for all the bills).
    reference: Optional[str] = None
    cash: Optional[str] = None
    # Admin (or business owner) only: own bills, no service charge; "shop" = paid from shop funds.
    personal: Optional[Literal["paid", "shop"]] = None


class ParkIn(BaseModel):
    kind: Literal["sale", "wallet", "bills"]
    label: str = ""
    summary: str = ""
    total_cents: int = 0
    data: dict[str, Any]


SaleLineIn.model_rebuild()
