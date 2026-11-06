from datetime import date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pos.auth_adapter import User, display_name, get_current_user, page_user
from pos.controllers import eod_controller as eod
from pos.controllers import gsheets_controller as gsheets
from pos.controllers.sale_controller import PosError
from pos.controllers.settings_controller import list_wallets
from pos.database import get_db
from pos.templating import templates

router = APIRouter(prefix="/pos")


def _day(value: Optional[str]) -> date:
    try:
        return date.fromisoformat(value) if value else date.today()
    except ValueError:
        return date.today()


@router.get("/eod", response_class=HTMLResponse, include_in_schema=False)
async def eod_page(
    request: Request, day: Optional[str] = None, user: User = Depends(page_user), db: AsyncSession = Depends(get_db)
):
    # Encoders do today's closing count only; admins can open any day.
    report = await eod.eod_report(db, _day(day) if user.role == "admin" else date.today())
    users = {}
    for m in report.movements:
        if m.user_id not in users:
            found = await db.get(User, m.user_id)
            users[m.user_id] = display_name(found)
    return templates.TemplateResponse(
        request,
        "pos/eod.html",
        {
            "user": user,
            "active": "eod",
            "r": report,
            "movement_users": users,
            "movement_kinds": eod.MOVEMENT_KINDS,
            "wallets": await list_wallets(db, active_only=True),
            "is_today": report.day == date.today(),
        },
    )


@router.post("/api/eod/{day}")
async def save_eod(
    day: str,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    is_admin = user.role == "admin"
    if not is_admin and _day(day) != date.today():
        raise HTTPException(status_code=403, detail="Only an admin can change another day's count")
    try:
        report = await eod.save_close(db, _day(day), await request.json(), user, counts_only=not is_admin)
    except PosError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    background.add_task(gsheets.backup_after_eod, user.id)
    if not is_admin:
        return {"ok": True}  # a blind count: encoders don't see the expected cash
    return {"expected_cash_cents": report.expected_cash_cents, "difference_cents": report.difference_cents}


@router.post("/api/eod/{day}/movements")
async def add_movement(
    day: str, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    if user.role != "admin" and _day(day) != date.today():
        raise HTTPException(status_code=403, detail="Only an admin can change another day's count")
    try:
        movement = await eod.add_movement(db, _day(day), await request.json(), user)
    except PosError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": movement.id}


@router.post("/api/eod/{day}/handover")
async def hand_over_drawer(
    day: str, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """The outgoing cashier counts the drawer; the reliever's shift starts from that count."""
    try:
        handover = await eod.add_handover(db, _day(day), await request.json(), user)
    except PosError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if user.role != "admin":
        return {"ok": True}  # a blind count, as at closing
    return {
        "ok": True,
        "expected_cash_cents": handover.expected_cash_cents,
        "difference_cents": handover.counted_cash_cents - handover.expected_cash_cents,
    }


@router.post("/api/handovers/{handover_id}/void")
async def remove_handover(handover_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can remove a handover")
    try:
        await eod.remove_handover(db, handover_id, user)
    except PosError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/api/cash-movements/{movement_id}/void")
async def void_movement(movement_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can remove a cash movement")
    try:
        await eod.remove_movement(db, movement_id, user)
    except PosError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}
