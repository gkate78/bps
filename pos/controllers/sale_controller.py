from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import BillRecord
from pos.auth_adapter import User, display_name, normalize_phone, validate_mobile, validate_phone
from pos.controllers.settings_controller import add_audit, get_fee_schedule
from pos.fees import (
    FeeError,
    WalletQuote,
    load_cost,
    nearest_fee_included,
    quote_load,
    quote_personal_load,
    quote_personal_wallet,
    quote_wallet,
)
from pos.money import MoneyError, cash_due_cents, to_cents, to_cents_optional
from pos.models import PosNetwork, PosSale, PosSaleLine, PosSalePayment, PosService, PosWallet, PosWalletTxn
from pos.schemas import BalancePaymentIn, SaleIn, WalletTxnIn

MAX_QTY = 10_000
PERSONAL_LABELS = {"paid": "personal, no fees", "shop": "personal, from shop funds"}
CASH_OUT_FEE_LABELS = {"paid_in_cash": " (fee paid in cash)", "included": " (fee included in amount sent)"}


class PosError(ValueError):
    """A problem the cashier can fix; shown as-is on screen."""


def clean_text(value: Optional[str], max_len: int) -> Optional[str]:
    """Trimmed, single-spaced, uppercase (same convention as BPS); None when blank."""
    cleaned = " ".join(str(value or "").split()).upper()[:max_len]
    return cleaned or None


def _mobile(value: Optional[str], label: str) -> str:
    phone = normalize_phone(value or "")
    if not validate_mobile(phone):
        raise PosError(f"{label} must be an 11-digit number starting with 09")
    return phone


def _money(value, field: str) -> int:
    try:
        return to_cents(value, field=field)
    except MoneyError as exc:
        raise PosError(str(exc)) from exc


async def _get_active(db: AsyncSession, model, item_id: Optional[int], label: str):
    if not item_id:
        raise PosError(f"Choose a {label}")
    item = (await db.execute(select(model).where(model.id == item_id))).scalar_one_or_none()
    if not item or not item.is_active:
        raise PosError(f"That {label} is not available")
    return item


async def _take_payment(db: AsyncSession, method: str, wallet_id, reference, cash_text, due_cents: int) -> dict:
    """Cash (cash received covers what's due; change) or the shop's GCash/Maya (reference no., no change)."""
    if method == "wallet":
        wallet = await _get_active(db, PosWallet, wallet_id, "GCash/Maya account the customer paid to")
        ref = clean_text(reference, 60)
        if not ref:
            raise PosError(f"Enter the {wallet.name} reference no.")
        await _check_reference(db, ref)
        return {
            "payment_method": "wallet",
            "pay_wallet_id": wallet.id,
            "pay_wallet_name": wallet.name,
            "payment_reference": ref,
            "cash_cents": 0,
            "change_cents": 0,
        }
    cash = _money(cash_text, "Cash received")
    collect = cash_due_cents(due_cents)  # cash is collected to the whole peso
    if cash < collect:
        raise PosError(f"Cash received is less than the amount due (₱{collect / 100:,.2f})")
    return {"payment_method": "cash", "cash_cents": cash, "change_cents": cash - collect}


def _check_personal(personal: Optional[str], user: User) -> None:
    if personal and user.role != "admin":
        raise PosError("Only an admin can ring up a personal transaction")


def quote_sale_cash_out(due_cents: int, sent_cents: int, schedule) -> Optional[WalletQuote]:
    """
    The customer paid a sale by GCash/Maya and sent more (₱1,075 for a ₱55 load): the extra is a
    cash-out with its fee included (₱1,020 = ₱1,000 + ₱20 fee, give ₱1,000). None when nothing extra.
    """
    if sent_cents < due_cents:
        raise PosError("Amount sent is less than the amount due")
    extra = sent_cents - due_cents
    if not extra:
        return None
    if extra % 100:
        raise PosError(f"The cash-out part (₱{extra / 100:,.2f}) must be whole pesos. Check the amount sent.")
    try:
        return quote_wallet("cash_out", extra, "included", schedule)
    except (MoneyError, FeeError) as exc:
        payout, fits = nearest_fee_included(extra, schedule)
        # fits > extra: even ₱1 plus its fee is more than what's left over.
        hint = f" The nearest that works: ₱{(due_cents + fits) / 100:,.2f} sent gives ₱{payout / 100:,.2f} cash." if fits <= extra else ""
        raise PosError(f"₱{extra / 100:,.2f} left after the sale isn't a cash-out plus its fee.{hint} Check the amount sent.") from exc


async def linked_cash_out(db: AsyncSession, sale_id: int) -> Optional[PosWalletTxn]:
    return (
        await db.execute(select(PosWalletTxn).where(PosWalletTxn.sale_id == sale_id, PosWalletTxn.kind == "cash_out").limit(1))
    ).scalar_one_or_none()


