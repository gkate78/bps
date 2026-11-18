"""Stock page (DEC-077): materials, restocks, counts, what each item uses, and cost and profit per service."""
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pos.auth_adapter import User, page_admin
from pos.controllers import stock_controller as stock
from pos.controllers.settings_controller import list_services
from pos.database import get_db
from pos.models import PosServiceItem
from pos.templating import templates

router = APIRouter(prefix="/pos/stock")


def per_unit(value: float) -> str:
    """Uses per unit for the form: 1, 2, 0.5, or 1/3 for a third."""
    if 0 < value < 1 and abs(1 / value - round(1 / value)) < 0.001:
        return f"1/{round(1 / value)}"
    return f"{round(value, 4):g}"


templates.env.filters["per_unit"] = per_unit


def _back(request: Request, message: str = "", error: str = "", anchor: str = "") -> RedirectResponse:
    request.session["pos_flash"] = {"message": message, "error": error}
    return RedirectResponse(url=f"/pos/stock{'#' + anchor if anchor else ''}", status_code=303)


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def stock_page(
    request: Request,
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    flash = request.session.pop("pos_flash", None) or {}
    today = date.today()
    start = from_date or today.replace(day=1)
    end = to_date or today
    if end < start:
        start, end = end, start
    materials = await stock.list_materials(db)
    items = (await db.execute(select(PosServiceItem).order_by(PosServiceItem.sort_order, PosServiceItem.name))).scalars().all()
    by_service: dict[int, list] = {}
    for item in items:
        by_service.setdefault(item.service_id, []).append(item)
    return templates.TemplateResponse(
        request,
        "pos/stock.html",
        {
            "user": user,
            "active": "stock",
            "materials": materials,
            "materials_by_id": {m.id: m for m in materials},
            "low": [m for m in materials if stock.is_low(m)],
            "services": await list_services(db),
            "items_by_service": by_service,
            "uses": await stock.item_uses(db),
            "moves": await stock.recent_moves(db, 60),
            "report": await stock.cost_report(
                db, datetime.combine(start, datetime.min.time()), datetime.combine(end + timedelta(days=1), datetime.min.time())
            ),
            "from_date": start,
            "to_date": end,
            "today": today,
            "message": flash.get("message"),
            "error": flash.get("error"),
        },
    )


def _done(request: Request, action, ok: str, anchor: str):
    async def run():
        try:
            result = await action()
        except stock.StockError as exc:
            return _back(request, error=str(exc), anchor=anchor)
        return _back(request, message=ok(result) if callable(ok) else ok, anchor=anchor)
    return run()


@router.post("/materials", include_in_schema=False)
async def add_material(
    request: Request,
    name: str = Form(""),
    unit: str = Form("PC"),
    low_stock_at: str = Form("0"),
    avg_cost: str = Form(""),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _done(request, lambda: stock.save_material(db, None, name, unit, low_stock_at, user.id, avg_cost),
                       lambda m: f"{m.name} added", "materials")


@router.post("/materials/{material_id}/save", include_in_schema=False)
async def save_material(
    request: Request,
    material_id: int,
    name: str = Form(""),
    unit: str = Form("PC"),
    low_stock_at: str = Form("0"),
    avg_cost: str = Form(""),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _done(request, lambda: stock.save_material(db, material_id, name, unit, low_stock_at, user.id, avg_cost),
                       lambda m: f"{m.name} saved", "materials")


@router.post("/materials/{material_id}/toggle", include_in_schema=False)
async def toggle_material(request: Request, material_id: int, user: User = Depends(page_admin), db: AsyncSession = Depends(get_db)):
    return await _done(request, lambda: stock.toggle_material(db, material_id, user.id),
                       lambda m: f"{m.name} {'shown' if m.is_active else 'hidden'}", "materials")


@router.post("/restock", include_in_schema=False)
async def restock(
    request: Request,
    material_id: int = Form(...),
    qty: str = Form(""),
    total_cost: str = Form(""),
    supplier: str = Form(""),
    note: str = Form(""),
    day: Optional[date] = Form(None),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _done(request, lambda: stock.restock(db, material_id, qty, total_cost, supplier, note, user.id, day),
                       lambda m: f"Restock saved: stock is now {m.stock_after:g}", "restock")


@router.post("/count", include_in_schema=False)
async def count(
    request: Request,
    material_id: int = Form(...),
    counted: str = Form(""),
    note: str = Form(""),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _done(request, lambda: stock.count(db, material_id, counted, note, user.id),
                       lambda m: f"Count saved ({m.qty:+g} from what BPS expected)", "restock")


@router.post("/uses/{service_item_id}", include_in_schema=False)
async def set_use(
    request: Request,
    service_item_id: int,
    material_id: Optional[str] = Form(None),
    qty_per_unit: str = Form("1"),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    chosen = int(material_id) if material_id and material_id.isdigit() else None
    return await _done(request, lambda: stock.set_item_use(db, service_item_id, chosen, qty_per_unit, user.id), "Saved", "uses")


@router.post("/set-up", include_in_schema=False)
async def set_up(request: Request, user: User = Depends(page_admin), db: AsyncSession = Depends(get_db)):
    return await _done(request, lambda: stock.set_up_suggested(db, user.id),
                       lambda r: f"{r[0]} materials added, {r[1]} items linked. Check them below, then count your stock.", "materials")
