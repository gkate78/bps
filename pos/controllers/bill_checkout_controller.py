"""
Bills at the register: several bills (any billers and accounts) paid together in one payment.

Each bill is saved to `bill_records` exactly like one from the BPS entry form (same charges, checks,
reference, customer list, audit log and SMS); the register keeps no copy of it. End of day already
counts bills from `bill_records`, so nothing else changes there.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.bill_controller import (
    build_record,
    check_account_for_biller,
    has_active_biller_rule,
    find_monthly_duplicate,
    monthly_duplicate_message,
    quote_bill,
)
from pos.auth_adapter import User
from pos.controllers.sale_controller import PosError, _check_reference, _money, clean_text
from pos.controllers.settings_controller import add_audit
from pos.models import PosSale, PosSaleBill, PosWallet
from pos.money import cash_due_cents
from pos.schemas import BillIn, BillsCheckoutIn

MAX_BILLS = 20
WALLET_METHODS = ("GCASH", "MAYA")
METHOD_NAMES = {"CASH": "cash", "GCASH": "GCash", "MAYA": "Maya", "BDO": "BDO", "BPI": "BPI"}


def peso_cents(value) -> int:
    return int(round(float(value or 0) * 100))


def _label(index: int, bill: BillIn) -> str:
    biller = clean_text(bill.biller, 120) or "?"
    account = clean_text(bill.account, 64) or "?"
    return f"Bill {index} ({biller} {account})"


def _detail(exc: HTTPException) -> str:
    return exc.detail if isinstance(exc.detail, str) else "please check the details"


async def quote(
    db: AsyncSession, *, biller: str, account: str, amount: str, due_date: Optional[date], personal: bool
) -> dict:
    """Charges for one bill before it's added to the list, with the checks the save makes."""
    key = clean_text(biller, 120)
    if not key:
        raise PosError("Enter the biller")
    if not await has_active_biller_rule(db, key):
        return {"needs_rule": True, "biller": key}
    account_key = clean_text(account, 64)
    if account_key:
        error = await check_account_for_biller(db, account_key, key)
        if error:
            raise PosError(error)
    cents = _money(amount, "Bill amount")
    if cents <= 0:
        raise PosError("Bill amount must be more than zero")
    existing = account_key and await find_monthly_duplicate(db, account=account_key, bill_amt=cents / 100)
    if existing:
        raise PosError(monthly_duplicate_message(account_key, cents / 100, existing))
    amounts = await quote_bill(db, biller=key, bill_amt=cents / 100, due_date=due_date, personal="paid" if personal else None)
    return {
        "needs_rule": False,
        "biller": key,
        "bill_cents": peso_cents(amounts["bill_amt"]),
        "late_charge_cents": peso_cents(amounts["late_charge"]),
        "charge_cents": peso_cents(amounts["charge"]),
        "total_cents": peso_cents(amounts["total"]),
    }


async def prepare_bills(
    db: AsyncSession, bills: list[BillIn], *, method: Optional[str], reference: Optional[str], personal: Optional[str],
    user: User, now: datetime, first_index: int = 1,
) -> list[tuple[str, dict, int]]:
    """Check every bill (nothing is saved): (label, payload for build_record, total cents) for each.
    method is the bill_records payment method (None for bills paid from shop funds)."""
    # Imported here: bill_routes is BPS's web layer, loaded once the app is set up.
    from app.routes.bill_routes import RecordCreate, prepare_new_record

    prepared: list[tuple[str, dict, int]] = []
    seen: set[tuple[str, int]] = set()  # same account and amount: a duplicate
    for index, bill in enumerate(bills, start=first_index):
        label = _label(index, bill)
        biller = clean_text(bill.biller, 120)
        account = clean_text(bill.account, 64)
        if not account or not biller or not clean_text(bill.customer_name, 160):
            raise PosError(f"{label}: enter the account, biller and customer name")
        amount = _money(bill.bill_amt, f"{label} amount")
        if not await has_active_biller_rule(db, biller):
            raise PosError(f"{label}: {biller} has no biller rule yet. Add it first.")
        if (account, amount) in seen:
            raise PosError(f"{label}: duplicate, the same account and amount is already in the list")
        seen.add((account, amount))
        try:
            record_in = RecordCreate(
                txn_datetime=now,
                account=account,
                biller=biller,
                customer_name=clean_text(bill.customer_name, 160),
                cp_number=bill.cp_number or "",
                bill_amt=amount / 100,
                due_date=bill.due_date,
                payment_method=method,
                confirmation_reference=reference,
                payment_reference=clean_text(bill.payment_reference, 120),
                personal=personal,
            )
            payload = await prepare_new_record(db, record_in, user)
        except ValidationError as exc:
            raise PosError(f"{label}: please check the details") from exc
        except HTTPException as exc:
            raise PosError(f"{label}: {_detail(exc)}") from exc
        existing = await find_monthly_duplicate(db, account=account, bill_amt=amount / 100, txn_date=now.date())
        if existing:
            raise PosError(f"{label}: {monthly_duplicate_message(account, amount / 100, existing)}")
        amounts = await quote_bill(db, biller=biller, bill_amt=amount / 100, due_date=bill.due_date, personal=personal)
        prepared.append((label, payload, peso_cents(amounts["total"])))
    return prepared


