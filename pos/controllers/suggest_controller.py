"""Type-ahead suggestions from past (non-voided) transactions."""
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import Customer
from pos.models import PosSale, PosSaleLine, PosService, PosServiceItem, PosWalletTxn

LIMIT = 8
PRESET_LIMIT = 30
HISTORY_AFTER_PRESETS = 3  # past descriptions not in the pick list, shown under it


async def service_descriptions(db: AsyncSession, service_id: int, q: str) -> list[dict]:
    """
    The service's pick list first (its usual price), then other descriptions sold before under this service,
    most-used first, with the last price charged.
    """
    needle = " ".join(q.split()).upper()
    preset_query = (
        select(PosServiceItem.name, PosServiceItem.price_cents)
        .where(PosServiceItem.service_id == service_id, PosServiceItem.is_active)
        .order_by(PosServiceItem.sort_order, PosServiceItem.name)
        .limit(PRESET_LIMIT)
    )
    if needle:
        preset_query = preset_query.where(PosServiceItem.name.contains(needle, autoescape=True))
    presets = [{"description": name, "price_cents": price, "preset": True} for name, price in (await db.execute(preset_query)).all()]
    # Tarpaulin: a size below the small size in Settings is suggested at the small-tarp price.
    from pos.controllers.settings_controller import get_settings
    from pos.controllers.stock_controller import TARP_SERVICE, tarp_name, tarp_size, tarp_small

    size = tarp_size(needle)
    if size and tarp_name(*size) not in {p["description"] for p in presets}:
        settings = await get_settings(db)
        if settings.tarp_small_price_cents and tarp_small(settings, needle) and \
                (await db.execute(select(PosService.name).where(PosService.id == service_id))).scalar() == TARP_SERVICE:
            presets.insert(0, {"description": tarp_name(*size), "price_cents": settings.tarp_small_price_cents, "preset": True})
    taken = {p["description"] for p in presets}
    history = [h for h in await _past_descriptions(db, service_id, needle) if h["description"] not in taken]
    return presets + history[:HISTORY_AFTER_PRESETS] if presets else history


async def _past_descriptions(db: AsyncSession, service_id: int, needle: str) -> list[dict]:
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

    # BPS bill customers last, so a name from the register (newer, typed at the counter) wins.
    customers = await db.execute(
        select(Customer.phone, Customer.customer_name, Customer.updated_at)
        .where(Customer.phone.startswith(digits))
        .order_by(Customer.updated_at.desc())
        .limit(50)
    )
    for mobile, name, at in customers.all():
        note(mobile, name, None, at)

    ranked = sorted(found.values(), key=lambda e: e["at"], reverse=True)[:LIMIT]
    return [{"mobile": e["mobile"], "name": e["name"], "network_id": e["network_id"]} for e in ranked]
