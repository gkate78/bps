"""
Materials stock (DEC-077). See pos/models/stock.py.

A service line uses materials when its description is a pick list item of its service with materials set.
Stock can go below zero (sold before a restock was recorded); the next count corrects it.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pos.controllers.settings_controller import add_audit
from pos.models import PosItemMaterial, PosMaterial, PosSale, PosSaleLine, PosService, PosServiceItem, PosStockMove

MAX_QTY = 1_000_000


class StockError(Exception):
    pass


def _round(value: float) -> float:
    # 6 places, so thirds add up (3 × 1/3 sheet = 1 sheet, shown rounded).
    return round(float(value) + 0.0, 6)


# ---------- Tarpaulin sizes ----------

TARP_SERVICE = "TARPAULIN"
# Tarps may be printed by another shop, charged by the sq ft. That printing is kept as a "material" in sq ft so
# its cost shows in Cost and profit; it is never counted, so it gives no low-stock warning. The cost a sq ft and
# the small-tarp price and cost are the shop's own, set in Settings (PosSettings.tarp_*).
TARP = "TARPAULIN (SENT OUT)"


def tarp_size(text: str) -> Optional[tuple[float, float]]:
    """'1X1.5', '2 x 3', '2X3 FT' → (width, height) in feet; anything else → None."""
    import re

    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[X×]\s*(\d+(?:\.\d+)?)\s*(?:FT|FEET|')?\s*", str(text or "").upper())
    if not match:
        return None
    width, height = float(match.group(1)), float(match.group(2))
    return (width, height) if 0 < width <= 100 and 0 < height <= 100 else None


def tarp_sqft(width: float, height: float) -> float:
    return _round(width * height)


def tarp_small(settings, description: str) -> bool:
    """A tarp below the small size in Settings (it has its own price and cost)."""
    size = tarp_size(description)
    return bool(size and settings and settings.tarp_small_below_sqft > 0 and size[0] * size[1] < settings.tarp_small_below_sqft)


def tarp_name(width: float, height: float) -> str:
    return f"{width:g}X{height:g}"


def _clean(value, max_len: int) -> str:
    return " ".join(str(value or "").split()).upper()[:max_len]


def _qty(value, label: str, allow_zero: bool = False) -> float:
    text = str(value).replace(",", "").strip()
    try:
        if "/" in text:  # e.g. 1/3: an ID picture package is a third of an A4 photo paper
            top, bottom = text.split("/", 1)
            qty = float(top) / float(bottom)
        else:
            qty = float(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise StockError(f"{label} must be a number or a fraction like 1/3") from exc
    if qty < 0 or (qty == 0 and not allow_zero) or qty > MAX_QTY:
        raise StockError(f"{label} must be {'0' if allow_zero else 'more than 0'} up to {MAX_QTY:,}")
    return _round(qty)


async def list_materials(db: AsyncSession, active_only: bool = False) -> list[PosMaterial]:
    query = select(PosMaterial).order_by(PosMaterial.sort_order, PosMaterial.name)
    if active_only:
        query = query.where(PosMaterial.is_active)
    return list((await db.execute(query)).scalars().all())


async def get_material(db: AsyncSession, material_id: int) -> PosMaterial:
    material = (await db.execute(select(PosMaterial).where(PosMaterial.id == material_id))).scalar_one_or_none()
    if not material:
        raise StockError("Material not found")
    return material


def is_low(material: PosMaterial) -> bool:
    return bool(material.is_active and material.counted_at and material.low_stock_at > 0
                and material.stock_qty <= material.low_stock_at)


async def low_stock(db: AsyncSession) -> list[PosMaterial]:
    """Counted materials at or below their warning level."""
    return [m for m in await list_materials(db, active_only=True) if is_low(m)]


def _move(db, material: PosMaterial, kind: str, qty: float, **extra) -> PosStockMove:
    material.stock_qty = _round(material.stock_qty + qty)
    db.add(material)
    move = PosStockMove(material_id=material.id, kind=kind, qty=_round(qty), stock_after=material.stock_qty, **extra)
    db.add(move)
    return move


# ---------- Sales ----------

async def recipes_for(db: AsyncSession, keys: set[tuple[int, str]]) -> dict[tuple[int, str], list[tuple[int, float]]]:
    """(service_id, item name) → [(material_id, qty per unit)] for the pick list items that use materials."""
    if not keys:
        return {}
    rows = await db.execute(
        select(PosServiceItem.service_id, PosServiceItem.name, PosItemMaterial.material_id, PosItemMaterial.qty_per_unit)
        .join(PosItemMaterial, PosItemMaterial.service_item_id == PosServiceItem.id)
        .where(PosServiceItem.service_id.in_({k[0] for k in keys}), PosServiceItem.name.in_({k[1] for k in keys}))
    )
    out: dict[tuple[int, str], list[tuple[int, float]]] = {}
    for service_id, name, material_id, per_unit in rows.all():
        if (service_id, name) in keys:
            out.setdefault((service_id, name), []).append((material_id, per_unit))
    return out


async def use_for_sale(db: AsyncSession, sale: PosSale, lines: list[PosSaleLine]) -> int:
    """Take the materials the sale's service lines use off the stock (lines must have ids). Returns moves made."""
    service_lines = [l for l in lines if l.kind == "service" and l.service_id and l.description]
    recipes = await recipes_for(db, {(l.service_id, l.description) for l in service_lines})
    # A tarpaulin typed as a size that isn't in the pick list (e.g. 1X1.5) costs the outside printing by its size.
    tarp_lines = [l for l in service_lines if (l.service_id, l.description) not in recipes and tarp_size(l.description)]
    tarp = None
    if tarp_lines:
        tarp_ids = set((await db.execute(select(PosService.id).where(PosService.name == TARP_SERVICE))).scalars().all())
        tarp_lines = [l for l in tarp_lines if l.service_id in tarp_ids]
        tarp = (await db.execute(select(PosMaterial).where(PosMaterial.name == TARP))).scalar_one_or_none() if tarp_lines else None
    if not recipes and not tarp:
        return 0
    materials = {m.id: m for m in await list_materials(db)}
    from pos.controllers.settings_controller import get_settings

    settings = await get_settings(db)
    made = 0
    for line in service_lines:
        uses = recipes.get((line.service_id, line.description), [])
        if not uses and tarp and line in tarp_lines:
            uses = [(tarp.id, tarp_sqft(*tarp_size(line.description)))]
        for material_id, per_unit in uses:
            material = materials.get(material_id)
            if not material or per_unit <= 0:
                continue
            used = _round(per_unit * line.qty)
            cost_cents = int(round(used * material.avg_cost * 100))
            if material.name == TARP and settings.tarp_small_cost_cents and tarp_small(settings, line.description):
                cost_cents = settings.tarp_small_cost_cents * int(line.qty)  # a small tarp's own cost
            _move(db, material, "sale", -used, cost_cents=cost_cents,
                  sale_id=sale.id, sale_line_id=line.id, service_id=line.service_id, user_id=sale.cashier_user_id)
            made += 1
    return made