async def add_bills(db: AsyncSession, prepared: list[tuple[str, dict, int]], cash_each: list[int]) -> list:
    """Add the checked bills to the session (flushed, not committed); cash_each is each bill's cash in cents."""
    records = []
    for (label, payload, _), cents in zip(prepared, cash_each):
        payload["cash"] = cents / 100
        try:
            record = await build_record(db, payload)
        except HTTPException as exc:
            raise PosError(f"{label}: {_detail(exc)}") from exc
        db.add(record)
        await db.flush()
        records.append(record)
    return records


async def finish_bills(db: AsyncSession, records: list, user: User) -> None:
    """After the commit: customer list, audit log and SMS for each bill, as from the entry form."""
    from app.routes.bill_routes import finish_new_record

    for record in records:
        await db.refresh(record)
        await finish_new_record(db, record, user, channel="register")


async def _bills_sale(db: AsyncSession, records: list, *, method: Optional[str], reference: Optional[str],
                     cash: int, change: int, personal: Optional[str], user: User) -> PosSale:
    """
    A sale of only these bills, as when they're rung up in the shop sale: it holds the one payment
    (cash and change, or the GCash/Maya/bank transfer) for the receipt and the History list. Its own
    total is zero, so Summary and End of day still count the bills from their own records only.
    """
    if method is None:
        payment = {"payment_method": "shop"}
    elif method == "CASH":
        payment = {"payment_method": "cash", "cash_cents": cash, "change_cents": change}
    elif method in WALLET_METHODS:
        wallet = (
            await db.execute(
                select(PosWallet).where(PosWallet.provider == method, PosWallet.is_active).order_by(PosWallet.id).limit(1)
            )
        ).scalar_one_or_none()
        payment = {"payment_method": "wallet", "pay_wallet_id": wallet.id if wallet else None,
                   "pay_wallet_name": wallet.name if wallet else method, "payment_reference": reference}
    else:
        payment = {"payment_method": "bank", "pay_wallet_name": method, "payment_reference": reference}
    first = records[0]
    sale = PosSale(
        cashier_user_id=user.id, customer_name=first.customer_name, total_cents=0, checkout_paid_cents=0,
        amount_paid_cents=0, personal=personal, **payment,
    )
    db.add(sale)
    await db.flush()
    sale.sale_no = f"S-{sale.id:06d}"
    for record in records:
        db.add(PosSaleBill(sale_id=sale.id, bill_record_id=record.id))
    add_audit(db, "sale", sale.id, "create", user.id, {"sale_no": sale.sale_no, "bills": len(records), "from": "bills tab"})
    return sale


async def checkout(db: AsyncSession, data: BillsCheckoutIn, user: User) -> dict:
    if not data.bills:
        raise PosError("Add at least one bill")
    if len(data.bills) > MAX_BILLS:
        raise PosError(f"At most {MAX_BILLS} bills at a time")

    method = None if data.personal == "shop" else data.payment_method  # from shop funds: nothing received
    reference = clean_text(data.reference, 120) if method and method != "CASH" else None
    if method in WALLET_METHODS:
        if not reference:
            raise PosError(f"Enter the {METHOD_NAMES[method]} reference no.")
        await _check_reference(db, reference)  # one transfer, used once: not again for a cash-in or sale

    prepared = await prepare_bills(
        db, data.bills, method=method, reference=reference, personal=data.personal, user=user, now=datetime.now()
    )
    totals = [total for _, _, total in prepared]
    if method is None:
        due, cash, cash_each = 0, 0, [0] * len(prepared)
    elif method == "CASH":
        # Each bill is collected to the whole peso (as on the entry form and in End of day).
        cash_each = [cash_due_cents(total) for total in totals]
        due = sum(cash_each)
        cash = _money(data.cash, "Cash received")
        if cash < due:
            raise PosError(f"Cash received is less than the total (₱{due / 100:,.2f})")
        cash_each[-1] += cash - due  # the change is on the last bill, so the bills add up to what was handed over
    else:
        cash_each = list(totals)  # GCash, Maya and bank: exact, no change
        due = cash = sum(totals)

    try:
        records = await add_bills(db, prepared, cash_each)
        sale = await _bills_sale(db, records, method=method, reference=reference, cash=cash, change=cash - due,
                                 personal=data.personal, user=user)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await finish_bills(db, records, user)

    first = records[0]
    return {
        "sale_id": sale.id,
        "sale_no": sale.sale_no,
        "ids": [r.id for r in records],
        "references": [r.reference for r in records],
        "count": len(records),
        "total_cents": sum(totals),
        "due_cents": due,
        "cash_cents": cash,
        "change_cents": cash - due,
        "payment_method": method,
        "customer_name": first.customer_name,
        "cp_number": first.cp_number,
    }
