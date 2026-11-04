from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from pos.auth_adapter import User, page_admin
from pos.controllers.sale_controller import clean_text
from pos.controllers.settings_controller import (
    add_audit,
    get_fee_brackets,
    get_settings,
    list_networks,
    list_services,
    list_wallets,
)
from pos.database import get_db
from pos.fees import FeeError, FeeSchedule, validate_schedule
from pos.models import PosFeeBracket, PosNetwork, PosService, PosWallet
from pos.money import MoneyError, to_cents
from pos.templating import templates

router = APIRouter(prefix="/pos/settings")

# Simple add/enable/disable lists that share one set of routes.
LISTS = {
    "services": (PosService, 60, "Service"),
    "networks": (PosNetwork, 40, "Network"),
}


def _back(request: Request, message: str = "", error: str = "", anchor: str = "") -> RedirectResponse:
    request.session["pos_flash"] = {"message": message, "error": error}
    return RedirectResponse(url=f"/pos/settings{'#' + anchor if anchor else ''}", status_code=303)


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def settings_page(request: Request, user: User = Depends(page_admin), db: AsyncSession = Depends(get_db)):
    flash = request.session.pop("pos_flash", None) or {}
    return templates.TemplateResponse(
        request,
        "pos/settings.html",
        {
            "user": user,
            "active": "settings",
            "settings": await get_settings(db),
            "brackets": await get_fee_brackets(db),
            "services": await list_services(db),
            "networks": await list_networks(db),
            "wallets": await list_wallets(db),
            "message": flash.get("message"),
            "error": flash.get("error"),
        },
    )


