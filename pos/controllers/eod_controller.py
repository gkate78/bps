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

Shifts: when the drawer is turned over mid-day, the outgoing cashier counts it (a handover) and the
reliever starts from that count. Each shift is checked over its own time window; because each shift
starts from the previous count, the shifts' over/short add up to the day's.
"""
import json
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
from pos.models import PosCashMovement, PosDayClose, PosDayWallet, PosDrawerHandover, PosParkedTxn, PosWallet
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
    parked: tuple = (0, 0)  # (count, cents) parked by the end of the day and still not paid
    personal_shop: tuple = (0, 0)  # (count, cents) admin's personal transactions paid from shop funds
    movements: list = field(default_factory=list)
    shifts: list = field(default_factory=list)  # ShiftReport, only when the drawer was handed over
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

    @property
    def current_shift(self) -> Optional["ShiftReport"]:
        return self.shifts[-1] if self.shifts else None


@dataclass
class ShiftWallet:
    wallet: PosWallet
    opening_cents: int
    change_cents: int
    counted_cents: Optional[int]

    @property
    def expected_cents(self) -> int:
        return self.opening_cents + self.change_cents

    @property
    def difference_cents(self) -> Optional[int]:
        return None if self.counted_cents is None else self.counted_cents - self.expected_cents


@dataclass
class ShiftReport:
    number: int
    started_at: datetime
    ended_at: Optional[datetime]  # None: the last shift, closed by the day's count
    closed_by: str  # who counted the drawer at the end ("" while still open)
    opening_cash_cents: int
    cash_change_cents: int
    counted_cash_cents: Optional[int]
    wallets: list = field(default_factory=list)  # ShiftWallet
    handover: Optional[PosDrawerHandover] = None
    started_from: str = ""  # who counted the cash this shift started with

    @property
    def expected_cash_cents(self) -> int:
        return self.opening_cash_cents + self.cash_change_cents

    @property
    def difference_cents(self) -> Optional[int]:
        return None if self.counted_cash_cents is None else self.counted_cash_cents - self.expected_cash_cents


def _wallet_counts(handover: PosDrawerHandover) -> dict[int, int]:
    try:
        return {int(k): int(v) for k, v in json.loads(handover.wallet_counts or "{}").items()}
    except (ValueError, TypeError, AttributeError):
        return {}


async def _handovers(db: AsyncSession, day: date) -> list[PosDrawerHandover]:
    return list(
        (
            await db.execute(
                select(PosDrawerHandover)
                .where(PosDrawerHandover.day == day, PosDrawerHandover.status == "completed")
                .order_by(PosDrawerHandover.handed_at)
            )
        ).scalars().all()
    )


async def _shifts(db: AsyncSession, report: "EodReport", wallets: list) -> list[ShiftReport]:
    handovers = await _handovers(db, report.day)
    if not handovers:
        return []
    names = {}
    for h in handovers:
        if h.user_id not in names:
            names[h.user_id] = display_name(await db.get(User, h.user_id))
    day_lo, day_hi = day_range(report.day, report.day)
    bounds = [day_lo] + [h.handed_at for h in handovers] + [day_hi]
    day_wallets = {w.wallet.id: w for w in report.wallets}
    shifts: list[ShiftReport] = []
    for i in range(len(handovers) + 1):
        changes = await _changes(db, report.day, bounds[i], bounds[i + 1], wallets)
        last = i == len(handovers)
        handover = None if last else handovers[i]
        previous = shifts[-1] if shifts else None
        previous_counts = _wallet_counts(handovers[i - 1]) if i else {}
        shift = ShiftReport(
            number=i + 1,
            started_at=bounds[i],
            ended_at=None if last else handover.handed_at,
            closed_by=(report.closed_by if report.counted_cash_cents is not None else "") if last else names[handover.user_id],
            opening_cash_cents=report.opening_cash_cents if i == 0 else handovers[i - 1].counted_cash_cents,
            cash_change_cents=changes.cash_change_cents,
            counted_cash_cents=report.counted_cash_cents if last else handover.counted_cash_cents,
            handover=handover,
            started_from=names[handovers[i - 1].user_id] if i else "",
        )
        counts = {} if last else _wallet_counts(handover)
        for wallet in wallets:
            if i == 0:
                opening = day_wallets[wallet.id].opening_cents
            elif wallet.id in previous_counts:
                opening = previous_counts[wallet.id]
            else:  # not checked at the handover: carry on from what was expected
                opening = next(w.expected_cents for w in previous.wallets if w.wallet.id == wallet.id)
            counted = day_wallets[wallet.id].counted_cents if last else counts.get(wallet.id)
            shift.wallets.append(ShiftWallet(wallet, opening, changes.wallet_change_cents(wallet.id), counted))
        shifts.append(shift)
    return shifts


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


@dataclass
class _Changes:
    """What moved the drawer and each wallet in a time window (a whole day or one shift)."""

    cash_lines: list  # (label, cents)
    wallet_lines: dict  # wallet_id -> [(label, cents)]
    movements: list
    settled_by_channel: dict
    bills_in: list
    shop: object

    @property
    def cash_change_cents(self) -> int:
        return sum(cents for _, cents in self.cash_lines)

    def wallet_change_cents(self, wallet_id: int) -> int:
        return sum(cents for _, cents in self.wallet_lines.get(wallet_id, []))


async def _changes(db: AsyncSession, day: date, lo: datetime, hi: datetime, wallets: list) -> _Changes:
    day_lo, day_hi = day_range(day, day)

    def in_window(at: Optional[datetime]) -> bool:
        # The first shift is open at the start and the last at the end, so nothing dated this day is lost.
        return (lo <= day_lo or (at is not None and at >= lo)) and (hi >= day_hi or (at is not None and at < hi))

    # Bills (BPS): collected by transaction date (and time, for a shift), settled by settled_at.
    bills_in = [
        b for b in (await db.execute(select(BillRecord).where(BillRecord.txn_date == day))).scalars().all()
        if in_window(b.txn_datetime)
    ]
    # Personal bills paid from shop funds bring nothing in; paying them to the biller still takes money out.
    received_bills = [b for b in bills_in if b.personal != "shop"]
    bills_cash = sum(bill_cents(b.total) for b in received_bills if _method(b.payment_method) in ("", "CASH"))
    bills_by_method = defaultdict(int)
    for bill in received_bills:
        bills_by_method[_method(bill.payment_method)] += bill_cents(bill.total)

    settled = (
        await db.execute(select(BillRecord).where(BillRecord.settled_at >= lo, BillRecord.settled_at < hi))
    ).scalars().all()
    settled_by_channel = defaultdict(lambda: [0, 0])
    for bill in settled:
        # The biller gets the bill amount and late charge; the service charge stays with the shop.
        settled_by_channel[_method(bill.payment_channel) or "NOT SET"][0] += 1
        settled_by_channel[_method(bill.payment_channel) or "NOT SET"][1] += bill_cents(bill.total) - bill_cents(bill.charge)

    shop = await day_summary(db, day, day, window=(lo, hi))
    movements = [
        m
        for m in (
            await db.execute(
                select(PosCashMovement)
                .where(PosCashMovement.day == day, PosCashMovement.status == "completed")
                .order_by(PosCashMovement.created_at)
            )
        ).scalars().all()
        if in_window(m.created_at)
    ]

    cash_lines = [
        ("Bills paid in cash", bills_cash),
        ("Shop sales and job order payments in cash", shop.shop_cash_cents),
        ("GCash/Maya cash-in collected minus cash-out paid out", shop.ewallet_drawer_cents),
        ("Bills paid to billers in cash", -settled_by_channel.get("CASH", [0, 0])[1]),
    ]
    for kind, label in MOVEMENT_KINDS.items():
        total = sum(m.drawer_delta_cents for m in movements if m.kind == kind)
        if total:
            cash_lines.append((label, total))

    # Wallets: bills are matched to the first active account of that provider (GCASH, MAYA).
    first_of_provider = {}
    for wallet in wallets:
        first_of_provider.setdefault(wallet.provider, wallet.id)
    wallet_lines = {}
    for wallet in wallets:
        parts = shop.wallet_parts.get(wallet.name, {})
        is_bill_wallet = first_of_provider.get(wallet.provider) == wallet.id
        lines = [
            ("Bills paid by customers into it", bills_by_method.get(wallet.provider, 0) if is_bill_wallet else 0),
            ("Shop sales and job order payments into it", parts.get("payments", 0)),
            ("Cash-outs received", parts.get("cash_outs", 0)),
            ("Cash-ins sent", parts.get("cash_ins", 0)),
            ("Loads sent", parts.get("loads", 0)),
            ("Bills paid to billers from it", -settled_by_channel.get(wallet.provider, [0, 0])[1] if is_bill_wallet else 0),
        ]
        moved = sum(-m.drawer_delta_cents for m in movements if m.wallet_id == wallet.id)
        if moved:
            lines.append(("Moved from/to the cash drawer", moved))
        wallet_lines[wallet.id] = lines
    return _Changes(cash_lines, wallet_lines, movements, settled_by_channel, bills_in, shop)


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

    wallets = await list_wallets(db, active_only=True)
    changes = await _changes(db, day, lo, hi, wallets)
    bills_in = changes.bills_in
    personal_bills = [b for b in bills_in if b.personal == "shop"]
    unsettled = [b for b in bills_in if not b.settled_at and not (b.payment_reference or "").strip()]
    report.unsettled_bills = (len(unsettled), sum(bill_cents(b.total) - bill_cents(b.charge) for b in unsettled))
    parked = (await db.execute(select(PosParkedTxn).where(PosParkedTxn.parked_at < hi))).scalars().all()
    report.parked = (len(parked), sum(p.total_cents for p in parked))
    report.personal_shop = (
        len(personal_bills) + changes.shop.personal_shop_count,
        sum(bill_cents(b.total) for b in personal_bills) + changes.shop.personal_shop_cents,
    )
    report.movements = changes.movements
    report.cash_lines = changes.cash_lines

    for wallet in wallets:
        saved = saved_wallets.get(wallet.id)
        if saved:
            opening = saved.opening_cents
        else:
            opening = await _previous_wallet_count(db, day, wallet.id) or 0
        w = WalletReport(wallet=wallet, opening_cents=opening, counted_cents=saved.counted_cents if saved else None)
        w.lines = changes.wallet_lines[wallet.id]
        report.wallets.append(w)

    tracked = {"CASH"} | {w.provider for w in wallets}
    report.other_settlements = {ch: v for ch, v in sorted(changes.settled_by_channel.items()) if ch not in tracked}
    report.shifts = await _shifts(db, report, wallets)
    return report


async def save_close(db: AsyncSession, day: date, form: dict, user: User, counts_only: bool = False) -> EodReport:
    """
    Save the starting cash, the counts and notes for a day. Saving again updates it (audit-logged).
    counts_only (encoders): only the counted cash, the GCash/Maya balances in the apps and notes change;
    the starting cash and opening balances stay as the admin set them.
    """
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
    if not counts_only:
        close.opening_cash_cents = opening
    close.counted_cash_cents = counted
    close.notes = clean_text(form.get("notes"), 500)
    db.add(close)
    for wallet_id, (w_opening, w_counted) in wallet_inputs.items():
        row = (
            await db.execute(select(PosDayWallet).where(PosDayWallet.day == day, PosDayWallet.wallet_id == wallet_id))
        ).scalar_one_or_none()
        row = row or PosDayWallet(day=day, wallet_id=wallet_id)
        if not counts_only:
            row.opening_cents = w_opening
        row.counted_cents = w_counted
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


async def add_handover(db: AsyncSession, day: date, form: dict, user: User) -> PosDrawerHandover:
    """The outgoing cashier closes their shift with a count; the reliever starts from it."""
    if day != date.today():
        raise PosError("A handover can only be recorded for today")
    try:
        counted = to_cents_optional(form.get("counted_cash"), field="Counted cash")
        wallet_counts = {}
        for item in form.get("wallets") or []:
            value = to_cents_optional(item.get("counted"), field="Balance in the app")
            if value is not None:
                wallet_counts[int(item["wallet_id"])] = value
    except (MoneyError, KeyError, ValueError, TypeError) as exc:
        raise PosError(str(exc)) from exc
    if counted is None:
        raise PosError("Count the cash in the drawer before handing it over")
    report = await eod_report(db, day)
    if report.counted_cash_cents is not None:
        raise PosError("The day's closing count is already saved. Ask an admin to clear it before handing over.")
    # Every transaction of the shift must be encoded before the turnover.
    parked_count = len((await db.execute(select(PosParkedTxn.id))).all())
    if parked_count:
        raise PosError(
            f"Finish or discard the {parked_count} parked transaction{'' if parked_count == 1 else 's'} in the register before handing over"
        )
    current = report.current_shift
    handover = PosDrawerHandover(
        day=day,
        user_id=user.id,
        counted_cash_cents=counted,
        expected_cash_cents=current.expected_cash_cents if current else report.expected_cash_cents,
        wallet_counts=json.dumps({str(k): v for k, v in wallet_counts.items()}),
        notes=clean_text(form.get("notes"), 500),
    )
    if current and current.started_at >= handover.handed_at:
        raise PosError("The last handover is newer than now. Check the computer's clock.")
    db.add(handover)
    await db.flush()
    add_audit(
        db, "drawer_handover", handover.id, "create", user.id,
        {"day": day.isoformat(), "expected": handover.expected_cash_cents, "counted": counted},
    )
    await db.commit()
    return handover


async def remove_handover(db: AsyncSession, handover_id: int, user: User) -> None:
    """Undo a handover made by mistake: its two shifts become one again."""
    handover = await db.get(PosDrawerHandover, handover_id)
    if not handover or handover.status != "completed":
        raise PosError("Not found")
    handover.status = "voided"
    handover.voided_by_user_id = user.id
    db.add(handover)
    add_audit(db, "drawer_handover", handover.id, "void", user.id, {"counted": handover.counted_cash_cents})
    await db.commit()