async def return_for_void(db: AsyncSession, sale_id: int, user_id: Optional[int]) -> int:
    """Put back what a voided sale used (once)."""
    moves = (await db.execute(select(PosStockMove).where(PosStockMove.sale_id == sale_id))).scalars().all()
    if any(m.kind == "void" for m in moves):
        return 0
    materials = {m.id: m for m in await list_materials(db)}
    made = 0
    for move in moves:
        if move.kind == "sale" and move.material_id in materials:
            _move(db, materials[move.material_id], "void", -move.qty, cost_cents=-move.cost_cents, sale_id=sale_id,
                  sale_line_id=move.sale_line_id, service_id=move.service_id, user_id=user_id)
            made += 1
    return made


# ---------- Restock, count, materials ----------

async def restock(db: AsyncSession, material_id: int, qty, total_cost, supplier: str, note: str, user_id: int,
                  when: Optional[date] = None) -> PosStockMove:
    """Stock bought: adds it and averages its cost in (stock below zero counts as none on hand)."""
    from pos.money import MoneyError, to_cents

    material = await get_material(db, material_id)
    qty = _qty(qty, "Quantity")
    try:
        cost_cents = to_cents(total_cost or "0", field="Total cost")
    except MoneyError as exc:
        raise StockError(str(exc)) from exc
    if cost_cents < 0:
        raise StockError("Total cost can't be negative")
    on_hand = max(material.stock_qty, 0)
    if cost_cents:
        material.avg_cost = round((on_hand * material.avg_cost + cost_cents / 100) / (on_hand + qty), 4)
    material.counted_at = material.counted_at or datetime.now()
    move = _move(db, material, "restock", qty, cost_cents=cost_cents, supplier=_clean(supplier, 80) or None,
                 note=_clean(note, 160) or None, user_id=user_id)
    if when:
        move.created_at = datetime.combine(when, datetime.now().time())
    add_audit(db, "material", material.id, "restock", user_id, {"qty": qty, "cost_cents": cost_cents, "supplier": move.supplier})
    await db.commit()
    return move


