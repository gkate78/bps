from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from pos.auth_adapter import User, page_admin
from pos.controllers import gsheets_controller as gsheets
from pos.controllers import tarp_controller as tarp
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
from pos.models import PosFeeBracket, PosNetwork, PosService, PosServiceItem, PosWallet
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


async def _gsheets_password(db: AsyncSession) -> str:
    """The Apps Script needs the password before there's a link, so make one the first time Settings opens."""
    s = await get_settings(db)
    if not s.gsheets_password:
        s.gsheets_password = gsheets.new_password()
        db.add(s)
        await db.commit()
    return s.gsheets_password


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
            "service_items": await _service_items(db),
            "networks": await list_networks(db),
            "wallets": await list_wallets(db),
            "staff": await tarp.staff(db),
            "gsheets_script": gsheets.script_text(await _gsheets_password(db)),
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


@router.post("/tarpaulin", include_in_schema=False)
async def save_tarpaulin(
    request: Request,
    cost_sqft: str = Form(""),
    small_below_sqft: str = Form(""),
    small_price: str = Form(""),
    small_cost: str = Form(""),
    designer: str = Form(""),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    """Tarpaulin printing cost a sq ft, and small tarps' price and cost (DEC-079)."""
    try:
        cost = to_cents(cost_sqft or "0", field="Printing cost a sq ft")
        price = to_cents(small_price or "0", field="Small tarp price")
        small = to_cents(small_cost or "0", field="Small tarp cost")
        below = float(small_below_sqft or 0)
    except MoneyError as exc:
        return _back(request, error=str(exc), anchor="tarpaulin")
    except ValueError:
        return _back(request, error="Small size must be a number of sq ft (e.g. 6 for 2x3)", anchor="tarpaulin")
    if min(cost, price, small) < 0 or not 0 <= below <= 1000:
        return _back(request, error="Use 0 or more", anchor="tarpaulin")
    designer_id = int(designer) if designer.isdigit() else None
    if designer_id and designer_id not in {u.id for u in await tarp.staff(db)}:
        return _back(request, error="Choose a staff member as the designer", anchor="tarpaulin")
    s = await get_settings(db)
    s.tarp_cost_sqft_cents, s.tarp_small_below_sqft, s.tarp_small_price_cents, s.tarp_small_cost_cents = cost, below, price, small
    s.tarp_designer_user_id = designer_id
    db.add(s)
    # Open jobs no one has yet go to the designer too.
    handed = await tarp.assign_unassigned(db, designer_id, user) if designer_id else 0
    add_audit(db, "settings", 1, "update_tarpaulin", user.id,
              {"cost_sqft_cents": cost, "small_below_sqft": below, "small_price_cents": price, "small_cost_cents": small,
               "designer_user_id": designer_id})
    await db.commit()
    note = f"; {handed} unassigned design job{'' if handed == 1 else 's'} given to the designer" if handed else ""
    return _back(request, message=f"Tarpaulin saved{note}", anchor="tarpaulin")


@router.post("/gsheets", include_in_schema=False)
async def save_gsheets(
    request: Request,
    url: str = Form(""),
    after_eod: str = Form(""),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    url = url.strip()
    if url and not gsheets.valid_url(url):
        return _back(request, error=f"The link should start with {gsheets.URL_PREFIX} and end with /exec", anchor="gsheets")
    s = await get_settings(db)
    s.gsheets_url = url or None
    s.gsheets_after_eod = bool(after_eod)
    db.add(s)
    add_audit(db, "settings", 1, "update_gsheets", user.id, {"url_set": bool(url), "after_eod": s.gsheets_after_eod})
    await db.commit()
    return _back(request, message="Saved", anchor="gsheets")


@router.post("/gsheets/backup", include_in_schema=False)
async def gsheets_backup(request: Request, user: User = Depends(page_admin)):
    try:
        message = await gsheets.run_backup("button", user.id)
    except gsheets.BackupError as exc:
        return _back(request, error=str(exc), anchor="gsheets")
    return _back(request, message=message, anchor="gsheets")


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


@router.post("/wallets/discounts", include_in_schema=False)
async def save_wallet_discounts(request: Request, user: User = Depends(page_admin), db: AsyncSession = Depends(get_db)):
    form = await request.form()
    changes = {}
    for wallet in await list_wallets(db):
        raw = str(form.get(f"discount_{wallet.id}", "")).strip() or "0"
        try:
            bp = round(float(raw) * 100)
        except ValueError:
            bp = -1
        if not 0 <= bp < 5_000:
            return _back(request, error=f"{wallet.name} discount must be a percent from 0 to 49.99", anchor="wallets")
        if bp != wallet.load_discount_bp:
            changes[wallet.name] = {"from": wallet.load_discount_bp, "to": bp}
            wallet.load_discount_bp = bp
            db.add(wallet)
    if changes:
        add_audit(db, "wallet", None, "load_discount", user.id, changes)
    await db.commit()
    return _back(request, message="Discounts saved", anchor="wallets")


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


# ---------- Service pick lists (DEC-075). Declared before the /{list_name} routes, which would match first. ----------

async def _service_items(db: AsyncSession) -> dict[int, list[PosServiceItem]]:
    items: dict[int, list[PosServiceItem]] = {}
    rows = await db.execute(select(PosServiceItem).order_by(PosServiceItem.sort_order, PosServiceItem.name))
    for item in rows.scalars().all():
        items.setdefault(item.service_id, []).append(item)
    return items


def _item_name(value: str) -> str:
    return (clean_text(value, 120) or "").upper()


@router.post("/service-items/add", include_in_schema=False)
async def add_service_item(
    request: Request,
    service_id: int = Form(...),
    name: str = Form(""),
    price: str = Form(""),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    service = (await db.execute(select(PosService).where(PosService.id == service_id))).scalar_one_or_none()
    cleaned = _item_name(name)
    if not service or not cleaned:
        return _back(request, error="Choose a service and type the item", anchor="service-items")
    try:
        price_cents = to_cents(price or "0", field="Price")
    except MoneyError as exc:
        return _back(request, error=str(exc), anchor="service-items")
    taken = await db.execute(
        select(PosServiceItem.id).where(PosServiceItem.service_id == service_id, PosServiceItem.name == cleaned)
    )
    if taken.first():
        return _back(request, error=f"{service.name} already has {cleaned}", anchor="service-items")
    last = (await db.execute(
        select(PosServiceItem.sort_order).where(PosServiceItem.service_id == service_id)
        .order_by(PosServiceItem.sort_order.desc()).limit(1)
    )).scalar_one_or_none()
    item = PosServiceItem(service_id=service_id, name=cleaned, price_cents=price_cents, sort_order=(last or 0) + 1)
    db.add(item)
    await db.flush()
    add_audit(db, "service_item", item.id, "create", user.id, {"service": service.name, "name": cleaned, "price_cents": price_cents})
    await db.commit()
    return _back(request, message=f"{service.name}: {cleaned} added", anchor="service-items")


@router.post("/service-items/{item_id}/save", include_in_schema=False)
async def save_service_item(
    request: Request,
    item_id: int,
    name: str = Form(""),
    price: str = Form(""),
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    """Past sales keep the description they were sold with; new sales use the new name and price."""
    item = (await db.execute(select(PosServiceItem).where(PosServiceItem.id == item_id))).scalar_one_or_none()
    cleaned = _item_name(name)
    if not item or not cleaned:
        return _back(request, error="Type the item", anchor="service-items")
    try:
        price_cents = to_cents(price or "0", field="Price")
    except MoneyError as exc:
        return _back(request, error=str(exc), anchor="service-items")
    if cleaned != item.name:
        taken = await db.execute(
            select(PosServiceItem.id).where(PosServiceItem.service_id == item.service_id, PosServiceItem.name == cleaned)
        )
        if taken.first():
            return _back(request, error=f"{cleaned} is already in this list", anchor="service-items")
    before = {"name": item.name, "price_cents": item.price_cents}
    item.name, item.price_cents = cleaned, price_cents
    db.add(item)
    add_audit(db, "service_item", item.id, "update", user.id, {"from": before, "to": {"name": cleaned, "price_cents": price_cents}})
    await db.commit()
    return _back(request, message=f"{cleaned} saved", anchor="service-items")


@router.post("/service-items/{item_id}/toggle", include_in_schema=False)
async def toggle_service_item(
    request: Request,
    item_id: int,
    user: User = Depends(page_admin),
    db: AsyncSession = Depends(get_db),
):
    item = (await db.execute(select(PosServiceItem).where(PosServiceItem.id == item_id))).scalar_one_or_none()
    if not item:
        return _back(request, error="Not found", anchor="service-items")
    item.is_active = not item.is_active
    db.add(item)
    add_audit(db, "service_item", item.id, "enable" if item.is_active else "disable", user.id)
    await db.commit()
    return _back(request, message=f"{item.name} {'shown' if item.is_active else 'hidden'}", anchor="service-items")


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
