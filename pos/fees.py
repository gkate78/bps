"""
Fees for loading and GCash/Maya cash-in/cash-out (see docs/PLAN.md, Phase 1).

One rule for everything: a fee per full block (₱20 per ₱1,000), plus a fee on the
remainder from the brackets (₱1-₱499 -> ₱10, ₱500-₱999 -> ₱20).
Loading exception: a load of ₱50 or less is +₱5.
Promos: the promo price is rounded up to the next ₱10 before the fee is added.
"""
from dataclasses import dataclass, field
from typing import Literal

from pos.money import MoneyError

WalletKind = Literal["cash_in", "cash_out"]
CashOutFeeMode = Literal["deducted", "paid_in_cash", "included"]


class FeeError(ValueError):
    pass


@dataclass(frozen=True)
class FeeSchedule:
    block_cents: int = 100_000
    block_fee_cents: int = 2_000
    # (min_cents, max_cents, fee_cents) on the remainder after full blocks.
    brackets: tuple[tuple[int, int, int], ...] = field(
        default=((100, 49_900, 1_000), (50_000, 99_900, 2_000))
    )
    load_small_max_cents: int = 5_000
    load_small_fee_cents: int = 500
    promo_round_cents: int = 1_000


DEFAULT_SCHEDULE = FeeSchedule()


def validate_schedule(s: FeeSchedule) -> None:
    """Brackets must cover ₱1 up to one peso below the block size, with no gaps or overlaps."""
    if s.block_cents <= 0 or s.block_cents % 100:
        raise FeeError("Block size must be a whole peso amount above zero")
    if not s.brackets:
        raise FeeError("Add at least one fee bracket")
    expected_min = 100
    for low, high, fee in sorted(s.brackets):
        if low != expected_min:
            raise FeeError(f"Fee brackets must continue from ₱{expected_min // 100:,} with no gaps or overlaps")
        if high < low:
            raise FeeError("A fee bracket's 'to' amount must not be below its 'from' amount")
        if fee < 0:
            raise FeeError("Fees cannot be negative")
        expected_min = high + 100
    if expected_min != s.block_cents:
        raise FeeError(f"The last fee bracket must end at ₱{(s.block_cents - 100) // 100:,}")


def _check_amount(amount_cents: int) -> None:
    if amount_cents <= 0:
        raise MoneyError("Amount must be more than zero")
    if amount_cents % 100:
        raise MoneyError("Amount must be in whole pesos")


def ewallet_fee(amount_cents: int, s: FeeSchedule = DEFAULT_SCHEDULE) -> int:
    _check_amount(amount_cents)
    blocks, remainder = divmod(amount_cents, s.block_cents)
    fee = blocks * s.block_fee_cents
    if remainder:
        for low, high, bracket_fee in s.brackets:
            if low <= remainder <= high:
                fee += bracket_fee
                break
        else:
            raise FeeError(f"No fee bracket covers ₱{remainder / 100:,.2f}")
    return fee


