"""
End of day for the shop's one cash drawer and its GCash/Maya accounts, bills and shop together.

Cash drawer:  starting cash
              + bills paid in cash (BPS, by transaction date)
              + shop cash (sales, down payments, job order balances)
              + GCash/Maya cash-in collected - cash-out paid out
              - bills paid to billers in cash (BPS, settled that day, channel CASH)
              -/+ cash taken out / added, and moves to/from a GCash/Maya account
              = expected cash, compared with the count.
Each wallet:  opening balance + bills paid by customers into it + shop payments into it + cash-outs
              - cash-ins - loads - bills paid to billers from it -/+ moves = expected balance.
Bills settled through Bayad, banks, etc. don't touch the drawer or these wallets; they're listed for reference.
Bill amounts are stored as decimals in BPS and converted to centavos here.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import BillRecord
from pos.auth_adapter import User, display_name
from pos.controllers.sale_controller import PosError, clean_text, day_range, day_summary
from pos.controllers.settings_controller import add_audit, get_settings, list_wallets
from pos.models import PosCashMovement, PosDayClose, PosDayWallet, PosWallet
from pos.money import MoneyError, to_cents, to_cents_optional

MOVEMENT_KINDS = {
    "take_out": "Cash taken out",
    "add": "Cash added",
    "to_wallet": "Moved to GCash/Maya",
    "from_wallet": "Moved from GCash/Maya",
}


def bill_cents(value) -> int:
    return int(round(float(value or 0) * 100))


def _method(value) -> str:
    return str(value or "").strip().upper()


@dataclass
class WalletReport:
    wallet: PosWallet
    opening_cents: int
    counted_cents: Optional[int]
    lines: list = field(default_factory=list)  # (label, cents)

    @property
    def change_cents(self) -> int:
        return sum(cents for _, cents in self.lines)

    @property
    def expected_cents(self) -> int:
        return self.opening_cents + self.change_cents

    @property
    def difference_cents(self) -> Optional[int]:
        return None if self.counted_cents is None else self.counted_cents - self.expected_cents


@dataclass
class EodReport:
    day: date
    opening_cash_cents: int
    counted_cash_cents: Optional[int]
    cash_lines: list = field(default_factory=list)  # (label, cents)
    wallets: list = field(default_factory=list)  # WalletReport
    other_settlements: dict = field(default_factory=dict)  # channel -> [count, cents]
    unsettled_bills: tuple = (0, 0)  # (count, cents) collected that day, not yet paid to billers
    movements: list = field(default_factory=list)
    close: Optional[PosDayClose] = None
    closed_by: str = ""
    notes: str = ""

    @property
    def change_cents(self) -> int:
        return sum(cents for _, cents in self.cash_lines)

    @property
    def expected_cash_cents(self) -> int:
        return self.opening_cash_cents + self.change_cents

    @property
    def difference_cents(self) -> Optional[int]:
        return None if self.counted_cash_cents is None else self.counted_cash_cents - self.expected_cash_cents


async def _previous_wallet_count(db: AsyncSession, day: date, wallet_id: int) -> Optional[int]:
    row = (
        await db.execute(
            select(PosDayWallet)
            .where(PosDayWallet.wallet_id == wallet_id, PosDayWallet.day < day, PosDayWallet.counted_cents.is_not(None))
            .order_by(PosDayWallet.day.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row.counted_cents if row else None


async def eod_report(db: AsyncSession, day: date) -> EodReport:
    lo, hi = day_range(day, day)
    close = (await db.execute(select(PosDayClose).where(PosDayClose.day == day))).scalar_one_or_none()
    saved_wallets = {
        w.wallet_id: w for w in (await db.execute(select(PosDayWallet).where(PosDayWallet.day == day))).scalars().all()
    }
    settings = await get_settings(db)
    report = EodReport(
        day=day,
        opening_cash_cents=close.opening_cash_cents if close else settings.default_starting_cash_cents,
        counted_cash_cents=close.counted_cash_cents if close else None,
        close=close,
        notes=(close.notes or "") if close else "",
    )
    if close and close.closed_by_user_id:
        user = (await db.execute(select(User).where(User.id == close.closed_by_user_id))).scalar_one_or_none()
        report.closed_by = display_name(user)

    # Bills (BPS): collected by transaction date, settled by settled_at.
    bills_in = (await db.execute(select(BillRecord).where(BillRecord.txn_date == day))).scalars().all()
    bills_cash = sum(bill_cents(b.total) for b in bills_in if _method(b.payment_method) in ("", "CASH"))
    bills_by_method = defaultdict(int)
    for bill in bills_in:
        bills_by_method[_method(bill.payment_method)] += bill_cents(bill.total)
    unsettled = [b for b in bills_in if not b.settled_at and not (b.payment_reference or "").strip()]
    report.unsettled_bills = (len(unsettled), sum(bill_cents(b.total) - bill_cents(b.charge) for b in unsettled))

    settled = (
        await db.execute(select(BillRecord).where(BillRecord.settled_at >= lo, BillRecord.settled_at < hi))
    ).scalars().all()
    settled_by_channel = defaultdict(lambda: [0, 0])
    for bill in settled:
        # The biller gets the bill amount and late charge; the service charge stays with the shop.
        settled_by_channel[_method(bill.payment_channel) or "NOT SET"][0] += 1
        settled_by_channel[_method(bill.payment_channel) or "NOT SET"][1] += bill_cents(bill.total) - bill_cents(bill.charge)

    shop = await day_summary(db, day, day)
    movements = (
        await db.execute(
            select(PosCashMovement)
            .where(PosCashMovement.day == day, PosCashMovement.status == "completed")
            .order_by(PosCashMovement.created_at)
        )
    ).scalars().all()
    report.movements = list(movements)

    report.cash_lines = [
        ("Bills paid in cash", bills_cash),
        ("Shop sales and job order payments in cash", shop.shop_cash_cents),
        ("GCash/Maya cash-in collected minus cash-out paid out", shop.ewallet_drawer_cents),
        ("Bills paid to billers in cash", -settled_by_channel.get("CASH", [0, 0])[1]),
    ]
    for kind, label in MOVEMENT_KINDS.items():
        total = sum(m.drawer_delta_cents for m in movements if m.kind == kind)
        if total:
            report.cash_lines.append((label, total))

    # Wallets: bills are matched to the first active account of that provider (GCASH, MAYA).
    wallets = await list_wallets(db, active_only=True)
    first_of_provider = {}
    for wallet in wallets:
        first_of_provider.setdefault(wallet.provider, wallet.id)
    for wallet in wallets:
        saved = saved_wallets.get(wallet.id)
        if saved:
            opening = saved.opening_cents
        else:
            opening = await _previous_wallet_count(db, day, wallet.id) or 0
        w = WalletReport(wallet=wallet, opening_cents=opening, counted_cents=saved.counted_cents if saved else None)
        parts = shop.wallet_parts.get(wallet.name, {})
        is_bill_wallet = first_of_provider.get(wallet.provider) == wallet.id
        w.lines = [
            ("Bills paid by customers into it", bills_by_method.get(wallet.provider, 0) if is_bill_wallet else 0),
            ("Shop sales and job order payments into it", parts.get("payments", 0)),
            ("Cash-outs received", parts.get("cash_outs", 0)),
            ("Cash-ins sent", parts.get("cash_ins", 0)),
            ("Loads sent", parts.get("loads", 0)),
            ("Bills paid to billers from it", -settled_by_channel.get(wallet.provider, [0, 0])[1] if is_bill_wallet else 0),
        ]
        moved = sum(-m.drawer_delta_cents for m in movements if m.wallet_id == wallet.id)
        if moved:
            w.lines.append(("Moved from/to the cash drawer", moved))
        report.wallets.append(w)

    tracked = {"CASH"} | {w.provider for w in wallets}
    report.other_settlements = {ch: v for ch, v in sorted(settled_by_channel.items()) if ch not in tracked}
    return report


async def save_close(db: AsyncSession, day: date, form: dict, user: User) -> EodReport:
    """Save the starting cash, the counts and notes for a day. Saving again updates it (audit-logged)."""
    try:
        opening = to_cents(form.get("opening_cash") or "0", field="Starting cash")
        counted = to_cents_optional(form.get("counted_cash"), field="Counted cash")
        wallet_inputs = {}
        for item in form.get("wallets") or []:
            wallet_inputs[int(item["wallet_id"])] = (
                to_cents(item.get("opening") or "0", field="Opening balance"),
                to_cents_optional(item.get("counted"), field="Counted balance"),
            )
    except (MoneyError, KeyError, ValueError, TypeError) as exc:
        raise PosError(str(exc)) from exc

    close = (await db.execute(select(PosDayClose).where(PosDayClose.day == day))).scalar_one_or_none()
    close = close or PosDayClose(day=day)
    close.opening_cash_cents = opening
    close.counted_cash_cents = counted
    close.notes = clean_text(form.get("notes"), 500)
    db.add(close)
    for wallet_id, (w_opening, w_counted) in wallet_inputs.items():
        row = (
            await db.execute(select(PosDayWallet).where(PosDayWallet.day == day, PosDayWallet.wallet_id == wallet_id))
        ).scalar_one_or_none()
        row = row or PosDayWallet(day=day, wallet_id=wallet_id)
        row.opening_cents, row.counted_cents = w_opening, w_counted
        db.add(row)
    await db.flush()

    report = await eod_report(db, day)
    close.expected_cash_cents = report.expected_cash_cents
    close.closed_by_user_id = user.id
    close.closed_at = datetime.now()
    for w in report.wallets:
        row = (
            await db.execute(select(PosDayWallet).where(PosDayWallet.day == day, PosDayWallet.wallet_id == w.wallet.id))
        ).scalar_one_or_none()
        if row:
            row.expected_cents = w.expected_cents
            db.add(row)
    add_audit(
        db, "day_close", close.id, "save", user.id,
        {"day": day.isoformat(), "expected": report.expected_cash_cents, "counted": counted},
    )
    await db.commit()
    return await eod_report(db, day)


async def add_movement(db: AsyncSession, day: date, form: dict, user: User) -> PosCashMovement:
    kind = form.get("kind")
    if kind not in MOVEMENT_KINDS:
        raise PosError("Choose what kind of cash movement this is")
    try:
        amount = to_cents(form.get("amount"), field="Amount")
    except MoneyError as exc:
        raise PosError(str(exc)) from exc
    if amount <= 0:
        raise PosError("Amount must be more than zero")
    reason = clean_text(form.get("reason"), 160)
    if not reason:
        raise PosError("Say what the cash was for (e.g. owner pickup, bond paper, bank deposit)")
    wallet = None
    if kind in ("to_wallet", "from_wallet"):
        wallet = (await db.execute(select(PosWallet).where(PosWallet.id == form.get("wallet_id")))).scalar_one_or_none()
        if not wallet:
            raise PosError("Choose the GCash/Maya account")
    movement = PosCashMovement(
        day=day,
        kind=kind,
        wallet_id=wallet.id if wallet else None,
        wallet_name=wallet.name if wallet else None,
        amount_cents=amount,
        reason=reason,
        user_id=user.id,
    )
    db.add(movement)
    await db.flush()
    add_audit(db, "cash_movement", movement.id, "create", user.id, {"kind": kind, "amount_cents": amount, "reason": reason})
    await db.commit()
    return movement


async def remove_movement(db: AsyncSession, movement_id: int, user: User) -> None:
    movement = (await db.execute(select(PosCashMovement).where(PosCashMovement.id == movement_id))).scalar_one_or_none()
    if not movement or movement.status != "completed":
        raise PosError("Not found")
    movement.status = "voided"
    movement.voided_by_user_id = user.id
    db.add(movement)
    add_audit(db, "cash_movement", movement.id, "void", user.id, {"amount_cents": movement.amount_cents})
    await db.commit()