async def create_sale(db: AsyncSession, data: SaleIn, user: User) -> PosSale:
    if not data.lines:
        raise PosError("Add at least one item")
    _check_personal(data.personal, user)
    if data.personal and data.is_job_order:
        raise PosError("A personal sale can't be a job order")
    schedule = await get_fee_schedule(db)
    lines: list[PosSaleLine] = []
    for line in data.lines:
        if line.kind == "service":
            service = await _get_active(db, PosService, line.service_id, "service")
            if not (1 <= line.qty <= MAX_QTY):
                raise PosError(f"Quantity must be from 1 to {MAX_QTY:,}")
            price = _money(line.unit_price, f"{service.name} price")
            if price < 0 or (price == 0 and not data.personal):
                raise PosError(f"{service.name} price must be more than zero")
            lines.append(
                PosSaleLine(
                    kind="service",
                    service_id=service.id,
                    service_name=service.name,
                    description=clean_text(line.description, 160),
                    qty=line.qty,
                    unit_price_cents=price,
                    line_total_cents=price * line.qty,
                )
            )
        else:
            network = await _get_active(db, PosNetwork, line.network_id, "network")
            wallet = await _get_active(db, PosWallet, line.wallet_id, "wallet to send the load from")
            mobile = _mobile(line.mobile_no, "Load mobile number")
            try:
                amount = _money(line.amount, "Load amount")
                quote = quote_personal_load(amount) if data.personal else quote_load(amount, line.is_promo, schedule)
            except (MoneyError, FeeError) as exc:
                raise PosError(f"Load: {exc}") from exc
            if (line.deducted or "").strip():
                cost = _money(line.deducted, f"Amount {wallet.name} deducted")
                if not 0 < cost <= quote.load_cents:
                    raise PosError(f"Amount {wallet.name} deducted must be more than zero and not more than the load")
            else:
                cost = load_cost(quote.load_cents, wallet.load_discount_bp)
            lines.append(
                PosSaleLine(
                    kind="load",
                    service_name="LOAD",
                    description=clean_text(line.description, 160),
                    qty=1,
                    unit_price_cents=quote.total_cents,
                    line_total_cents=quote.total_cents,
                    network_id=network.id,
                    network_name=network.name,
                    wallet_id=wallet.id,
                    wallet_name=wallet.name,
                    mobile_no=mobile,
                    is_promo=line.is_promo,
                    load_cents=quote.load_cents,
                    wallet_cost_cents=cost,
                    fee_cents=quote.fee_cents,
                    reference=clean_text(line.reference, 60),
                )
            )

    total = sum(line.line_total_cents for line in lines)
    customer_name = clean_text(data.customer_name, 160)
    due = total
    if data.is_job_order:
        if any(line.kind == "load" for line in lines):
            raise PosError("Load must be paid in full. Ring it up as a separate sale.")
        if not customer_name:
            raise PosError("Enter the customer's name for a job order")
        due = _money(data.down_payment, "Down payment")
        if not 0 < due < total:
            raise PosError("Down payment must be more than zero and less than the total")
    if data.personal == "shop":
        payment = {"payment_method": "shop", "cash_cents": 0, "change_cents": 0}
    else:
        payment = await _take_payment(db, data.payment_method, data.pay_wallet_id, data.payment_reference, data.cash, due)
    customer_phone = normalize_phone(data.customer_phone or "") or None
    if customer_phone and not validate_phone(customer_phone):
        raise PosError("Customer phone must be 11 digits")
    cash_out = None
    if (data.amount_sent or "").strip():
        if payment["payment_method"] != "wallet":
            raise PosError("Amount sent is only for a sale paid by GCash/Maya")
        if data.personal:
            raise PosError("A personal sale can't include a cash-out")
        cash_out = quote_sale_cash_out(due, _money(data.amount_sent, "Amount sent"), schedule)
        if cash_out:
            customer_phone = _mobile(data.customer_phone, "Customer mobile no. (needed for the cash-out)")

    sale = PosSale(
        cashier_user_id=user.id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        bir_invoice_no=clean_text(data.bir_invoice_no, 40),
        total_cents=total,
        checkout_paid_cents=due,
        amount_paid_cents=due,
        is_job_order=data.is_job_order,
        job_status="in_progress" if data.is_job_order else None,
        promised_date=data.promised_date if data.is_job_order else None,
        personal=data.personal,
        **payment,
    )
    db.add(sale)
    await db.flush()
    sale.sale_no = f"S-{sale.id:06d}"
    for line in lines:
        line.sale_id = sale.id
        db.add(line)
    if cash_out:
        txn = PosWalletTxn(
            cashier_user_id=user.id,
            kind="cash_out",
            wallet_id=sale.pay_wallet_id,
            wallet_name=sale.pay_wallet_name,
            amount_cents=cash_out.amount_cents,
            fee_cents=cash_out.fee_cents,
            fee_mode=cash_out.fee_mode,
            collect_cents=0,
            give_cents=cash_out.give_cents,
            customer_mobile=customer_phone,
            customer_name=customer_name,
            reference=sale.payment_reference,
            sale_id=sale.id,
        )
        db.add(txn)
        await db.flush()
        txn.txn_no = f"W-{txn.id:06d}"
        add_audit(db, "wallet_txn", txn.id, "create", user.id, {"txn_no": txn.txn_no, "kind": "cash_out", "sale_no": sale.sale_no})
    add_audit(
        db, "sale", sale.id, "create", user.id,
        {"sale_no": sale.sale_no, "total_cents": total, "paid_cents": due, "job_order": data.is_job_order, "personal": data.personal},
    )
    await db.commit()
    await db.refresh(sale)
    return sale