async def count(db: AsyncSession, material_id: int, counted, note: str, user_id: int) -> PosStockMove:
    """What's on the shelf: the difference is recorded (spoilage, unrecorded use), at the average cost."""
    material = await get_material(db, material_id)
    counted = _qty(counted, "Count", allow_zero=True)
    diff = _round(counted - material.stock_qty)
    material.counted_at = datetime.now()
    move = _move(db, material, "count", diff, cost_cents=int(round(diff * material.avg_cost * 100)),
                 note=_clean(note, 160) or None, user_id=user_id)
    add_audit(db, "material", material.id, "count", user_id, {"counted": counted, "difference": diff})
    await db.commit()
    return move


async def save_material(db: AsyncSession, material_id: Optional[int], name: str, unit: str, low_stock_at, user_id: int,
                        avg_cost=None) -> PosMaterial:
    name = _clean(name, 80)
    if not name:
        raise StockError("Type the material's name")
    unit = _clean(unit, 20) or "PC"
    low = _qty(low_stock_at or 0, "Warn at", allow_zero=True)
    taken = (await db.execute(select(PosMaterial).where(PosMaterial.name == name))).scalar_one_or_none()
    if material_id:
        material = await get_material(db, material_id)
        if taken and taken.id != material.id:
            raise StockError(f"{name} already exists")
        before = {"name": material.name, "unit": material.unit, "low_stock_at": material.low_stock_at, "avg_cost": material.avg_cost}
    else:
        if taken:
            raise StockError(f"{name} already exists")
        last = (await db.execute(select(func.max(PosMaterial.sort_order)))).scalar() or 0
        material = PosMaterial(name=name, sort_order=last + 1)
        before = None
    material.name, material.unit, material.low_stock_at = name, unit, low
    if avg_cost not in (None, ""):
        try:
            material.avg_cost = round(float(str(avg_cost).replace(",", "")), 4)
        except ValueError as exc:
            raise StockError("Cost per unit must be a number") from exc
        if material.avg_cost < 0:
            raise StockError("Cost per unit can't be negative")
    db.add(material)
    await db.flush()
    add_audit(db, "material", material.id, "update" if before else "create", user_id,
              {"from": before, "to": {"name": name, "unit": unit, "low_stock_at": low, "avg_cost": material.avg_cost}})
    await db.commit()
    return material


async def toggle_material(db: AsyncSession, material_id: int, user_id: int) -> PosMaterial:
    material = await get_material(db, material_id)
    material.is_active = not material.is_active
    db.add(material)
    add_audit(db, "material", material.id, "enable" if material.is_active else "disable", user_id)
    await db.commit()
    return material


# ---------- What each item uses ----------

async def item_uses(db: AsyncSession) -> dict[int, list[PosItemMaterial]]:
    out: dict[int, list[PosItemMaterial]] = {}
    for row in (await db.execute(select(PosItemMaterial).order_by(PosItemMaterial.id))).scalars().all():
        out.setdefault(row.service_item_id, []).append(row)
    return out


async def set_item_use(db: AsyncSession, service_item_id: int, material_id: Optional[int], qty_per_unit, user_id: int) -> None:
    """Set what one unit of a pick list item uses: one material (or none when material_id is empty)."""
    item = (await db.execute(select(PosServiceItem).where(PosServiceItem.id == service_item_id))).scalar_one_or_none()
    if not item:
        raise StockError("Item not found")
    rows = (await db.execute(select(PosItemMaterial).where(PosItemMaterial.service_item_id == item.id))).scalars().all()
    for row in rows:
        await db.delete(row)
    detail = {"item": item.name, "material_id": None}
    if material_id:
        material = await get_material(db, material_id)
        per_unit = _qty(qty_per_unit or 1, "Uses per unit")
        db.add(PosItemMaterial(service_item_id=item.id, material_id=material.id, qty_per_unit=per_unit))
        detail = {"item": item.name, "material": material.name, "qty_per_unit": per_unit}
    add_audit(db, "service_item", item.id, "materials", user_id, detail)
    await db.commit()


