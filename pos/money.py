"""Money helpers. All amounts are stored and computed as integer centavos."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional


class MoneyError(ValueError):
    pass


def to_cents(value, *, field: str = "Amount") -> int:
    """Parse '1,234.50', 1234.5 or 1234 into centavos. Rejects blanks, negatives and >2 decimals."""
    if value is None:
        raise MoneyError(f"{field} is required")
    text = str(value).strip().replace(",", "").replace("₱", "")
    if text == "":
        raise MoneyError(f"{field} is required")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise MoneyError(f"{field} must be a number") from exc
    if not amount.is_finite():
        raise MoneyError(f"{field} must be a number")
    if amount < 0:
        raise MoneyError(f"{field} cannot be negative")
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise MoneyError(f"{field} can have at most 2 decimal places")
    return int(cents)


def to_cents_optional(value, *, field: str = "Amount") -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    return to_cents(value, field=field)


def whole_pesos(cents: int, *, field: str = "Amount") -> int:
    """Load and GCash/Maya amounts are whole pesos."""
    if cents % 100:
        raise MoneyError(f"{field} must be in whole pesos")
    return cents


def cash_due_cents(cents: int) -> int:
    """Cash is collected to the whole peso: under 50 centavos rounds down, 50 and up rounds up.
    ₱1,025.45 → ₱1,025 (₱1,100 gets ₱75 change); ₱1,025.50 → ₱1,026 (₱74 change)."""
    return (int(cents) + 50) // 100 * 100


def fmt(cents: Optional[int]) -> str:
    """12345 -> '123.45', with thousands separators."""
    value = (Decimal(int(cents or 0)) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{value:,.2f}"


def peso(cents: Optional[int]) -> str:
    cents = int(cents or 0)
    sign = "-" if cents < 0 else ""
    return f"{sign}₱{fmt(abs(cents))}"