@dataclass(frozen=True)
class UsedReference:
    no: str
    label: str
    amount_cents: int
    at: datetime


async def used_reference(db: AsyncSession, reference: Optional[str]) -> Optional[UsedReference]:
    """
    The completed transaction that already used this GCash/Maya reference no. (ignoring case and
    spaces): a cash-in, a cash-out, a shop sale or job order payment paid by GCash/Maya, or bills
    paid by GCash/Maya (several bills paid with one transfer share it). A
    reference no. belongs to one transaction, so the same receipt can't be claimed or paid with twice.
    Voided transactions don't count.
    """
    key = "".join(str(reference or "").split()).upper()
    if not key:
        return None

    def same(column):
        return func.upper(func.replace(column, " ", "")) == key

    txn = (
        await db.execute(select(PosWalletTxn).where(PosWalletTxn.status == "completed", same(PosWalletTxn.reference)).limit(1))
    ).scalar_one_or_none()
    if txn:
        kind = "cash-in" if txn.kind == "cash_in" else "cash-out"
        return UsedReference(txn.txn_no, f"{txn.wallet_name} {kind}", txn.amount_cents, txn.created_at)
    sale = (
        await db.execute(
            select(PosSale)
            .where(PosSale.status == "completed", PosSale.payment_method == "wallet", same(PosSale.payment_reference))
            .limit(1)
        )
    ).scalar_one_or_none()
    if sale:
        what = "job order down payment" if sale.is_job_order else "shop sale paid"
        return UsedReference(sale.sale_no, f"{sale.pay_wallet_name} {what}", sale.checkout_paid_cents, sale.created_at)
    payment = (
        await db.execute(
            select(PosSalePayment)
            .where(
                PosSalePayment.status == "completed",
                PosSalePayment.payment_method == "wallet",
                same(PosSalePayment.payment_reference),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if payment:
        return UsedReference(payment.payment_no, f"{payment.pay_wallet_name} job order payment", payment.amount_cents, payment.created_at)
    # Bills paid to the shop's GCash/Maya (the customer's confirmation reference).
    bills = (
        await db.execute(
            select(BillRecord)
            .where(
                func.upper(BillRecord.payment_method).in_(("GCASH", "MAYA")),
                same(BillRecord.confirmation_reference),
            )
            .order_by(BillRecord.id)
        )
    ).scalars().all()
    if bills:
        first = bills[0]
        billers = ", ".join(dict.fromkeys(b.biller for b in bills))
        label = f"{first.payment_method} payment for {'bill' if len(bills) == 1 else f'{len(bills)} bills'} ({billers})"
        total = sum(int(round(float(b.total or 0) * 100)) for b in bills)
        return UsedReference(first.reference or f"bill #{first.id}", label, total, first.txn_datetime)
    return None


def used_message(reference: str, used: UsedReference) -> str:
    return (
        f"Reference no. {reference} was already used: {used.no}, {used.label} of "
        f"₱{used.amount_cents / 100:,.2f} on {used.at:%m/%d/%Y %I:%M %p}. Check the customer's receipt; don't accept it again."
    )


async def _check_reference(db: AsyncSession, reference: str) -> None:
    used = await used_reference(db, reference)
    if used:
        raise PosError(used_message(reference, used))


async def create_wallet_txn(db: AsyncSession, data: WalletTxnIn, user: User) -> PosWalletTxn:
    _check_personal(data.personal, user)
    wallet = await _get_active(db, PosWallet, data.wallet_id, "GCash/Maya account")
    amount = _money(data.amount, "Amount")
    try:
        if data.personal:
            quote = quote_personal_wallet(data.kind, amount, from_shop=data.personal == "shop")
        else:
            quote = quote_wallet(data.kind, amount, data.fee_mode, await get_fee_schedule(db))
    except (MoneyError, FeeError) as exc:
        raise PosError(str(exc)) from exc
    mobile = _mobile(data.customer_mobile, "Customer mobile number")
    reference = clean_text(data.reference, 60)
    if not reference:
        raise PosError("Reference no. is required")
    await _check_reference(db, reference)

    tendered = quote.collect_cents
    if quote.collect_cents:
        try:
            tendered = to_cents_optional(data.tendered, field="Cash received")
        except MoneyError as exc:
            raise PosError(str(exc)) from exc
        tendered = quote.collect_cents if tendered is None else tendered
        if tendered < quote.collect_cents:
            raise PosError("Cash received is less than the amount to collect")

    txn = PosWalletTxn(
        cashier_user_id=user.id,
        kind=data.kind,
        wallet_id=wallet.id,
        wallet_name=wallet.name,
        amount_cents=quote.amount_cents,
        fee_cents=quote.fee_cents,
        fee_mode=quote.fee_mode,
        collect_cents=quote.collect_cents,
        give_cents=quote.give_cents,
        tendered_cents=tendered,
        change_cents=tendered - quote.collect_cents,
        customer_mobile=mobile,
        customer_name=clean_text(data.customer_name, 160),
        reference=reference,
        personal=data.personal,
    )
    db.add(txn)
    await db.flush()
    txn.txn_no = f"W-{txn.id:06d}"
    add_audit(db, "wallet_txn", txn.id, "create", user.id, {"txn_no": txn.txn_no, "kind": txn.kind, "personal": txn.personal})
    await db.commit()
    await db.refresh(txn)
    return txn


async def get_sale(db: AsyncSession, sale_id: int) -> tuple[Optional[PosSale], list[PosSaleLine]]:
    sale = (await db.execute(select(PosSale).where(PosSale.id == sale_id))).scalar_one_or_none()
    if not sale:
        return None, []
    lines = (await db.execute(select(PosSaleLine).where(PosSaleLine.sale_id == sale_id).order_by(PosSaleLine.id))).scalars().all()
    return sale, list(lines)


async def get_wallet_txn(db: AsyncSession, txn_id: int) -> Optional[PosWalletTxn]:
    return (await db.execute(select(PosWalletTxn).where(PosWalletTxn.id == txn_id))).scalar_one_or_none()


async def get_payment(db: AsyncSession, payment_id: int) -> Optional[PosSalePayment]:
    return (await db.execute(select(PosSalePayment).where(PosSalePayment.id == payment_id))).scalar_one_or_none()


async def sale_payments(db: AsyncSession, sale_id: int) -> list[PosSalePayment]:
    query = select(PosSalePayment).where(PosSalePayment.sale_id == sale_id).order_by(PosSalePayment.id)
    return list((await db.execute(query)).scalars().all())


def describe_lines(lines: list[PosSaleLine]) -> str:
    parts = []
    for line in lines:
        if line.kind == "load":
            parts.append(f"LOAD {line.network_name} {line.mobile_no} ₱{line.load_cents // 100:,}{' PROMO' if line.is_promo else ''}")
        else:
            parts.append(f"{line.service_name}{' ' + line.description if line.description else ''} ×{line.qty}")
    return "; ".join(parts)


async def _open_job_order(db: AsyncSession, sale_id: int) -> PosSale:
    sale = (await db.execute(select(PosSale).where(PosSale.id == sale_id))).scalar_one_or_none()
    if not sale or not sale.is_job_order:
        raise PosError("Job order not found")
    if sale.status == "voided":
        raise PosError("This job order was voided")
    return sale


async def collect_balance(db: AsyncSession, sale_id: int, data: BalancePaymentIn, user: User) -> PosSalePayment:
    """Payment on a job order's balance. Paying it all marks the job completed."""
    sale = await _open_job_order(db, sale_id)
    if sale.balance_cents <= 0:
        raise PosError("This job order is already fully paid")
    amount = sale.balance_cents if data.amount in (None, "") else _money(data.amount, "Amount")
    if not 0 < amount <= sale.balance_cents:
        raise PosError(f"Amount must be more than zero and at most the balance (₱{sale.balance_cents / 100:,.2f})")
    payment = PosSalePayment(
        sale_id=sale.id,
        cashier_user_id=user.id,
        amount_cents=amount,
        balance_after_cents=sale.balance_cents - amount,
        **await _take_payment(db, data.payment_method, data.pay_wallet_id, data.payment_reference, data.cash, amount),
    )
    db.add(payment)
    sale.amount_paid_cents += amount
    if sale.balance_cents == 0:
        sale.job_status = "completed"
        sale.completed_at = datetime.now()
    db.add(sale)
    await db.flush()
    payment.payment_no = f"P-{payment.id:06d}"
    add_audit(db, "sale_payment", payment.id, "create", user.id, {"sale_no": sale.sale_no, "amount_cents": amount})
    await db.commit()
    await db.refresh(payment)
    return payment


async def set_job_status(db: AsyncSession, sale_id: int, status: str, user: User) -> PosSale:
    """Mark a job ready for pickup (or back to in progress). Completed is set by paying the balance."""
    sale = await _open_job_order(db, sale_id)
    if status not in ("in_progress", "ready"):
        raise PosError("Unknown status")
    if sale.job_status == "completed":
        raise PosError("This job order is already completed")
    sale.job_status = status
    db.add(sale)
    add_audit(db, "sale", sale.id, f"job_{status}", user.id)
    await db.commit()
    return sale


async def list_job_orders(db: AsyncSession, show: str = "open", search: str = "") -> list[dict]:
    query = select(PosSale).where(PosSale.is_job_order, PosSale.status == "completed")
    if show == "open":
        query = query.where(PosSale.job_status != "completed")
    elif show == "completed":
        query = query.where(PosSale.job_status == "completed")
    sales = (await db.execute(query.order_by(PosSale.created_at.desc()).limit(500))).scalars().all()
    lines_by_sale: dict[int, list[PosSaleLine]] = defaultdict(list)
    if sales:
        lines = await db.execute(select(PosSaleLine).where(PosSaleLine.sale_id.in_([s.id for s in sales])).order_by(PosSaleLine.id))
        for line in lines.scalars().all():
            lines_by_sale[line.sale_id].append(line)
    needle = search.strip().upper()
    rows = []
    for sale in sales:
        details = describe_lines(lines_by_sale[sale.id])
        haystack = " ".join(filter(None, [sale.sale_no, details, sale.customer_name, sale.customer_phone]))
        if needle and needle not in haystack.upper():
            continue
        rows.append({"sale": sale, "details": details})
    if show == "open":
        # Soonest promised first; orders without a date after, oldest first.
        rows.sort(key=lambda r: (r["sale"].promised_date is None, r["sale"].promised_date or date.max, r["sale"].created_at))
    return rows


async def void_record(db: AsyncSession, record, entity: str, reason: str, admin: User, user: User) -> None:
    if record.status == "voided":
        raise PosError("Already voided")
    reason = " ".join(reason.split())
    if len(reason) < 3:
        raise PosError("Please give a reason for the void")
    now = datetime.now()

    def mark(item) -> None:
        item.status = "voided"
        item.void_reason = reason[:255]
        item.voided_by_user_id = admin.id
        item.voided_at = now
        db.add(item)

    if entity == "sale":
        # The cash-out sent in the same transfer goes with the sale.
        linked = await linked_cash_out(db, record.id)
        if linked and linked.status != "voided":
            mark(linked)
    if entity == "sale" and record.is_job_order:
        # Voiding a job order voids its balance payments too.
        for payment in await sale_payments(db, record.id):
            if payment.status != "voided":
                mark(payment)
    if entity == "sale_payment":
        # Voiding a balance payment puts that amount back on the job order's balance.
        sale = (await db.execute(select(PosSale).where(PosSale.id == record.sale_id))).scalar_one()
        if sale.status == "voided":
            raise PosError("The job order itself was voided")
        sale.amount_paid_cents -= record.amount_cents
        if sale.job_status == "completed":
            sale.job_status = "ready"
            sale.completed_at = None
        db.add(sale)
    mark(record)
    add_audit(db, entity, record.id, "void", user.id, {"reason": reason, "approved_by": admin.id})
    await db.commit()


def day_range(start: date, end: date) -> tuple[datetime, datetime]:
    return datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)


async def _users_by_id(db: AsyncSession) -> dict[int, User]:
    return {u.id: u for u in (await db.execute(select(User))).scalars().all()}


def _mine(query, model, cashier_id: Optional[int]):
    return query if cashier_id is None else query.where(model.cashier_user_id == cashier_id)


async def list_transactions(
    db: AsyncSession, start: date, end: date, kind: str = "all", search: str = "", cashier_id: Optional[int] = None
) -> list[dict]:
    """Shop sales and GCash/Maya transactions in one list, newest first. cashier_id limits it to one cashier's."""
    lo, hi = day_range(start, end)
    users = await _users_by_id(db)
    needle = search.strip().upper()
    rows: list[dict] = []

    if kind in ("all", "shop"):
        sales = (await db.execute(_mine(select(PosSale).where(PosSale.created_at >= lo, PosSale.created_at < hi), PosSale, cashier_id))).scalars().all()
        lines_by_sale: dict[int, list[PosSaleLine]] = defaultdict(list)
        if sales:
            all_lines = (
                await db.execute(select(PosSaleLine).where(PosSaleLine.sale_id.in_([s.id for s in sales])).order_by(PosSaleLine.id))
            ).scalars().all()
            for line in all_lines:
                lines_by_sale[line.sale_id].append(line)
        for sale in sales:
            details = describe_lines(lines_by_sale[sale.id])
            if sale.is_job_order:
                details += f" · job order, down payment ₱{sale.checkout_paid_cents / 100:,.2f}"
            if sale.payment_method == "wallet":
                details += f" · paid via {sale.pay_wallet_name} ref {sale.payment_reference}"
            if sale.personal:
                details += f" · {PERSONAL_LABELS[sale.personal]}"
            haystack = " ".join(filter(None, [sale.sale_no, details, sale.customer_name, sale.customer_phone, sale.bir_invoice_no]))
            if needle and needle not in haystack.upper():
                continue
            rows.append(
                {
                    "type": "sale",
                    "id": sale.id,
                    "no": sale.sale_no,
                    "at": sale.created_at,
                    "label": ("Job order" if sale.is_job_order else "Shop sale")
                    + (f" · {sale.pay_wallet_name}" if sale.payment_method == "wallet" else ""),
                    "details": details,
                    "customer": sale.customer_name,
                    "bir_invoice_no": sale.bir_invoice_no,
                    "amount_cents": sale.total_cents,
                    "fee_cents": None,
                    "cashier": display_name(users.get(sale.cashier_user_id)),
                    "status": sale.status,
                    "void_reason": sale.void_reason,
                }
            )

    if kind in ("all", "shop"):
        payments = (
            await db.execute(
                _mine(select(PosSalePayment).where(PosSalePayment.created_at >= lo, PosSalePayment.created_at < hi), PosSalePayment, cashier_id)
            )
        ).scalars().all()
        sale_info = {}
        if payments:
            found = await db.execute(select(PosSale).where(PosSale.id.in_({p.sale_id for p in payments})))
            sale_info = {sale.id: sale for sale in found.scalars().all()}
        for payment in payments:
            sale = sale_info.get(payment.sale_id)
            details = f"Balance payment for {sale.sale_no if sale else '?'}"
            details += " (paid in full)" if payment.balance_after_cents == 0 else f", ₱{payment.balance_after_cents / 100:,.2f} still due"
            if payment.payment_method == "wallet":
                details += f" · paid via {payment.pay_wallet_name} ref {payment.payment_reference}"
            customer = sale.customer_name if sale else None
            haystack = " ".join(filter(None, [payment.payment_no, details, customer, payment.payment_reference]))
            if needle and needle not in haystack.upper():
                continue
            rows.append(
                {
                    "type": "payment",
                    "id": payment.id,
                    "no": payment.payment_no,
                    "at": payment.created_at,
                    "label": "Job order payment",
                    "details": details,
                    "customer": customer,
                    "bir_invoice_no": None,
                    "amount_cents": payment.amount_cents,
                    "fee_cents": None,
                    "cashier": display_name(users.get(payment.cashier_user_id)),
                    "status": payment.status,
                    "void_reason": payment.void_reason,
                }
            )

    if kind in ("all", "wallet"):
        txns = (
            await db.execute(
                _mine(select(PosWalletTxn).where(PosWalletTxn.created_at >= lo, PosWalletTxn.created_at < hi), PosWalletTxn, cashier_id)
            )
        ).scalars().all()
        for txn in txns:
            label = f"{txn.wallet_name} {'cash-in' if txn.kind == 'cash_in' else 'cash-out'}"
            details = f"{txn.customer_mobile} ref {txn.reference}"
            if txn.personal:
                details += f" · {PERSONAL_LABELS[txn.personal]}"
            elif txn.kind == "cash_out":
                details += CASH_OUT_FEE_LABELS.get(txn.fee_mode, " (fee deducted)")
            if txn.sale_id:
                details += f" · sent with sale S-{txn.sale_id:06d}"
            haystack = " ".join(filter(None, [txn.txn_no, label, details, txn.customer_name]))
            if needle and needle not in haystack.upper():
                continue
            rows.append(
                {
                    "type": "wallet",
                    "id": txn.id,
                    "no": txn.txn_no,
                    "at": txn.created_at,
                    "label": label,
                    "details": details,
                    "customer": txn.customer_name,
                    "bir_invoice_no": None,
                    "amount_cents": txn.amount_cents,
                    "fee_cents": txn.fee_cents,
                    "cashier": display_name(users.get(txn.cashier_user_id)),
                    "status": txn.status,
                    "void_reason": txn.void_reason,
                }
            )

    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows


@dataclass
class DaySummary:
    sale_count: int = 0
    service_totals: dict = field(default_factory=lambda: defaultdict(int))  # name -> cents
    service_sales_cents: int = 0
    load_count: int = 0
    load_sent_cents: int = 0
    load_cost_cents: int = 0  # what GCash/Maya deducted (after their discount)
    load_charged_cents: int = 0
    load_by_network: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))  # name -> [count, sent]
    cash_in_count: int = 0
    cash_in_cents: int = 0
    cash_in_fees_cents: int = 0
    cash_out_count: int = 0
    cash_out_cents: int = 0
    cash_out_fees_cents: int = 0
    drawer_cents: int = 0
    shop_cash_cents: int = 0  # cash from shop sales, down payments and balances
    ewallet_drawer_cents: int = 0  # GCash/Maya cash-in collected minus cash-out paid out
    # wallet name -> {"loads", "cash_ins", "cash_outs", "payments"} (signed, as they move the wallet)
    wallet_parts: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    sales_paid_by_wallet: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))  # name -> [count, cents]
    wallet_deltas: dict = field(default_factory=lambda: defaultdict(int))  # wallet name -> cents
    by_cashier: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))  # name -> [count, drawer cents]
    voids: list = field(default_factory=list)
    job_count: int = 0  # new job orders
    job_total_cents: int = 0
    job_down_payments_cents: int = 0
    balance_payment_count: int = 0
    balance_payments_cents: int = 0
    unpaid_job_count: int = 0  # all open job orders right now, not just these dates
    unpaid_balance_cents: int = 0
    # Admin's personal transactions paid from shop funds: nothing received, not income.
    personal_shop_count: int = 0
    personal_shop_cents: int = 0  # services at their price, loads at what the wallet deducted, cash-ins sent
    # Bills (BPS bill_records), added by add_bills for the Summary page; End of day counts them itself.
    bill_count: int = 0
    bill_amt_cents: int = 0
    bill_late_cents: int = 0
    bill_charge_cents: int = 0  # service charges: the shop's income from bills
    bill_total_cents: int = 0
    bills_by_method: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))  # method -> [count, total]
    bills_by_biller: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))  # biller -> [count, total]
    bill_cash_cents: int = 0  # into the drawer (cash collected to the whole peso)
    bills_settled: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))  # channel -> [count, to biller]

    @property
    def load_income_cents(self) -> int:
        return self.load_charged_cents - self.load_cost_cents

    @property
    def income_cents(self) -> int:
        """What the shop earned: service sales + load fees/rounding + GCash/Maya fees."""
        return self.service_sales_cents + self.load_income_cents + self.cash_in_fees_cents + self.cash_out_fees_cents

    @property
    def total_income_cents(self) -> int:
        """Shop income plus the service charges on bills."""
        return self.income_cents + self.bill_charge_cents

    @property
    def bills_settled_cents(self) -> int:
        return sum(row[1] for row in self.bills_settled.values())


