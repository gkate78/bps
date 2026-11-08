from datetime import timedelta
from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

from app.static_version import add_version_filter
from pos.money import fmt, peso

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# BPS's templates too, for the bill receipt (_bill_receipt.html) printed with a sale.
templates.env.loader = ChoiceLoader(
    [templates.env.loader, FileSystemLoader(str(Path(__file__).parent.parent / "app" / "templates"))]
)
templates.env.filters["peso"] = peso
templates.env.filters["fmt"] = fmt
templates.env.globals["timedelta"] = timedelta
add_version_filter(templates)


def pesos_input(cents) -> str:
    """Value for a money input: 150000 -> '1500', 1234567 -> '12345.67'."""
    cents = int(cents or 0)
    return str(cents // 100) if cents % 100 == 0 else f"{cents / 100:.2f}"


templates.env.filters["pesos_input"] = pesos_input
