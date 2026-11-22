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


# The example fee schedule in pos/fees.py (₱25 per ₱1,000, ₱15 / ₱25 brackets). The shop's own is in Settings.
@pytest.mark.parametrize(
    "amount, fee",
    [
        (300, 15),
        (499, 15),
        (500, 25),
        (999, 25),
        (1_000, 25),
        (1_200, 40),
        (1_500, 50),
        (2_000, 50),
        (2_300, 65),
        (5_750, 150),
        (1, 15),
    ],
)
def test_ewallet_fee_table(amount, fee):
    assert ewallet_fee(P(amount)) == P(fee)


@pytest.mark.parametrize(
    "amount, is_promo, fee, total",
    [
        (30, False, 3, 33),
        (50, False, 3, 53),
        (51, False, 15, 66),
        (100, False, 15, 115),
        (499, False, 15, 514),
        (500, False, 25, 525),
        (1_000, False, 25, 1_025),
        (1_030, False, 40, 1_070),
        (59, True, 15, 75),
        (69, True, 15, 85),
        (70, True, 15, 85),
        (49, True, 3, 53),
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
    assert q.income_cents == P(16)


def test_cash_in():
    q = quote_wallet("cash_in", P(1_000))
    assert (q.fee_cents, q.collect_cents, q.give_cents) == (P(25), P(1_025), 0)
    assert q.drawer_delta_cents == P(1_025)
    assert q.wallet_delta_cents == -P(1_000)


def test_cash_out_fee_deducted():
    q = quote_wallet("cash_out", P(1_000), "deducted")
    assert (q.collect_cents, q.give_cents) == (0, P(975))
    assert q.drawer_delta_cents == -P(975)
    assert q.wallet_delta_cents == P(1_000)


def test_cash_out_fee_paid_in_cash_moves_drawer_the_same():
    q = quote_wallet("cash_out", P(1_000), "paid_in_cash")
    assert (q.collect_cents, q.give_cents) == (P(25), P(1_000))
    assert q.drawer_delta_cents == -P(975)


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

    assert load_cost(9_900, 200) == 9_702  # a 2% wallet discount: ₱99 → ₱97.02
    assert load_cost(5_000, 200) == 4_900
    assert load_cost(9_900, 0) == 9_900
    assert load_cost(3_300, 250) == 3_218  # ₱32.175 rounds to ₱32.18


@pytest.mark.parametrize(
    "sent, payout, fee",
    [(6_150, 6_000, 150), (1_025, 1_000, 25), (1_550, 1_500, 50), (525, 500, 25), (6_166, 6_001, 165)],
)
def test_cash_out_fee_included_in_amount_sent(sent, payout, fee):
    q = quote_wallet("cash_out", P(sent), "included")
    assert (q.fee_cents, q.collect_cents, q.give_cents) == (P(fee), 0, P(payout))
    assert q.wallet_delta_cents == P(sent)
    assert q.drawer_delta_cents == -P(payout)


@pytest.mark.parametrize("sent", [6_155, 520, 10, 1])
def test_cash_out_fee_included_rejects_amounts_that_dont_fit(sent):
    with pytest.raises(FeeError):
        quote_wallet("cash_out", P(sent), "included")