async def day_summary(
    db: AsyncSession, start: date, end: date, window: Optional[tuple[datetime, datetime]] = None
) -> DaySummary:
    """window (lo, hi) narrows it to part of a day, e.g. one cashier's shift."""
    lo, hi = window or day_range(start, end)
    users = await _users_by_id(db)
    out = DaySummary()

    def who(user_id: int) -> str:
        return display_name(users.get(user_id))

    sales = (await db.execute(select(PosSale).where(PosSale.created_at >= lo, PosSale.created_at < hi))).scalars().all()
    completed = {s.id: s for s in sales if s.status == "completed"}
    for sale in sales:
        if sale.status == "voided":
            out.voids.append((sale.sale_no, sale.total_cents, sale.void_reason, who(sale.voided_by_user_id)))
    if completed:
        lines = (await db.execute(select(PosSaleLine).where(PosSaleLine.sale_id.in_(list(completed))))).scalars().all()
        for line in lines:
            if completed[line.sale_id].payment_method == "shop":
                # Paid from shop funds: loads still leave the wallet, but nothing is earned.
                out.personal_shop_cents += line.cost_cents if line.kind == "load" else line.line_total_cents
                if line.kind == "load":
                    out.wallet_deltas[line.wallet_name] -= line.cost_cents
                    out.wallet_parts[line.wallet_name]["loads"] -= line.cost_cents
                continue
            if line.kind == "load":
                out.load_count += 1
                out.load_sent_cents += line.load_cents
                out.load_cost_cents += line.cost_cents
                out.load_charged_cents += line.line_total_cents
                out.load_by_network[line.network_name][0] += 1
                out.load_by_network[line.network_name][1] += line.load_cents
                out.wallet_deltas[line.wallet_name] -= line.cost_cents
                out.wallet_parts[line.wallet_name]["loads"] -= line.cost_cents
            else:
                out.service_totals[line.service_name] += line.line_total_cents
                out.service_sales_cents += line.line_total_cents
    # Money is counted on the day it's received: what was paid at checkout (the total, or a
    # job order's down payment) here, and later balance payments on their own dates below.
    def received(user_id: int, cents: int, method: str, wallet_name: Optional[str]) -> None:
        if method == "shop":
            return  # personal, from shop funds: nothing received
        if method == "wallet":
            # Paid into the shop's GCash/Maya: raises that wallet, not the drawer.
            out.wallet_deltas[wallet_name] += cents
            out.wallet_parts[wallet_name]["payments"] += cents
            out.sales_paid_by_wallet[wallet_name][0] += 1
            out.sales_paid_by_wallet[wallet_name][1] += cents
        else:
            cents = cash_due_cents(cents)  # what went into the drawer: cash is collected to the whole peso
            out.drawer_cents += cents
            out.shop_cash_cents += cents
            out.by_cashier[who(user_id)][1] += cents

    for sale in completed.values():
        if sale.payment_method == "shop":
            out.personal_shop_count += 1
        out.sale_count += 1
        out.by_cashier[who(sale.cashier_user_id)][0] += 1
        received(sale.cashier_user_id, sale.checkout_paid_cents, sale.payment_method, sale.pay_wallet_name)
        if sale.is_job_order:
            out.job_count += 1
            out.job_total_cents += sale.total_cents
            out.job_down_payments_cents += sale.checkout_paid_cents

    payments = (
        await db.execute(select(PosSalePayment).where(PosSalePayment.created_at >= lo, PosSalePayment.created_at < hi))
    ).scalars().all()
    for payment in payments:
        if payment.status == "voided":
            out.voids.append((payment.payment_no, payment.amount_cents, payment.void_reason, who(payment.voided_by_user_id)))
            continue
        out.balance_payment_count += 1
        out.balance_payments_cents += payment.amount_cents
        out.by_cashier[who(payment.cashier_user_id)][0] += 1
        received(payment.cashier_user_id, payment.amount_cents, payment.payment_method, payment.pay_wallet_name)

    open_jobs = (
        await db.execute(
            select(PosSale).where(PosSale.is_job_order, PosSale.status == "completed", PosSale.job_status != "completed")
        )
    ).scalars().all()
    out.unpaid_job_count = len(open_jobs)
    out.unpaid_balance_cents = sum(sale.balance_cents for sale in open_jobs)

    txns = (await db.execute(select(PosWalletTxn).where(PosWalletTxn.created_at >= lo, PosWalletTxn.created_at < hi))).scalars().all()
    for txn in txns:
        if txn.status == "voided":
            out.voids.append((txn.txn_no, txn.amount_cents, txn.void_reason, who(txn.voided_by_user_id)))
            continue
        drawer = txn.collect_cents - txn.give_cents
        if txn.personal == "shop":
            out.personal_shop_count += 1
            out.personal_shop_cents += txn.amount_cents
        if txn.kind == "cash_in":
            out.cash_in_count += 1
            out.cash_in_cents += txn.amount_cents
            out.cash_in_fees_cents += txn.fee_cents
            out.wallet_deltas[txn.wallet_name] -= txn.amount_cents
            out.wallet_parts[txn.wallet_name]["cash_ins"] -= txn.amount_cents
        else:
            out.cash_out_count += 1
            out.cash_out_cents += txn.amount_cents
            out.cash_out_fees_cents += txn.fee_cents
            out.wallet_deltas[txn.wallet_name] += txn.amount_cents
            out.wallet_parts[txn.wallet_name]["cash_outs"] += txn.amount_cents
        out.drawer_cents += drawer
        out.ewallet_drawer_cents += drawer
        out.by_cashier[who(txn.cashier_user_id)][0] += 1
        out.by_cashier[who(txn.cashier_user_id)][1] += drawer
    return out