# ---------- Rejects (DEC-078) ----------

REJECT_REASONS = {"MISPRINT": "Misprint", "PAPER JAM": "Paper jam", "CUSTOMER REPRINT": "Customer reprint", "OTHER": "Other"}


def sale_id_from(text: str) -> Optional[int]:
    """S-000123, s123 or 123 → 123; blank → None."""
    text = str(text or "").strip().upper().replace(" ", "")
    if not text:
        return None
    if text.startswith("S-"):
        text = text[2:]
    elif text.startswith("S"):
        text = text[1:]
    if not text.isdigit() or int(text) <= 0:
        raise StockError("Sale no. should look like S-000123")
    return int(text)


async def reject_choices(db: AsyncSession) -> tuple[list[tuple[PosServiceItem, str, list[tuple[PosMaterial, float]]]], list[PosMaterial]]:
    """What a cashier can mark as wasted: pick list items that use materials (counted in prints), or a material itself."""
    materials = {m.id: m for m in await list_materials(db, active_only=True)}
    rows = await db.execute(
        select(PosServiceItem, PosService.name, PosItemMaterial.material_id, PosItemMaterial.qty_per_unit)
        .join(PosService, PosService.id == PosServiceItem.service_id)
        .join(PosItemMaterial, PosItemMaterial.service_item_id == PosServiceItem.id)
        .where(PosServiceItem.is_active)
        .order_by(PosService.sort_order, PosService.name, PosServiceItem.sort_order, PosServiceItem.name)
    )
    items: dict[int, tuple[PosServiceItem, str, list]] = {}
    for item, service_name, material_id, per_unit in rows.all():
        if material_id in materials:
            items.setdefault(item.id, (item, service_name, []))[2].append((materials[material_id], per_unit))
    return list(items.values()), list(materials.values())


async def record_reject(db: AsyncSession, what: str, qty, reason: str, sale_ref: str, note: str, user_id: int) -> list[PosStockMove]:
    """
    Wasted stock, taken off now. `what` is "item:<id>" (qty in prints; the item's materials per print) or
    "material:<id>" (qty in the material's unit). A customer reprint must name the sale it was for.
    """
    reason = str(reason or "").strip().upper()
    if reason not in REJECT_REASONS:
        raise StockError("Choose why it was rejected")
    sale_id = sale_id_from(sale_ref)
    if reason == "CUSTOMER REPRINT" and not sale_id:
        raise StockError("Customer reprint: type the sale no. it was for (on the receipt, e.g. S-000123)")
    if sale_id and not (await db.execute(select(PosSale.id).where(PosSale.id == sale_id))).first():
        raise StockError(f"Sale S-{sale_id:06d} not found")
    kind, _, raw_id = str(what or "").partition(":")
    if not raw_id.isdigit():
        raise StockError("Choose what was rejected")
    qty = _qty(qty, "Quantity")
    note = _clean(note, 160)
    uses: list[tuple[PosMaterial, float]] = []
    service_id = None
    label = ""
    if kind == "item":
        items, _ = await reject_choices(db)
        found = next((entry for entry in items if entry[0].id == int(raw_id)), None)
        if not found:
            raise StockError("That item uses no materials")
        item, service_name, materials = found
        service_id = item.service_id
        label = f"{qty:g} × {service_name} {item.name}"
        uses = [(material, _round(per_unit * qty)) for material, per_unit in materials]
    elif kind == "material":
        material = await get_material(db, int(raw_id))
        uses = [(material, qty)]
    else:
        raise StockError("Choose what was rejected")
    moves = []
    for material, used in uses:
        moves.append(_move(db, material, "reject", -used, cost_cents=int(round(used * material.avg_cost * 100)),
                           sale_id=sale_id, service_id=service_id, reason=reason,
                           note=" · ".join(x for x in (label, note) if x)[:160] or None, user_id=user_id))
    add_audit(db, "material", uses[0][0].id, "reject", user_id,
              {"what": what, "qty": qty, "reason": reason, "sale_id": sale_id, "materials": {m.name: q for m, q in uses}})
    await db.commit()
    return moves


