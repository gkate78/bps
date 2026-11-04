from datetime import timedelta
from pathlib import Path

from fastapi.templating import Jinja2Templates

from pos.money import fmt, peso

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["peso"] = peso
templates.env.filters["fmt"] = fmt
templates.env.globals["timedelta"] = timedelta


def pesos_input(cents) -> str:
    """Value for a money input: 150000 -> '1500', 1234567 -> '12345.67'."""
    cents = int(cents or 0)
    return str(cents // 100) if cents % 100 == 0 else f"{cents / 100:.2f}"


templates.env.filters["pesos_input"] = pesos_input