def _bill_cents(value) -> int:
    return int(round(float(value or 0) * 100))


async def add_bills(db: AsyncSession, out: DaySummary, start: date, end: date, wallets: list) -> DaySummary:
    """Add bills to a summary the way End of day counts them: collected by transaction date, paid to
    the biller by settled_at; GCash/Maya bills go to the first account of that provider."""
    lo, hi = day_range(start, end)
    users = await _users_by_id(db)
    first_of_provider = {}
    for wallet in wallets:
        first_of_provider.setdefault(wallet.provider, wallet.name)

    bills = (
        await db.execute(select(BillRecord).where(BillRecord.txn_date >= start, BillRecord.txn_date <= end))
    ).scalars().all()
    for bill in bills:
        total = _bill_cents(bill.total)
        method = str(bill.payment_method or "").strip().upper() or "CASH"  # blank was cash (older entry form)
        out.bill_count += 1
        out.bill_amt_cents += _bill_cents(bill.bill_amt)
        out.bill_late_cents += _bill_cents(bill.late_charge)
        out.bill_charge_cents += _bill_cents(bill.charge)
        out.bill_total_cents += total
        out.bills_by_biller[bill.biller or "?"][0] += 1
        out.bills_by_biller[bill.biller or "?"][1] += total
        cashier = display_name(users.get(bill.created_by_user_id))
        out.by_cashier[cashier][0] += 1
        if bill.personal == "shop":
            # Paid from shop funds: nothing received (paying the biller still takes money out).
            out.personal_shop_count += 1
            out.personal_shop_cents += total
            out.bills_by_method["SHOP FUNDS"][0] += 1
            out.bills_by_method["SHOP FUNDS"][1] += total
            continue
        out.bills_by_method[method][0] += 1
        out.bills_by_method[method][1] += total
        if method == "CASH":
            cash = cash_due_cents(total)
            out.bill_cash_cents += cash
            out.drawer_cents += cash
            out.by_cashier[cashier][1] += cash
        elif method in first_of_provider:
            out.wallet_deltas[first_of_provider[method]] += total

    settled = (
        await db.execute(select(BillRecord).where(BillRecord.settled_at >= lo, BillRecord.settled_at < hi))
    ).scalars().all()
    for bill in settled:
        # The biller gets the bill amount and late charge; the service charge stays with the shop.
        to_biller = _bill_cents(bill.total) - _bill_cents(bill.charge)
        channel = str(bill.payment_channel or "").strip().upper() or "NOT SET"
        out.bills_settled[channel][0] += 1
        out.bills_settled[channel][1] += to_biller
        if channel == "CASH":
            out.drawer_cents -= to_biller
        elif channel in first_of_provider:
            out.wallet_deltas[first_of_provider[channel]] -= to_biller
    return out