async def recent_rejects(db: AsyncSession, user_id: Optional[int] = None, limit: int = 30) -> list[PosStockMove]:
    query = select(PosStockMove).where(PosStockMove.kind == "reject").order_by(PosStockMove.id.desc()).limit(limit)
    if user_id is not None:
        query = query.where(PosStockMove.user_id == user_id)
    return list((await db.execute(query)).scalars().all())


# ---------- Suggested setup ----------

PAPER = {"SHORT": "SHORT BOND PAPER", "LONG": "LONG BOND PAPER", "A4": "A4 BOND PAPER"}
FILM = {"ID SMALL": "LAMINATION FILM ID SMALL", "ID MEDIUM": "LAMINATION FILM ID MEDIUM",
        "SHORT": "LAMINATION FILM SHORT", "LONG": "LAMINATION FILM LONG", "A4": "LAMINATION FILM A4"}
PHOTO_PAPER = "A4 PHOTO PAPER"
ID_PACKAGES_PER_SHEET = 3  # the owner prints 3 ID picture packages on one A4 photo paper
PHOTO_3R = "3R PHOTO PAPER"
WALLETS_PER_3R = 2  # the owner prints 2 wallet-size photos on one 3R photo paper
PHOTO_4R = "4R PHOTO PAPER"
PHOTO_5R = "5R PHOTO PAPER"  # out of stock for now: 5R photos are printed 2 on one A4 photo paper
FIVE_R_PER_A4 = 2
NOT_BOND = ("PHOTO", "VELLUM", "GSM", "STICKER", "CARD")


def suggested_use(service: str, item: str) -> Optional[tuple[str, float]]:
    """(material, uses per unit) a pick list item most likely uses, or None."""
    service, item = service.upper(), item.upper()
    if service == "ID PICTURE":
        return PHOTO_PAPER, 1 / ID_PACKAGES_PER_SHEET
    if service == "LAMINATION":
        return (FILM[item], 1) if item in FILM else None
    if service == TARP_SERVICE:
        size = tarp_size(item)
        return (TARP, tarp_sqft(*size)) if size else None
    if service == "SUPPLIES":
        return (item, 1) if item in PAPER.values() else None
    if service in ("XEROX", "PRINTING"):
        if item.startswith("A4 PHOTO PRINT"):
            return PHOTO_PAPER, 1
        if "WALLET" in item:
            return PHOTO_3R, 1 / WALLETS_PER_3R
        if item.startswith("3R PHOTO"):
            return PHOTO_3R, 1
        if item.startswith("4R PHOTO"):
            return PHOTO_4R, 1
        if item.startswith("5R PHOTO"):
            return PHOTO_PAPER, 1 / FIVE_R_PER_A4
        if any(word in item for word in NOT_BOND):
            return None
        first = item.split()[0] if item.split() else ""
        return (PAPER[first], 1) if first in PAPER else None
    return None


def suggested_material(service: str, item: str) -> Optional[str]:
    use = suggested_use(service, item)
    return use[0] if use else None


async def set_up_suggested(db: AsyncSession, user_id: int) -> tuple[int, int]:
    """Adds paper and lamination film materials and links pick list items that have no materials yet."""
    from pos.controllers.settings_controller import get_settings

    tarp_cost = (await get_settings(db)).tarp_cost_sqft_cents / 100  # Settings → Tarpaulin
    materials = {m.name: m for m in await list_materials(db)}
    created = 0
    for name, unit in [(n, "SHEET") for n in PAPER.values()] + [(PHOTO_PAPER, "SHEET"), (PHOTO_3R, "SHEET"), (PHOTO_4R, "SHEET"), (PHOTO_5R, "SHEET")] + [(n, "PC") for n in FILM.values()] + [(TARP, "SQ FT")]:
        if name not in materials:
            last = (await db.execute(select(func.max(PosMaterial.sort_order)))).scalar() or 0
            material = PosMaterial(name=name, unit=unit, sort_order=last + 1,
                                   avg_cost=tarp_cost if name == TARP else 0)
            db.add(material)
            await db.flush()
            materials[name] = material
            created += 1
    used = await item_uses(db)
    rows = await db.execute(
        select(PosServiceItem, PosService.name).join(PosService, PosService.id == PosServiceItem.service_id)
    )
    linked = 0
    for item, service_name in rows.all():
        if item.id in used:
            continue
        use = suggested_use(service_name, item.name)
        if use and use[0] in materials:
            db.add(PosItemMaterial(service_item_id=item.id, material_id=materials[use[0]].id, qty_per_unit=_round(use[1])))
            linked += 1
    add_audit(db, "material", 0, "set_up_suggested", user_id, {"materials_added": created, "items_linked": linked})
    await db.commit()
    return created, linked