def promo_price(promo_cents: int, s: FeeSchedule = DEFAULT_SCHEDULE) -> int:
    """₱59 -> ₱60, ₱69 -> ₱70, ₱70 -> ₱70."""
    step = s.promo_round_cents
    return -(-promo_cents // step) * step


@dataclass(frozen=True)
class LoadQuote:
    load_cents: int  # what is sent from the wallet
    priced_cents: int  # load amount the fee is based on (promo price rounded up)
    fee_cents: int
    total_cents: int  # what the customer pays

    @property
    def income_cents(self) -> int:
        return self.total_cents - self.load_cents


def quote_load(amount_cents: int, is_promo: bool, s: FeeSchedule = DEFAULT_SCHEDULE) -> LoadQuote:
    _check_amount(amount_cents)
    priced = promo_price(amount_cents, s) if is_promo else amount_cents
    if priced <= s.load_small_max_cents:
        fee = s.load_small_fee_cents
    else:
        fee = ewallet_fee(priced, s)
    return LoadQuote(load_cents=amount_cents, priced_cents=priced, fee_cents=fee, total_cents=priced + fee)


def quote_personal_load(amount_cents: int) -> LoadQuote:
    """Admin's own load: no fee and no promo rounding, just the load amount."""
    _check_amount(amount_cents)
    return LoadQuote(load_cents=amount_cents, priced_cents=amount_cents, fee_cents=0, total_cents=amount_cents)


def load_cost(load_cents: int, discount_bp: int) -> int:
    """What the wallet app actually deducts for a load after its discount (basis points: 300 = 3%), to the centavo."""
    return (load_cents * (10_000 - discount_bp) + 5_000) // 10_000


@dataclass(frozen=True)
class WalletQuote:
    kind: WalletKind
    fee_mode: str  # added | deducted | paid_in_cash | included
    amount_cents: int
    fee_cents: int
    collect_cents: int  # cash the customer hands over
    give_cents: int  # cash the shop hands to the customer

    @property
    def drawer_delta_cents(self) -> int:
        return self.collect_cents - self.give_cents

    @property
    def wallet_delta_cents(self) -> int:
        return -self.amount_cents if self.kind == "cash_in" else self.amount_cents


def quote_wallet(
    kind: WalletKind,
    amount_cents: int,
    fee_mode: CashOutFeeMode = "deducted",
    s: FeeSchedule = DEFAULT_SCHEDULE,
) -> WalletQuote:
    fee = ewallet_fee(amount_cents, s)
    if kind == "cash_in":
        return WalletQuote(kind, "added", amount_cents, fee, collect_cents=amount_cents + fee, give_cents=0)
    if kind != "cash_out":
        raise FeeError("Choose cash-in or cash-out")
    if fee_mode == "paid_in_cash":
        return WalletQuote(kind, fee_mode, amount_cents, fee, collect_cents=fee, give_cents=amount_cents)
    if fee_mode == "included":
        payout = payout_with_fee_included(amount_cents, s)
        return WalletQuote(kind, fee_mode, amount_cents, amount_cents - payout, collect_cents=0, give_cents=payout)
    if fee_mode != "deducted":
        raise FeeError("Choose how the cash-out fee is paid")
    if amount_cents <= fee:
        raise FeeError("Cash-out amount must be more than the fee")
    return WalletQuote(kind, fee_mode, amount_cents, fee, collect_cents=0, give_cents=amount_cents - fee)


def nearest_fee_included(sent_cents: int, s: FeeSchedule = DEFAULT_SCHEDULE) -> tuple[int, int]:
    """
    The largest payout whose payout + fee is at most sent_cents: (payout, payout + fee).
    payout + fee(payout) rises with every peso, so a binary search finds it.
    """
    _check_amount(sent_cents)
    low, high = 1, sent_cents // 100  # in pesos
    while low < high:
        mid = (low + high + 1) // 2
        if mid * 100 + ewallet_fee(mid * 100, s) <= sent_cents:
            low = mid
        else:
            high = mid - 1
    payout = low * 100
    return payout, payout + ewallet_fee(payout, s)


def payout_with_fee_included(sent_cents: int, s: FeeSchedule = DEFAULT_SCHEDULE) -> int:
    """
    The customer sent the payout plus its fee (₱6,120 = ₱6,000 + ₱120) to get an exact amount.
    At most one payout fits.
    """
    payout, total = nearest_fee_included(sent_cents, s)
    if total != sent_cents:
        if total > sent_cents:
            raise FeeError("Cash-out amount must be more than the fee")
        raise FeeError(
            f"₱{sent_cents // 100:,} isn't an amount plus its fee "
            f"(₱{payout // 100:,} + ₱{(total - payout) // 100:,} fee = ₱{total // 100:,}). Use Deduct from payout instead."
        )
    return payout


def quote_personal_wallet(kind: WalletKind, amount_cents: int, from_shop: bool) -> WalletQuote:
    """
    Admin's own cash-in/cash-out, no fee. Cash-in from shop funds collects nothing: the shop's
    GCash/Maya just goes down. A cash-out always hands over the cash, so it can't be from shop funds.
    """
    _check_amount(amount_cents)
    if kind == "cash_in":
        return WalletQuote(kind, "none", amount_cents, 0, collect_cents=0 if from_shop else amount_cents, give_cents=0)
    if kind != "cash_out":
        raise FeeError("Choose cash-in or cash-out")
    if from_shop:
        raise FeeError("A cash-out can't be from shop funds. To take cash from the drawer, record it in End of day.")
    return WalletQuote(kind, "none", amount_cents, 0, collect_cents=0, give_cents=amount_cents)