@router.post("/business", include_in_schema=False)
async def save_business(
    request: Request,
    receipt_footer: str = Form(""),
    default_starting_cash: str = Form(""),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    """Business name, address, phone and TIN come from BPS Admin Settings; only register settings here."""
    try:
        starting = to_cents(default_starting_cash or "0", field="Starting cash")
    except MoneyError as exc:
        return _back(request, error=str(exc), anchor="business")
    s = await get_settings(db)
    s.receipt_footer = clean_text(receipt_footer, 255) or ""
    s.default_starting_cash_cents = starting
    db.add(s)
    add_audit(db, "settings", 1, "update_register", user.id)
    await db.commit()
    return _back(request, message="Saved", anchor="business")


@router.post("/fees", include_in_schema=False)
async def save_fees(request: Request, user: User = Depends(page_admin), db: AsyncSession = Depends(get_db)):
    form = await request.form()
    try:
        block = to_cents(form.get("block"), field="Block size")
        block_fee = to_cents(form.get("block_fee"), field="Fee per block")
        small_max = to_cents(form.get("small_max"), field="Small load limit")
        small_fee = to_cents(form.get("small_fee"), field="Small load fee")
        promo_round = to_cents(form.get("promo_round"), field="Promo rounding")
        brackets = []
        for low, high, fee in zip(form.getlist("b_min"), form.getlist("b_max"), form.getlist("b_fee")):
            if not str(low).strip() and not str(high).strip() and not str(fee).strip():
                continue
            brackets.append(
                (to_cents(low, field="Bracket from"), to_cents(high, field="Bracket to"), to_cents(fee, field="Bracket fee"))
            )
        if promo_round <= 0:
            raise FeeError("Promo rounding must be more than zero")
        validate_schedule(FeeSchedule(block_cents=block, block_fee_cents=block_fee, brackets=tuple(brackets)))
    except (MoneyError, FeeError) as exc:
        return _back(request, error=str(exc), anchor="fees")

    s = await get_settings(db)
    s.fee_block_cents, s.fee_block_fee_cents = block, block_fee
    s.load_small_max_cents, s.load_small_fee_cents, s.promo_round_cents = small_max, small_fee, promo_round
    db.add(s)
    await db.execute(delete(PosFeeBracket))
    for low, high, fee in sorted(brackets):
        db.add(PosFeeBracket(min_cents=low, max_cents=high, fee_cents=fee))
    add_audit(db, "settings", 1, "update_fees", user.id, {"block": block, "block_fee": block_fee, "brackets": brackets})
    await db.commit()
    return _back(request, message="Fees saved", anchor="fees")


@router.post("/wallets", include_in_schema=False)
async def add_wallet(
    request: Request,
    name: str = Form(""),
    provider: str = Form(""),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    cleaned = clean_text(name, 60)
    if not cleaned or provider not in ("GCASH", "MAYA"):
        return _back(request, error="Enter a name and choose GCash or Maya", anchor="wallets")
    if (await db.execute(select(PosWallet.id).where(PosWallet.name == cleaned))).first():
        return _back(request, error=f"{cleaned} already exists", anchor="wallets")
    wallet = PosWallet(name=cleaned, provider=provider)
    db.add(wallet)
    await db.flush()
    add_audit(db, "wallet", wallet.id, "create", user.id, {"name": cleaned})
    await db.commit()
    return _back(request, message=f"{cleaned} added", anchor="wallets")


@router.post("/wallets/{item_id}/toggle", include_in_schema=False)
async def toggle_wallet(
    request: Request, item_id: int, user: User = Depends(page_admin), db: AsyncSession = Depends(get_db)
):
    wallet = (await db.execute(select(PosWallet).where(PosWallet.id == item_id))).scalar_one_or_none()
    if not wallet:
        return _back(request, error="Not found", anchor="wallets")
    wallet.is_active = not wallet.is_active
    db.add(wallet)
    add_audit(db, "wallet", wallet.id, "enable" if wallet.is_active else "disable", user.id)
    await db.commit()
    return _back(request, message=f"{wallet.name} {'enabled' if wallet.is_active else 'hidden'}", anchor="wallets")


@router.post("/{list_name}", include_in_schema=False)
async def add_list_item(
    request: Request,
    list_name: str,
    name: str = Form(""),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    if list_name not in LISTS:
        return _back(request, error="Unknown list")
    model, max_len, label = LISTS[list_name]
    cleaned = clean_text(name, max_len)
    if not cleaned:
        return _back(request, error=f"Enter a {label.lower()} name", anchor=list_name)
    if (await db.execute(select(model.id).where(model.name == cleaned))).first():
        return _back(request, error=f"{cleaned} already exists", anchor=list_name)
    last = (await db.execute(select(model.sort_order).order_by(model.sort_order.desc()).limit(1))).scalar_one_or_none()
    item = model(name=cleaned, sort_order=(last or 0) + 1)
    db.add(item)
    await db.flush()
    add_audit(db, list_name, item.id, "create", user.id, {"name": cleaned})
    await db.commit()
    return _back(request, message=f"{cleaned} added", anchor=list_name)


@router.post("/{list_name}/{item_id}/rename", include_in_schema=False)
async def rename_list_item(
    request: Request,
    list_name: str,
    item_id: int,
    name: str = Form(""),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    """Past sales keep the name they were sold under; only new sales use the new name."""
    if list_name not in LISTS:
        return _back(request, error="Unknown list")
    model, max_len, label = LISTS[list_name]
    item = (await db.execute(select(model).where(model.id == item_id))).scalar_one_or_none()
    cleaned = clean_text(name, max_len)
    if not item or not cleaned:
        return _back(request, error=f"Enter a {label.lower()} name", anchor=list_name)
    if cleaned != item.name and (await db.execute(select(model.id).where(model.name == cleaned))).first():
        return _back(request, error=f"{cleaned} already exists", anchor=list_name)
    old = item.name
    item.name = cleaned
    db.add(item)
    add_audit(db, list_name, item.id, "rename", user.id, {"from": old, "to": cleaned})
    await db.commit()
    return _back(request, message=f"{old} renamed to {cleaned}", anchor=list_name)


@router.post("/{list_name}/{item_id}/toggle", include_in_schema=False)
async def toggle_list_item(
    request: Request,
    list_name: str,
    item_id: int,
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    if list_name not in LISTS:
        return _back(request, error="Unknown list")
    model = LISTS[list_name][0]
    item = (await db.execute(select(model).where(model.id == item_id))).scalar_one_or_none()
    if not item:
        return _back(request, error="Not found", anchor=list_name)
    item.is_active = not item.is_active
    db.add(item)
    add_audit(db, list_name, item.id, "enable" if item.is_active else "disable", user.id)
    await db.commit()
    return _back(request, message=f"{item.name} {'shown' if item.is_active else 'hidden'}", anchor=list_name)