# ---------- Reports ----------

async def recent_moves(db: AsyncSession, limit: int = 50, kinds: Optional[tuple[str, ...]] = None) -> list[PosStockMove]:
    query = select(PosStockMove).order_by(PosStockMove.id.desc()).limit(limit)
    if kinds:
        query = query.where(PosStockMove.kind.in_(kinds))
    return list((await db.execute(query)).scalars().all())


@dataclass
class ServiceCost:
    service: str
    sales_cents: int = 0
    material_cents: int = 0

    @property
    def profit_cents(self) -> int:
        return self.sales_cents - self.material_cents


@dataclass
class CostReport:
    services: list[ServiceCost] = field(default_factory=list)
    restock_cents: int = 0
    spoilage_cents: int = 0  # counts' differences at the average cost (negative = missing stock)
    rejects: dict[str, int] = field(default_factory=dict)  # reason → cost of rejects in centavos

    @property
    def rejects_cents(self) -> int:
        return sum(self.rejects.values())

    @property
    def sales_cents(self) -> int:
        return sum(s.sales_cents for s in self.services)

    @property
    def material_cents(self) -> int:
        return sum(s.material_cents for s in self.services)


async def cost_report(db: AsyncSession, start: datetime, end: datetime) -> CostReport:
    """Per service: sales (completed sales), material used at the average cost when sold (voids taken off)."""
    report = CostReport()
    by_service: dict[int, ServiceCost] = {}
    sales = await db.execute(
        select(PosSaleLine.service_id, PosSaleLine.service_name, func.sum(PosSaleLine.line_total_cents))
        .join(PosSale, PosSale.id == PosSaleLine.sale_id)
        .where(PosSaleLine.kind == "service", PosSale.status == "completed", PosSale.personal.is_(None),
               PosSale.created_at >= start, PosSale.created_at < end)
        .group_by(PosSaleLine.service_id, PosSaleLine.service_name)
    )
    names = dict((await db.execute(select(PosService.id, PosService.name))).all())
    for service_id, name, total in sales.all():
        item = by_service.setdefault(service_id, ServiceCost(names.get(service_id, name)))
        item.sales_cents += int(total or 0)
    used = await db.execute(
        select(PosStockMove.service_id, func.sum(PosStockMove.cost_cents))
        .join(PosSale, PosSale.id == PosStockMove.sale_id)
        .where(PosStockMove.kind.in_(("sale", "void")), PosSale.status == "completed", PosSale.personal.is_(None),
               PosSale.created_at >= start, PosSale.created_at < end)
        .group_by(PosStockMove.service_id)
    )
    for service_id, cost in used.all():
        item = by_service.setdefault(service_id, ServiceCost(names.get(service_id, "?")))
        item.material_cents += int(cost or 0)
    report.services = sorted(by_service.values(), key=lambda s: s.sales_cents, reverse=True)
    other = await db.execute(
        select(PosStockMove.kind, func.sum(PosStockMove.cost_cents))
        .where(PosStockMove.kind.in_(("restock", "count")), PosStockMove.created_at >= start, PosStockMove.created_at < end)
        .group_by(PosStockMove.kind)
    )
    for kind, cost in other.all():
        if kind == "restock":
            report.restock_cents = int(cost or 0)
        else:
            report.spoilage_cents = int(cost or 0)
    rejects = await db.execute(
        select(PosStockMove.reason, func.sum(PosStockMove.cost_cents))
        .where(PosStockMove.kind == "reject", PosStockMove.created_at >= start, PosStockMove.created_at < end)
        .group_by(PosStockMove.reason)
    )
    for reason, cost in rejects.all():
        report.rejects[REJECT_REASONS.get(reason or "", "Other")] = report.rejects.get(REJECT_REASONS.get(reason or "", "Other"), 0) + int(cost or 0)
    return report
