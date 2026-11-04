import time
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pos.auth_adapter import User, display_name, find_admin_by_pin, get_current_user, page_user
from pos.controllers import parked_controller as parked
from pos.controllers import sale_controller as sales
from pos.controllers import suggest_controller as suggest
from pos.controllers.settings_controller import get_fee_schedule, get_settings, receipt_business, list_networks, list_services, list_wallets
from pos.database import get_db
from pos.fees import FeeError, load_cost, quote_load, quote_wallet
from pos.models import PosWallet
from pos.money import MoneyError, to_cents
from pos.schemas import BalancePaymentIn, JobStatusIn, ParkIn, SaleIn, VoidIn, WalletTxnIn
from pos.templating import templates

router = APIRouter(prefix="/pos")

# Wrong admin PINs on void, per signed-in user: (failures, blocked_until). Stops PIN guessing at the counter.
VOID_PIN_MAX_FAILURES = 5
VOID_PIN_BLOCK_SECONDS = 15 * 60
_void_pin_failures: dict[int, tuple[int, float]] = {}


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def register_page(request: Request, user: User = Depends(page_user), db: AsyncSession = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "pos/register.html",
        {
            "user": user,
            "active": "register",
            "services": await list_services(db, active_only=True),
            "networks": await list_networks(db, active_only=True),
            "wallets": await list_wallets(db, active_only=True),
        },
    )


