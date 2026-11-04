import pytest

from pos.fees import (
    FeeError,
    FeeSchedule,
    ewallet_fee,
    quote_load,
    quote_wallet,
    validate_schedule,
)
from pos.money import MoneyError


def P(pesos: int) -> int:
    return pesos * 100


# The confirmed fee table in docs/PLAN.md.
@pytest.mark.parametrize(
    "amount, fee",
    [
        (300, 10),
        (499, 10),
        (500, 20),
        (999, 20),
        (1_000, 20),
        (1_200, 30),
        (1_500, 40),
        (2_000, 40),
        (2_300, 50),
        (5_750, 120),
        (1, 10),
    ],
)
def test_ewallet_fee_table(amount, fee):
    assert ewallet_fee(P(amount)) == P(fee)


@pytest.mark.parametrize(
    "amount, is_promo, fee, total",
    [
        (30, False, 5, 35),
        (50, False, 5, 55),
        (51, False, 10, 61),
        (100, False, 10, 110),
        (499, False, 10, 509),
        (500, False, 20, 520),
        (1_000, False, 20, 1_020),
        (1_030, False, 30, 1_060),
        (59, True, 10, 70),
        (69, True, 10, 80),
        (70, True, 10, 80),
        (49, True, 5, 55),
    ],
)
def test_load_quotes(amount, is_promo, fee, total):
    q = quote_load(P(amount), is_promo)
    assert q.fee_cents == P(fee)
    assert q.total_cents == P(total)
    assert q.load_cents == P(amount)


def test_promo_rounding_counts_as_income():
    q = quote_load(P(59), True)
    assert q.priced_cents == P(60)
    assert q.income_cents == P(11)


def test_cash_in():
    q = quote_wallet("cash_in", P(1_000))
    assert (q.fee_cents, q.collect_cents, q.give_cents) == (P(20), P(1_020), 0)
    assert q.drawer_delta_cents == P(1_020)
    assert q.wallet_delta_cents == -P(1_000)


def test_cash_out_fee_deducted():
    q = quote_wallet("cash_out", P(1_000), "deducted")
    assert (q.collect_cents, q.give_cents) == (0, P(980))
    assert q.drawer_delta_cents == -P(980)
    assert q.wallet_delta_cents == P(1_000)


def test_cash_out_fee_paid_in_cash_moves_drawer_the_same():
    q = quote_wallet("cash_out", P(1_000), "paid_in_cash")
    assert (q.collect_cents, q.give_cents) == (P(20), P(1_000))
    assert q.drawer_delta_cents == -P(980)


def test_cash_out_must_exceed_fee():
    with pytest.raises(FeeError):
        quote_wallet("cash_out", P(10), "deducted")


@pytest.mark.parametrize("cents", [0, -100, 150])
def test_amount_must_be_positive_whole_pesos(cents):
    with pytest.raises(MoneyError):
        ewallet_fee(cents)


def test_default_schedule_is_valid():
    validate_schedule(FeeSchedule())


@pytest.mark.parametrize(
    "brackets",
    [
        ((100, 40_000, 1_000), (50_000, 99_900, 2_000)),  # gap
        ((100, 49_900, 1_000), (40_000, 99_900, 2_000)),  # overlap
        ((100, 49_900, 1_000),),  # stops short of the block
        (),
    ],
)
def test_invalid_brackets_rejected(brackets):
    with pytest.raises(FeeError):
        validate_schedule(FeeSchedule(brackets=brackets))


def test_load_cost_after_wallet_discount():
    from pos.fees import load_cost

    assert load_cost(9_900, 300) == 9_603  # Maya: ₱99 → ₱96.03
    assert load_cost(5_000, 300) == 4_850
    assert load_cost(9_900, 0) == 9_900
    assert load_cost(3_300, 250) == 3_218  # ₱32.175 rounds to ₱32.18
