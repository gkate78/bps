"""Type-ahead suggestions from past (non-voided) transactions."""
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pos.models import PosSale, PosSaleLine, PosWalletTxn

LIMIT = 8


async def service_descriptions(db: AsyncSession, service_id: int, q: str) -> list[dict]:
    """Descriptions sold before under this service, most-used first, with the last price charged."""
    needle = " ".join(q.split()).upper()
    last_id = func.max(PosSaleLine.id).label("last_id")
    uses = func.count(PosSaleLine.id).label("uses")
    query = (
        select(PosSaleLine.description, uses, last_id)
        .join(PosSale, PosSale.id == PosSaleLine.sale_id)
        .where(
            PosSaleLine.kind == "service",
            PosSaleLine.service_id == service_id,
            PosSaleLine.description.is_not(None),
            PosSale.status == "completed",
        )
        .group_by(PosSaleLine.description)
        .order_by(uses.desc(), last_id.desc())
        .limit(LIMIT)
    )
    if needle:
        query = query.where(PosSaleLine.description.contains(needle, autoescape=True))
    rows = (await db.execute(query)).all()
    if not rows:
        return []
    prices = dict(
        (await db.execute(select(PosSaleLine.id, PosSaleLine.unit_price_cents).where(PosSaleLine.id.in_([r.last_id for r in rows])))).all()
    )
    return [{"description": r.description, "price_cents": prices[r.last_id], "uses": r.uses} for r in rows]


async def mobiles(db: AsyncSession, q: str) -> list[dict]:
    """Mobile numbers starting with q, newest first, with the latest name and load network seen for each."""
    digits = "".join(ch for ch in q if ch.isdigit())
    if len(digits) < 3:
        return []
    found: dict[str, dict] = {}

    def note(mobile, name, network_id, at):
        if not mobile:
            return
        entry = found.setdefault(mobile, {"mobile": mobile, "name": None, "network_id": None, "at": at})
        entry["at"] = max(entry["at"], at)
        # Rows arrive newest first, so the first name/network seen is the latest.
        entry["name"] = entry["name"] or name
        entry["network_id"] = entry["network_id"] or network_id

    loads = await db.execute(
        select(PosSaleLine.mobile_no, PosSale.customer_name, PosSaleLine.network_id, PosSale.created_at)
        .join(PosSale, PosSale.id == PosSaleLine.sale_id)
        .where(PosSaleLine.kind == "load", PosSaleLine.mobile_no.startswith(digits), PosSale.status == "completed")
        .order_by(PosSale.created_at.desc())
        .limit(50)
    )
    for mobile, name, network_id, at in loads.all():
        note(mobile, name, network_id, at)

    txns = await db.execute(
        select(PosWalletTxn.customer_mobile, PosWalletTxn.customer_name, PosWalletTxn.created_at)
        .where(PosWalletTxn.customer_mobile.startswith(digits), PosWalletTxn.status == "completed")
        .order_by(PosWalletTxn.created_at.desc())
        .limit(50)
    )
    for mobile, name, at in txns.all():
        note(mobile, name, None, at)

    sales = await db.execute(
        select(PosSale.customer_phone, PosSale.customer_name, PosSale.created_at)
        .where(PosSale.customer_phone.startswith(digits), PosSale.status == "completed")
        .order_by(PosSale.created_at.desc())
        .limit(50)
    )
    for mobile, name, at in sales.all():
        note(mobile, name, None, at)

    ranked = sorted(found.values(), key=lambda e: e["at"], reverse=True)[:LIMIT]
    return [{"mobile": e["mobile"], "name": e["name"], "network_id": e["network_id"]} for e in ranked]