@router.get("/api/quote/load")
async def load_quote(
    amount: str = Query(""),
    promo: bool = Query(False),
    wallet_id: Optional[int] = Query(None),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        q = quote_load(to_cents(amount, field="Load amount"), promo, await get_fee_schedule(db))
    except (MoneyError, FeeError) as exc:
        raise _bad_request(exc)
    wallet = await db.get(PosWallet, wallet_id) if wallet_id else None
    return {
        "cost_cents": load_cost(q.load_cents, wallet.load_discount_bp) if wallet else q.load_cents,
        "load_cents": q.load_cents,
        "priced_cents": q.priced_cents,
        "fee_cents": q.fee_cents,
        "total_cents": q.total_cents,
    }


@router.get("/api/quote/wallet")
async def wallet_quote(
    kind: str = Query("cash_in"),
    amount: str = Query(""),
    fee_mode: str = Query("deducted"),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        q = quote_wallet(kind, to_cents(amount), fee_mode, await get_fee_schedule(db))
    except (MoneyError, FeeError) as exc:
        raise _bad_request(exc)
    return {
        "amount_cents": q.amount_cents,
        "fee_cents": q.fee_cents,
        "collect_cents": q.collect_cents,
        "give_cents": q.give_cents,
    }


@router.get("/api/suggest/service")
async def suggest_service(
    service_id: int = Query(...),
    q: str = Query(""),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await suggest.service_descriptions(db, service_id, q)


@router.get("/api/suggest/mobile")
async def suggest_mobile(q: str = Query(""), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await suggest.mobiles(db, q)


@router.post("/api/sales")
async def create_sale(data: SaleIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        sale = await sales.create_sale(db, data, user)
    except sales.PosError as exc:
        raise _bad_request(exc)
    return {"id": sale.id, "sale_no": sale.sale_no, "change_cents": sale.change_cents, "balance_cents": sale.balance_cents}


@router.post("/api/wallet-txns")
async def create_wallet_txn(
    data: WalletTxnIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    try:
        txn = await sales.create_wallet_txn(db, data, user)
    except sales.PosError as exc:
        raise _bad_request(exc)
    return {"id": txn.id, "txn_no": txn.txn_no, "change_cents": txn.change_cents, "give_cents": txn.give_cents}


@router.get("/api/parked")
async def list_parked(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await parked.list_parked(db)


@router.post("/api/parked")
async def park(data: ParkIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        row = await parked.park(db, data, user)
    except parked.ParkError as exc:
        raise _bad_request(exc)
    return {"id": row.id, "label": row.label}


@router.post("/api/parked/{parked_id}/resume")
async def resume_parked(parked_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await parked.take(db, parked_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Already resumed or discarded (maybe on another computer)")
    return result


@router.post("/api/parked/{parked_id}/discard")
async def discard_parked(parked_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await parked.take(db, parked_id)
    return {"ok": True}


async def _approve_void(db: AsyncSession, user: User, pin: str) -> User:
    failures, blocked_until = _void_pin_failures.get(user.id, (0, 0.0))
    if blocked_until > time.time():
        raise HTTPException(status_code=429, detail="Too many wrong admin PINs. Try again in 15 minutes.")
    admin = await find_admin_by_pin(db, pin)
    if not admin:
        failures += 1
        block = time.time() + VOID_PIN_BLOCK_SECONDS if failures >= VOID_PIN_MAX_FAILURES else 0.0
        _void_pin_failures[user.id] = (0 if block else failures, block)
        raise HTTPException(status_code=400, detail="Admin PIN is not correct")
    _void_pin_failures.pop(user.id, None)
    return admin


@router.post("/api/sales/{sale_id}/void")
async def void_sale(
    sale_id: int, data: VoidIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    sale, _ = await sales.get_sale(db, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    admin = await _approve_void(db, user, data.admin_pin)
    try:
        await sales.void_record(db, sale, "sale", data.reason, admin, user)
    except sales.PosError as exc:
        raise _bad_request(exc)
    return {"ok": True}


@router.post("/api/wallet-txns/{txn_id}/void")
async def void_wallet_txn(
    txn_id: int, data: VoidIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    txn = await sales.get_wallet_txn(db, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    admin = await _approve_void(db, user, data.admin_pin)
    try:
        await sales.void_record(db, txn, "wallet_txn", data.reason, admin, user)
    except sales.PosError as exc:
        raise _bad_request(exc)
    return {"ok": True}


@router.post("/api/sales/{sale_id}/payments")
async def collect_balance(
    sale_id: int, data: BalancePaymentIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    try:
        payment = await sales.collect_balance(db, sale_id, data, user)
    except sales.PosError as exc:
        raise _bad_request(exc)
    return {
        "id": payment.id,
        "payment_no": payment.payment_no,
        "change_cents": payment.change_cents,
        "balance_cents": payment.balance_after_cents,
    }


@router.post("/api/sales/{sale_id}/job-status")
async def set_job_status(
    sale_id: int, data: JobStatusIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    try:
        await sales.set_job_status(db, sale_id, data.status, user)
    except sales.PosError as exc:
        raise _bad_request(exc)
    return {"ok": True}


@router.post("/api/payments/{payment_id}/void")
async def void_payment(
    payment_id: int, data: VoidIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    payment = await sales.get_payment(db, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    admin = await _approve_void(db, user, data.admin_pin)
    try:
        await sales.void_record(db, payment, "sale_payment", data.reason, admin, user)
    except sales.PosError as exc:
        raise _bad_request(exc)
    return {"ok": True}


async def _cashier_name(db: AsyncSession, user_id: int) -> str:
    found = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    return found.first_name if found else ""


@router.get("/receipt/sale/{sale_id}", response_class=HTMLResponse, include_in_schema=False)
async def sale_receipt(
    request: Request, sale_id: int, _: User = Depends(page_user), db: AsyncSession = Depends(get_db)
):
    sale, lines = await sales.get_sale(db, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    return templates.TemplateResponse(
        request,
        "pos/receipt_sale.html",
        {
            "sale": sale,
            "lines": lines,
            "settings": await get_settings(db),
            "business": await receipt_business(db),
            "cashier": await _cashier_name(db, sale.cashier_user_id),
        },
    )


@router.get("/receipt/wallet/{txn_id}", response_class=HTMLResponse, include_in_schema=False)
async def wallet_receipt(
    request: Request, txn_id: int, _: User = Depends(page_user), db: AsyncSession = Depends(get_db)
):
    txn = await sales.get_wallet_txn(db, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return templates.TemplateResponse(
        request,
        "pos/receipt_wallet.html",
        {"txn": txn, "settings": await get_settings(db),
            "business": await receipt_business(db), "cashier": await _cashier_name(db, txn.cashier_user_id)},
    )


@router.get("/receipt/payment/{payment_id}", response_class=HTMLResponse, include_in_schema=False)
async def payment_receipt(
    request: Request, payment_id: int, _: User = Depends(page_user), db: AsyncSession = Depends(get_db)
):
    payment = await sales.get_payment(db, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    sale, lines = await sales.get_sale(db, payment.sale_id)
    return templates.TemplateResponse(
        request,
        "pos/receipt_payment.html",
        {
            "payment": payment,
            "sale": sale,
            "lines": lines,
            "previously_paid_cents": sale.total_cents - payment.balance_after_cents - payment.amount_cents,
            "settings": await get_settings(db),
            "business": await receipt_business(db),
            "cashier": await _cashier_name(db, payment.cashier_user_id),
        },
    )


@router.get("/jobs", response_class=HTMLResponse, include_in_schema=False)
async def jobs_page(
    request: Request,
    show: str = "open",
    q: str = "",
    user: User = Depends(page_user),
    db: AsyncSession = Depends(get_db),
):
    show = show if show in ("open", "completed", "all") else "open"
    return templates.TemplateResponse(
        request,
        "pos/jobs.html",
        {
            "user": user,
            "active": "jobs",
            "rows": await sales.list_job_orders(db, show, q),
            "show": show,
            "q": q,
            "today": date.today(),
            "wallets": await list_wallets(db, active_only=True),
        },
    )


def _parse_range(start: Optional[str], end: Optional[str]) -> tuple[date, date]:
    today = date.today()
    try:
        start_d = date.fromisoformat(start) if start else today
    except ValueError:
        start_d = today
    try:
        end_d = date.fromisoformat(end) if end else start_d
    except ValueError:
        end_d = start_d
    if end_d < start_d:
        start_d, end_d = end_d, start_d
    return start_d, end_d


@router.get("/sales", response_class=HTMLResponse, include_in_schema=False)
async def sales_page(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    kind: str = "all",
    q: str = "",
    user: User = Depends(page_user),
    db: AsyncSession = Depends(get_db),
):
    start_d, end_d = _parse_range(start, end)
    kind = kind if kind in ("all", "shop", "wallet") else "all"
    rows = await sales.list_transactions(db, start_d, end_d, kind, q)
    return templates.TemplateResponse(
        request,
        "pos/sales.html",
        {"user": user, "active": "sales", "rows": rows, "start": start_d, "end": end_d, "kind": kind, "q": q},
    )


@router.get("/summary", response_class=HTMLResponse, include_in_schema=False)
async def summary_page(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user: User = Depends(page_user),
    db: AsyncSession = Depends(get_db),
):
    start_d, end_d = _parse_range(start, end)
    summary = await sales.day_summary(db, start_d, end_d)
    wallets = await list_wallets(db)
    return templates.TemplateResponse(
        request,
        "pos/summary.html",
        {"user": user, "active": "summary", "s": summary, "start": start_d, "end": end_d, "wallets": wallets},
    )

