import csv
import io
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth import (
    get_current_user_optional,
    hash_pin,
    is_business_owner,
    normalize_phone,
    require_data_entry_access,
    require_owner_or_admin,
    validate_phone,
    validate_pin_policy,
)
from app.controllers.bill_controller import (
    ROUTING_URGENT_WINDOW_DAYS,
    decide_payment_channel,
    get_biller_account_digits,
    create_record,
    datatable_query,
    delete_record,
    find_latest_by_account,
    get_biller_charges,
    get_biller_late_charges,
    get_customer_by_account,
    list_customers,
    get_distinct_billers,
    get_record,
    has_active_biller_rule,
    import_csv_records,
    batch_mark_cash_and_export,
    reconciliation_report_summary,
    reconciliation_by_user_summary,
    reconciliation_summary,
    records_kpi_summary,
    update_record,
    upsert_customer_from_record,
)
from app.database import get_db
from app.models import BillerRule, BusinessProfile, RecordAuditLog, UserAccount
from app.services import get_confirmation_service

router = APIRouter(tags=["bills"])
templates = Jinja2Templates(directory="app/templates")
CUSTOMER_PAYMENT_METHODS = {"CASH", "GCASH", "MAYA", "BDO", "BPI"}
PROCESSING_PAYMENT_METHODS = {"CASH", "GCASH", "MAYA", "BAYAD", "BPI_CC", "BPI"}

DATABASE_VIEW_TABLES: dict[str, str] = {
    "bill_records": "Bill Records",
    "bill_record_import_raw": "Bill Record Import Raw",
    "customer_accounts": "Customer Accounts",
    "biller_rules": "Biller Rules",
    "record_audit_logs": "Record Audit Logs",
    "user_accounts": "User Accounts",
    "business_profiles": "Business Profiles",
    "auth_event_logs": "Auth Event Logs",
}

DATABASE_BILL_RECORDS_PRIORITY_COLUMNS = [
    "id",
    "txn_datetime",
    "updated_at",
    "payment_method",
    "confirmation_reference",
    "payment_channel",
    "payment_reference",
    "processed_by_user_id",
]

RECEIPT_FIELD_KEYS = (
    "reference",
    "txn_datetime",
    "account",
    "biller",
    "customer_name",
    "bill_amt",
    "late_charge",
    "charge",
    "total",
    "cash",
    "change_amt",
)


def _normalize_text(value: str) -> str:
    return value.strip().upper()


def _normalize_business_email(value: str) -> Optional[str]:
    s = (value or "").strip()
    return s or None


def _is_valid_cp_number(value: Optional[str]) -> bool:
    if value is None:
        return True
    cleaned = str(value).strip()
    if cleaned == "":
        return True
    return cleaned.isdigit() and len(cleaned) == 11


def _posting_eta_for_channel(payment_channel: Optional[str]) -> str:
    channel = str(payment_channel or "").strip().upper()
    if channel == "ONLINE":
        return "WITHIN 24 HOURS"
    return "WITHIN 1-2 BUSINESS DAYS"


def _normalize_payment_method_input(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip().upper().replace("-", "_")
    if normalized == "":
        return None
    if normalized in {"BPICC", "BPI CREDIT CARD"}:
        return "BPI_CC"
    return normalized


def _validate_payment_method(value: Optional[str], allowed: set[str]) -> Optional[str]:
    normalized = _normalize_payment_method_input(value)
    if normalized is None:
        return None
    if normalized not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported payment method.")
    return normalized


def _build_confirmation_message(
    *,
    customer_name: str,
    biller: str,
    total: float,
    reference: str,
    payment_channel: Optional[str],
    posting_eta: str,
) -> str:
    return (
        f"BPAY CONFIRMATION: HI {customer_name}, YOUR PAYMENT FOR {biller} "
        f"AMOUNTING TO PHP {total:,.2f} WAS RECEIVED. REF: {reference}. "
        f"ROUTE: {payment_channel or 'BRANCH_MANUAL'}. POSTING ETA: {posting_eta}."
    )


class RecordCreate(BaseModel):
    txn_datetime: Optional[datetime] = None
    txn_date: Optional[date] = None
    account: str = Field(min_length=1, max_length=64)
    biller: str = Field(min_length=1, max_length=120)
    customer_name: str = Field(min_length=1, max_length=160)
    cp_number: str = Field(default="", max_length=11)
    bill_amt: float = 0
    late_charge: float = 0
    amt2: Optional[float] = None
    charge: float = 0
    total: float = 0
    cash: float = 0
    change_amt: float = 0
    due_date: Optional[date] = None
    notes: Optional[str] = None
    reference: Optional[str] = None
    confirmation_reference: Optional[str] = None
    payment_reference: Optional[str] = None
    payment_method: Optional[str] = None
    payment_channel: Optional[str] = None


class RecordUpdate(BaseModel):
    txn_datetime: Optional[datetime] = None
    txn_date: Optional[date] = None
    account: Optional[str] = Field(default=None, min_length=1, max_length=64)
    biller: Optional[str] = Field(default=None, min_length=1, max_length=120)
    customer_name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    cp_number: Optional[str] = Field(default=None, max_length=11)
    bill_amt: Optional[float] = None
    late_charge: Optional[float] = None
    amt2: Optional[float] = None
    charge: Optional[float] = None
    total: Optional[float] = None
    cash: Optional[float] = None
    change_amt: Optional[float] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    reference: Optional[str] = None
    confirmation_reference: Optional[str] = None
    payment_reference: Optional[str] = None
    payment_method: Optional[str] = None
    payment_channel: Optional[str] = None


class RecordResponse(RecordCreate):
    id: int

    model_config = {"from_attributes": True}


class AdminUserCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=11, max_length=11)
    pin: str = Field(min_length=4, max_length=4)
    role: str = Field(min_length=1, max_length=20)


async def _get_profile_for_admin(db: AsyncSession, admin_user_id: int) -> Optional[BusinessProfile]:
    result = await db.execute(select(BusinessProfile).where(BusinessProfile.admin_user_id == admin_user_id))
    return result.scalar_one_or_none()


async def _list_biller_rules(db: AsyncSession) -> list[BillerRule]:
    result = await db.execute(select(BillerRule).order_by(BillerRule.biller.asc(), BillerRule.id.asc()))
    return result.scalars().all()


async def _required_account_digits_for_biller(db: AsyncSession, biller: str) -> Optional[int]:
    cleaned_biller = str(biller or "").strip().upper()
    if not cleaned_biller:
        return None
    result = await db.execute(
        select(BillerRule.account_digits)
        .where(BillerRule.biller == cleaned_biller)
        .where(BillerRule.is_active == True)  # noqa: E712
        .limit(1)
    )
    value = result.scalar_one_or_none()
    if value is None:
        return None
    digits = int(value)
    return digits if digits > 0 else None


async def _get_receipt_business_profile(
    db: AsyncSession, current_user: Optional[UserAccount]
) -> Optional[BusinessProfile]:
    if current_user and (
        current_user.role == "admin" or await is_business_owner(db, current_user.id)
    ):
        profile = await _get_profile_for_admin(db, current_user.id)
        if profile:
            return profile

    result = await db.execute(select(BusinessProfile).order_by(BusinessProfile.id.asc()).limit(1))
    return result.scalar_one_or_none()


def _visible_receipt_fields(raw: Optional[str]) -> set[str]:
    if not raw:
        return set(RECEIPT_FIELD_KEYS)
    selected = {part.strip() for part in raw.split(",") if part.strip()}
    if "amt2" in selected:
        selected.remove("amt2")
        selected.add("late_charge")
    return {key for key in RECEIPT_FIELD_KEYS if key in selected}


def _serialize_visible_fields(selected: list[str]) -> str:
    selected_set = set(selected or [])
    ordered = [key for key in RECEIPT_FIELD_KEYS if key in selected_set]
    if not ordered:
        ordered = list(RECEIPT_FIELD_KEYS)
    return ",".join(ordered)


def _build_receipt_settings(profile: Optional[BusinessProfile]) -> dict:
    visible = set(RECEIPT_FIELD_KEYS)
    show_headings = bool(profile.receipt_show_headings) if profile else True
    return {
        "show_headings": show_headings,
        "show_business_name": bool(profile.receipt_show_business_name) if profile else True,
        "show_business_address": bool(profile.receipt_show_business_address) if profile else True,
        "show_business_phone": bool(profile.receipt_show_business_phone) if profile else True,
        "show_business_email": bool(profile.receipt_show_business_email) if profile else False,
        "show_business_tin": bool(profile.receipt_show_business_tin) if profile else False,
        "show_footer": bool(profile.receipt_show_footer) if profile else True,
        "show_reference": "reference" in visible,
        "show_txn_datetime": "txn_datetime" in visible,
        "show_account": "account" in visible,
        "show_biller": "biller" in visible,
        "show_customer_name": "customer_name" in visible,
        "show_bill_amt": "bill_amt" in visible,
        "show_late_charge": "late_charge" in visible or "amt2" in visible,
        "show_charge": "charge" in visible,
        "show_total": "total" in visible,
        "show_cash": "cash" in visible,
        "show_change_amt": "change_amt" in visible,
    }


def _actor_name(user: Optional[UserAccount]) -> str:
    if not user:
        return "SYSTEM"
    return f"{user.first_name} {user.last_name}".strip() or user.phone


async def _log_record_audit(
    db: AsyncSession,
    *,
    action: str,
    status: str,
    current_user: Optional[UserAccount],
    channel: str = "web",
    record_id: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    db.add(
        RecordAuditLog(
            record_id=record_id,
            user_id=current_user.id if current_user else None,
            actor_name=_actor_name(current_user),
            actor_role=current_user.role if current_user else "system",
            action=action,
            channel=channel,
            status=status,
            detail=detail,
        )
    )
    await db.commit()


@router.get("/admin/records", response_class=HTMLResponse, include_in_schema=False)
async def admin_records_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
    ):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)
    if current_user.role != "admin" and not await is_business_owner(db, current_user.id):
        return RedirectResponse(url="/customer/dashboard", status_code=303)

    billers = await get_distinct_billers(db)
    return templates.TemplateResponse(
        "records.html",
        {
            "request": request,
            "billers": billers,
            "biller_charges": await get_biller_charges(db),
            "biller_late_charges": await get_biller_late_charges(db),
            "biller_account_digits": await get_biller_account_digits(db),
            "current_user": current_user,
        },
    )


@router.get("/admin/processing", include_in_schema=False)
async def admin_processing_redirect(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)
    if current_user.role != "admin" and not await is_business_owner(db, current_user.id):
        return RedirectResponse(url="/customer/dashboard", status_code=303)
    return RedirectResponse(url="/admin/reconciliation", status_code=303)


@router.get("/admin/reconciliation", response_class=HTMLResponse, include_in_schema=False)
async def admin_reconciliation_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)
    if current_user.role != "admin" and not await is_business_owner(db, current_user.id):
        return RedirectResponse(url="/customer/dashboard", status_code=303)
    return templates.TemplateResponse(
        "processing.html",
        {"request": request, "current_user": current_user},
    )


@router.get("/admin/reports", response_class=HTMLResponse, include_in_schema=False)
async def admin_reports_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)
    if current_user.role != "admin" and not await is_business_owner(db, current_user.id):
        return RedirectResponse(url="/customer/dashboard", status_code=303)
    return templates.TemplateResponse(
        "reports.html",
        {"request": request, "current_user": current_user},
    )


@router.get("/admin/database", response_class=HTMLResponse, include_in_schema=False)
async def admin_database_page(
    request: Request,
    table: Optional[str] = Query(default="bill_records"),
    limit: int = Query(default=100, ge=10, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: UserAccount = Depends(require_owner_or_admin),
):
    selected_table = table if table in DATABASE_VIEW_TABLES else "bill_records"
    column_rows = (await db.execute(text(f"PRAGMA table_info({selected_table})"))).fetchall()
    columns = [row[1] for row in column_rows]
    display_columns = list(columns)
    amount_columns: list[str] = []
    if selected_table == "bill_records":
        priority = [name for name in DATABASE_BILL_RECORDS_PRIORITY_COLUMNS if name in columns]
        remaining = [name for name in columns if name not in set(priority)]
        columns = priority + remaining
        if "updated_at" in columns and "txn_date" in columns:
            start_idx = columns.index("updated_at")
            end_idx = columns.index("txn_date")
            if start_idx <= end_idx:
                moved_block = columns[start_idx : end_idx + 1]
                columns = columns[:start_idx] + columns[end_idx + 1 :] + moved_block
        # Display-friendly compatibility:
        # show a single "late_charge" column header in place of legacy "amt2".
        if "amt2" in columns:
            display_columns = []
            for name in columns:
                if name == "amt2":
                    display_columns.append("late_charge")
                elif name == "late_charge":
                    # Avoid duplicate visual columns when both physical columns exist.
                    continue
                else:
                    display_columns.append(name)
        else:
            display_columns = list(columns)
        if "charge" in display_columns and "late_charge" in display_columns:
            charge_idx = display_columns.index("charge")
            late_idx = display_columns.index("late_charge")
            if charge_idx > late_idx:
                display_columns[charge_idx], display_columns[late_idx] = (
                    display_columns[late_idx],
                    display_columns[charge_idx],
                )
        amount_columns = ["bill_amt", "late_charge", "charge", "total", "cash", "change_amt"]
    elif selected_table == "biller_rules":
        # Hide deprecated legacy routing field from database view to avoid confusion.
        display_columns = [name for name in columns if name != "route_online_max_amount"]
    else:
        display_columns = list(columns)

    order_sql = " ORDER BY id DESC" if "id" in columns else ""
    query_sql = text(f"SELECT * FROM {selected_table}{order_sql} LIMIT :limit")
    data_rows = (await db.execute(query_sql, {"limit": limit})).fetchall()
    rows = [dict(row._mapping) for row in data_rows]
    if selected_table == "bill_records":
        for row in rows:
            if "amt2" in row:
                row["late_charge"] = row.get("amt2")

    return templates.TemplateResponse(
        "admin_database.html",
        {
            "request": request,
            "current_user": current_user,
            "table_options": DATABASE_VIEW_TABLES,
            "selected_table": selected_table,
            "limit": limit,
            "columns": display_columns,
            "amount_columns": amount_columns,
            "rows": rows,
            "row_count": len(rows),
        },
    )


@router.get("/api/admin/reconciliation-summary")
async def get_reconciliation_summary(
    summary_date: Optional[date] = Query(default=None),
    date_alias: Optional[date] = Query(default=None, alias="date"),
    cash_on_hand: Optional[float] = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    for_date = summary_date or date_alias or date.today()
    return await reconciliation_summary(db, for_date, cash_on_hand=cash_on_hand)


@router.get("/api/admin/reconciliation-by-user")
async def get_reconciliation_by_user(
    summary_date: Optional[date] = Query(default=None),
    date_alias: Optional[date] = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    for_date = summary_date or date_alias or date.today()
    result = await reconciliation_by_user_summary(db, for_date)

    ids = [item["processed_by_user_id"] for item in result["items"] if item["processed_by_user_id"] is not None]
    name_by_id: dict[int, str] = {}
    if ids:
        user_rows = (
            await db.execute(select(UserAccount).where(UserAccount.id.in_(ids)))
        ).scalars().all()
        for user in user_rows:
            full = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
            name_by_id[user.id] = full or f"USER {user.id}"

    for item in result["items"]:
        user_id = item["processed_by_user_id"]
        if user_id is None:
            item["user_label"] = "UNASSIGNED"
        else:
            item["user_label"] = name_by_id.get(user_id, f"USER {user_id}")

    return result


@router.get("/api/admin/reports/summary")
async def get_reports_summary(
    period: str = Query(default="daily"),
    reference_date: Optional[date] = Query(default=None),
    date_alias: Optional[date] = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    ref_date = reference_date or date_alias or date.today()
    return await reconciliation_report_summary(db, period=period, reference_date=ref_date)


@router.get("/api/admin/records/kpis")
async def get_records_kpis(
    biller: Optional[str] = Query(default=None),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    due_status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    return await records_kpi_summary(
        db,
        biller=biller,
        from_date=from_date,
        to_date=to_date,
        due_status=due_status,
    )


@router.get("/admin/settings", response_class=HTMLResponse, include_in_schema=False)
async def admin_settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserAccount = Depends(require_owner_or_admin),
):
    profile = await _get_profile_for_admin(db, current_user.id)
    biller_rules = await _list_biller_rules(db)
    show_welcome_guide = request.query_params.get("welcome", "").strip() == "1"
    needs_biller_setup = not any(getattr(r, "is_active", False) for r in biller_rules)
    return templates.TemplateResponse(
        "admin_settings.html",
        {
            "request": request,
            "current_user": current_user,
            "business_profile": profile,
            "receipt_show_headings": bool(profile.receipt_show_headings) if profile else True,
            "receipt_show_business_name": bool(profile.receipt_show_business_name) if profile else True,
            "receipt_show_business_address": bool(profile.receipt_show_business_address) if profile else True,
            "receipt_show_business_phone": bool(profile.receipt_show_business_phone) if profile else True,
            "receipt_show_business_email": bool(profile.receipt_show_business_email) if profile else False,
            "receipt_show_business_tin": bool(profile.receipt_show_business_tin) if profile else False,
            "receipt_show_footer": bool(profile.receipt_show_footer) if profile else True,
            "biller_rules": biller_rules,
            "error": request.query_params.get("error", "").strip(),
            "success": request.query_params.get("success", "").strip(),
            "show_welcome_guide": show_welcome_guide,
            "needs_biller_setup": needs_biller_setup,
        },
    )


@router.post("/admin/settings/business", include_in_schema=False)
async def update_business_settings(
    request: Request,
    business_name: str = Form(...),
    business_address: str = Form(...),
    business_phone: str = Form(""),
    business_email: str = Form(""),
    tin_number: str = Form(""),
    receipt_footer: str = Form(""),
    receipt_show_headings: Optional[str] = Form(None),
    receipt_show_business_name: Optional[str] = Form(None),
    receipt_show_business_address: Optional[str] = Form(None),
    receipt_show_business_phone: Optional[str] = Form(None),
    receipt_show_business_email: Optional[str] = Form(None),
    receipt_show_business_tin: Optional[str] = Form(None),
    receipt_show_footer: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserAccount = Depends(require_owner_or_admin),
):
    cleaned_name = _normalize_text(business_name)
    cleaned_address = _normalize_text(business_address)
    if not cleaned_name:
        return RedirectResponse(url="/admin/settings?error=Business+name+is+required", status_code=303)
    if not cleaned_address:
        return RedirectResponse(url="/admin/settings?error=Business+address+is+required", status_code=303)

    profile = await _get_profile_for_admin(db, current_user.id)
    if profile is None:
        profile = BusinessProfile(
            admin_user_id=current_user.id,
            business_name=cleaned_name,
            business_address=cleaned_address,
            business_phone=_normalize_text(business_phone) or None,
            business_email=_normalize_business_email(business_email),
            tin_number=_normalize_text(tin_number) or None,
            receipt_footer=_normalize_text(receipt_footer) or None,
            receipt_show_headings=True,
            receipt_visible_fields=_serialize_visible_fields(list(RECEIPT_FIELD_KEYS)),
            receipt_show_business_name=receipt_show_business_name is not None,
            receipt_show_business_address=receipt_show_business_address is not None,
            receipt_show_business_phone=receipt_show_business_phone is not None,
            receipt_show_business_email=receipt_show_business_email is not None,
            receipt_show_business_tin=receipt_show_business_tin is not None,
            receipt_show_footer=receipt_show_footer is not None,
        )
    else:
        profile.business_name = cleaned_name
        profile.business_address = cleaned_address
        profile.business_phone = _normalize_text(business_phone) or None
        profile.business_email = _normalize_business_email(business_email)
        profile.tin_number = _normalize_text(tin_number) or None
        profile.receipt_footer = _normalize_text(receipt_footer) or None
        if receipt_show_headings is not None:
            profile.receipt_show_headings = True
        profile.receipt_visible_fields = _serialize_visible_fields(list(RECEIPT_FIELD_KEYS))
        profile.receipt_show_business_name = receipt_show_business_name is not None
        profile.receipt_show_business_address = receipt_show_business_address is not None
        profile.receipt_show_business_phone = receipt_show_business_phone is not None
        profile.receipt_show_business_email = receipt_show_business_email is not None
        profile.receipt_show_business_tin = receipt_show_business_tin is not None
        profile.receipt_show_footer = receipt_show_footer is not None
        profile.updated_at = datetime.utcnow()

    db.add(profile)
    await db.commit()
    return RedirectResponse(url="/admin/settings?success=Business+details+saved", status_code=303)


@router.post("/admin/settings/encoders", include_in_schema=False)
async def create_encoder_user(
    first_name: str = Form(...),
    last_name: str = Form(...),
    phone: str = Form(...),
    pin: str = Form(...),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    cleaned_first = _normalize_text(first_name)
    cleaned_last = _normalize_text(last_name)
    normalized_phone = normalize_phone(phone)

    if not cleaned_first or not cleaned_last:
        return RedirectResponse(url="/admin/settings?error=Encoder+name+is+required", status_code=303)
    if not validate_phone(normalized_phone):
        return RedirectResponse(url="/admin/settings?error=Invalid+encoder+phone+number", status_code=303)
    pin_ok, pin_error = validate_pin_policy(pin)
    if not pin_ok:
        msg = (pin_error or "Invalid encoder PIN").replace(" ", "+")
        return RedirectResponse(url=f"/admin/settings?error={msg}", status_code=303)

    existing = await db.execute(select(UserAccount).where(UserAccount.phone == normalized_phone))
    user = existing.scalar_one_or_none()
    if user is not None:
        if user.role == "admin":
            return RedirectResponse(url="/admin/settings?error=Phone+already+belongs+to+an+admin", status_code=303)
        user.first_name = cleaned_first
        user.last_name = cleaned_last
        user.role = "encoder"
        pin_hash, pin_salt = hash_pin(pin)
        user.pin_hash = pin_hash
        user.pin_salt = pin_salt
        user.updated_at = datetime.utcnow()
    else:
        pin_hash, pin_salt = hash_pin(pin)
        user = UserAccount(
            first_name=cleaned_first,
            last_name=cleaned_last,
            phone=normalized_phone,
            pin_hash=pin_hash,
            pin_salt=pin_salt,
            role="encoder",
        )

    db.add(user)
    await db.commit()
    return RedirectResponse(url="/admin/settings?success=Encoder+saved", status_code=303)


@router.post("/admin/settings/biller-rules", include_in_schema=False)
async def upsert_biller_rule(
    biller: str = Form(...),
    service_charge: float = Form(0),
    system_charge_cash: float = Form(0),
    system_charge_gcash: float = Form(0),
    system_charge_maya: float = Form(0),
    system_charge_bayad: float = Form(0),
    system_charge_bpi_cc: float = Form(0),
    system_charge_bpi: float = Form(0),
    late_charge: float = Form(0),
    account_digits: Optional[int] = Form(None),
    is_active: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    cleaned_biller = biller.strip().upper()
    if not cleaned_biller:
        return RedirectResponse(url="/admin/settings?error=Biller+name+is+required", status_code=303)
    if (
        service_charge < 0
        or system_charge_cash < 0
        or system_charge_gcash < 0
        or system_charge_maya < 0
        or system_charge_bayad < 0
        or system_charge_bpi_cc < 0
        or system_charge_bpi < 0
        or late_charge < 0
    ):
        return RedirectResponse(url="/admin/settings?error=Charges+must+not+be+negative", status_code=303)
    if account_digits is not None and account_digits <= 0:
        return RedirectResponse(url="/admin/settings?error=Account+digits+must+be+greater+than+zero", status_code=303)
    existing = await db.execute(select(BillerRule).where(BillerRule.biller == cleaned_biller))
    rule = existing.scalar_one_or_none()
    if rule is None:
        rule = BillerRule(
            biller=cleaned_biller,
            service_charge=round(float(service_charge), 2),
            system_charge_cash=round(float(system_charge_cash), 2),
            system_charge_gcash=round(float(system_charge_gcash), 2),
            system_charge_maya=round(float(system_charge_maya), 2),
            system_charge_bayad=round(float(system_charge_bayad), 2),
            system_charge_bpi_cc=round(float(system_charge_bpi_cc), 2),
            system_charge_bpi=round(float(system_charge_bpi), 2),
            late_charge=round(float(late_charge), 2),
            account_digits=int(account_digits) if account_digits else None,
            is_active=is_active is not None,
        )
    else:
        rule.service_charge = round(float(service_charge), 2)
        rule.system_charge_cash = round(float(system_charge_cash), 2)
        rule.system_charge_gcash = round(float(system_charge_gcash), 2)
        rule.system_charge_maya = round(float(system_charge_maya), 2)
        rule.system_charge_bayad = round(float(system_charge_bayad), 2)
        rule.system_charge_bpi_cc = round(float(system_charge_bpi_cc), 2)
        rule.system_charge_bpi = round(float(system_charge_bpi), 2)
        rule.late_charge = round(float(late_charge), 2)
        rule.account_digits = int(account_digits) if account_digits else None
        rule.is_active = is_active is not None
        rule.updated_at = datetime.utcnow()

    db.add(rule)
    await db.commit()
    return RedirectResponse(url="/admin/settings?success=Biller+rule+saved", status_code=303)


@router.post("/admin/settings/biller-rules/import-csv", include_in_schema=False)
async def import_biller_rules_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return RedirectResponse(url="/admin/settings?error=Please+upload+a+CSV+file", status_code=303)

    content = (await file.read()).decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return RedirectResponse(url="/admin/settings?error=CSV+is+empty+or+invalid", status_code=303)

    created = 0
    updated = 0
    skipped = 0

    def _parse_float(value: Optional[str]) -> Optional[float]:
        raw = str(value or "").strip()
        if raw == "":
            return 0.0
        try:
            return round(float(raw), 2)
        except ValueError:
            return None

    def _parse_active(value: Optional[str]) -> bool:
        raw = str(value or "").strip().lower()
        if raw == "":
            return True
        return raw in {"1", "true", "yes", "y", "active"}

    for row in reader:
        biller = str(row.get("BILLER") or "").strip().upper()
        if not biller:
            skipped += 1
            continue

        service_charge = _parse_float(row.get("SERVICE_CHARGE"))
        system_charge_cash = _parse_float(row.get("CASH"))
        system_charge_gcash = _parse_float(row.get("GCASH"))
        system_charge_maya = _parse_float(row.get("MAYA"))
        system_charge_bayad = _parse_float(row.get("BAYAD"))
        system_charge_bpi_cc = _parse_float(row.get("BPI CREDIT CARD") or row.get("BPI_CC"))
        system_charge_bpi = _parse_float(row.get("BPI"))
        late_charge = _parse_float(row.get("LATE_CHARGE"))
        if (
            service_charge is None
            or system_charge_cash is None
            or system_charge_gcash is None
            or system_charge_maya is None
            or system_charge_bayad is None
            or system_charge_bpi_cc is None
            or system_charge_bpi is None
            or late_charge is None
            or service_charge < 0
            or system_charge_cash < 0
            or system_charge_gcash < 0
            or system_charge_maya < 0
            or system_charge_bayad < 0
            or system_charge_bpi_cc < 0
            or system_charge_bpi < 0
            or late_charge < 0
        ):
            skipped += 1
            continue

        raw_digits = str(row.get("ACCOUNT_DIGITS") or "").strip()
        account_digits: Optional[int] = None
        if raw_digits:
            if not raw_digits.isdigit() or int(raw_digits) <= 0:
                skipped += 1
                continue
            account_digits = int(raw_digits)

        is_active = _parse_active(row.get("IS_ACTIVE"))

        existing = await db.execute(select(BillerRule).where(BillerRule.biller == biller))
        rule = existing.scalar_one_or_none()
        if rule is None:
            rule = BillerRule(
                biller=biller,
                service_charge=service_charge,
                system_charge_cash=system_charge_cash,
                system_charge_gcash=system_charge_gcash,
                system_charge_maya=system_charge_maya,
                system_charge_bayad=system_charge_bayad,
                system_charge_bpi_cc=system_charge_bpi_cc,
                system_charge_bpi=system_charge_bpi,
                late_charge=late_charge,
                account_digits=account_digits,
                is_active=is_active,
            )
            created += 1
        else:
            rule.service_charge = service_charge
            rule.system_charge_cash = system_charge_cash
            rule.system_charge_gcash = system_charge_gcash
            rule.system_charge_maya = system_charge_maya
            rule.system_charge_bayad = system_charge_bayad
            rule.system_charge_bpi_cc = system_charge_bpi_cc
            rule.system_charge_bpi = system_charge_bpi
            rule.late_charge = late_charge
            rule.account_digits = account_digits
            rule.is_active = is_active
            rule.updated_at = datetime.utcnow()
            updated += 1
        db.add(rule)

    await db.commit()
    message = quote_plus(f"Biller rules import done: created={created}, updated={updated}, skipped={skipped}")
    return RedirectResponse(url=f"/admin/settings?success={message}", status_code=303)


@router.post("/admin/settings/biller-rules/{rule_id}/delete", include_in_schema=False)
async def delete_biller_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    result = await db.execute(select(BillerRule).where(BillerRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        return RedirectResponse(url="/admin/settings?error=Biller+rule+not+found", status_code=303)

    await db.delete(rule)
    await db.commit()
    return RedirectResponse(url="/admin/settings?success=Biller+rule+deleted", status_code=303)


@router.post("/admin/settings/encoders/{encoder_id}/remove", include_in_schema=False)
async def remove_encoder_role(
    encoder_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    result = await db.execute(select(UserAccount).where(UserAccount.id == encoder_id))
    user = result.scalar_one_or_none()
    if user is None:
        return RedirectResponse(url="/admin/settings?error=Encoder+not+found", status_code=303)
    if user.role == "admin":
        return RedirectResponse(url="/admin/settings?error=Cannot+remove+an+admin+role", status_code=303)

    user.role = "customer"
    user.updated_at = datetime.utcnow()
    db.add(user)
    await db.commit()
    return RedirectResponse(url="/admin/settings?success=Encoder+removed", status_code=303)


@router.get("/entry/form", response_class=HTMLResponse, include_in_schema=False)
async def entry_form_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)
    if current_user.role not in {"admin", "encoder"}:
        return RedirectResponse(url="/customer/dashboard", status_code=303)

    billers = await get_distinct_billers(db)
    show_admin_records_link = current_user.role == "admin" or await is_business_owner(
        db, current_user.id
    )
    return templates.TemplateResponse(
        "entry_form.html",
        {
            "request": request,
            "billers": billers,
            "biller_charges": await get_biller_charges(db),
            "biller_late_charges": await get_biller_late_charges(db),
            "biller_account_digits": await get_biller_account_digits(db),
            "routing_urgent_window_days": ROUTING_URGENT_WINDOW_DAYS,
            "current_user": current_user,
            "show_admin_records_link": show_admin_records_link,
        },
    )


@router.get("/api/records/datatable")
async def records_datatable(
    request: Request,
    biller: Optional[str] = Query(default=None),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    due_status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    params = request.query_params

    draw = int(params.get("draw", 1))
    start = int(params.get("start", 0))
    length = int(params.get("length", 10))

    search = params.get("search[value]", "").strip()
    order_col_index = params.get("order[0][column]", "0")
    order_dir = params.get("order[0][dir]", "asc")

    col_data_key = params.get(f"columns[{order_col_index}][data]", "txn_date")

    if length > 200:
        length = 200

    return await datatable_query(
        db,
        draw=draw,
        start=start,
        length=length,
        search=search,
        order_column=col_data_key,
        order_dir=order_dir,
        biller=biller,
        from_date=from_date,
        to_date=to_date,
        due_status=due_status,
    )


@router.get("/api/records/billers")
async def list_billers(db: AsyncSession = Depends(get_db), _: UserAccount = Depends(require_owner_or_admin)):
    return {"billers": await get_distinct_billers(db)}


@router.get("/api/admin/users")
async def list_users(db: AsyncSession = Depends(get_db), _: UserAccount = Depends(require_owner_or_admin)):
    result = await db.execute(
        select(UserAccount)
        .where(UserAccount.role.in_(["encoder", "customer"]))
        .order_by(UserAccount.created_at.desc(), UserAccount.id.desc())
    )
    users = result.scalars().all()
    return {
        "users": [
            {
                "id": u.id,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "phone": u.phone,
                "role": u.role,
                "created_at": u.created_at.isoformat() if u.created_at else "",
            }
            for u in users
        ]
    }


@router.get("/api/admin/record-audit")
async def list_record_audit_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    result = await db.execute(
        select(RecordAuditLog)
        .order_by(RecordAuditLog.created_at.desc(), RecordAuditLog.id.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return {
        "logs": [
            {
                "id": item.id,
                "record_id": item.record_id,
                "actor_name": item.actor_name or "",
                "actor_role": item.actor_role or "",
                "action": item.action,
                "channel": item.channel,
                "status": item.status,
                "detail": item.detail or "",
                "created_at": item.created_at.isoformat() if item.created_at else "",
            }
            for item in logs
        ]
    }


@router.post("/api/admin/users")
async def upsert_user(
    payload: AdminUserCreate,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    role = payload.role.strip().lower()
    if role not in {"encoder", "customer"}:
        raise HTTPException(status_code=400, detail="Role must be encoder or customer")

    phone = normalize_phone(payload.phone)
    if not validate_phone(phone):
        raise HTTPException(status_code=400, detail="Please enter a valid phone number")
    pin_ok, pin_error = validate_pin_policy(payload.pin)
    if not pin_ok:
        raise HTTPException(status_code=400, detail=pin_error or "Invalid PIN")

    first_name = _normalize_text(payload.first_name)
    last_name = _normalize_text(payload.last_name)
    if not first_name or not last_name:
        raise HTTPException(status_code=400, detail="First name and last name are required")

    existing = await db.execute(select(UserAccount).where(UserAccount.phone == phone))
    user = existing.scalar_one_or_none()
    pin_hash, pin_salt = hash_pin(payload.pin)
    if user is not None:
        if user.role == "admin":
            raise HTTPException(status_code=400, detail="Phone already belongs to an admin")
        user.first_name = first_name
        user.last_name = last_name
        user.role = role
        user.pin_hash = pin_hash
        user.pin_salt = pin_salt
        user.updated_at = datetime.utcnow()
    else:
        user = UserAccount(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            pin_hash=pin_hash,
            pin_salt=pin_salt,
            role=role,
        )

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "role": user.role,
    }


@router.get("/api/records/biller-charges")
async def list_biller_charges(
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    return {"biller_charges": await get_biller_charges(db)}


@router.get("/api/routing/decision")
async def get_routing_decision(
    biller: str = Query(..., min_length=1),
    total: float = Query(default=0),
    due_date: Optional[date] = Query(default=None),
    online_available: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    decision = await decide_payment_channel(
        db,
        biller=biller,
        total=total,
        due_date=due_date,
        online_available=online_available,
    )
    return decision


@router.get("/api/customers/lookup")
async def lookup_customer(
    account: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    """Lookup by account only (unique). Returns biller, name, phone to prefill. 404 if account does not exist."""
    customer = await get_customer_by_account(db, account)
    if not customer:
        raise HTTPException(status_code=404, detail="Account does not exist")
    return {
        "account": customer.account,
        "biller": customer.biller or "",
        "customer_name": customer.customer_name or "",
        "phone": customer.phone or "",
    }


@router.get("/api/customers")
async def list_customer_accounts(
    biller: Optional[str] = Query(default=None),
    query: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    customers = await list_customers(
        db,
        biller=biller,
        query=query,
        limit=limit,
    )
    return {
        "items": [
            {
                "account": item.account,
                "biller": item.biller or "",
                "customer_name": item.customer_name or "",
                "phone": item.phone or "",
            }
            for item in customers
        ]
    }


@router.get("/api/records/by-account/{account}")
async def lookup_by_account(
    account: str,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_data_entry_access),
):
    record = await find_latest_by_account(db, account.strip())
    if not record:
        raise HTTPException(status_code=404, detail="Account not found")

    return {
        "account": record.account,
        "biller": record.biller,
        "customer_name": record.customer_name,
        "cp_number": record.cp_number,
        "due_date": record.due_date.isoformat() if record.due_date else "",
    }


@router.post("/api/records/batch/mark-cash-export")
async def batch_mark_cash_export_endpoint(
    biller: Optional[str] = Query(default=None),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    due_status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: UserAccount = Depends(require_owner_or_admin),
):
    result = await batch_mark_cash_and_export(
        db,
        biller=biller,
        from_date=from_date,
        to_date=to_date,
        due_status=due_status,
    )
    await _log_record_audit(
        db,
        action="batch_mark_cash_export",
        status="success",
        current_user=current_user,
        channel="web",
        detail=(
            f"rows={result['row_count']}, updated={result['updated_count']}, "
            f"biller={biller or '-'}, from={from_date or '-'}, to={to_date or '-'}, due_status={due_status or '-'}"
        ),
    )
    today_tag = date.today().strftime("%Y%m%d")
    filename = f"batch_cash_export_{today_tag}.csv"
    return Response(
        content=result["csv_bytes"],
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Updated-Count": str(result["updated_count"]),
            "X-Row-Count": str(result["row_count"]),
        },
    )


@router.get("/api/records/{record_id}", response_model=RecordResponse)
async def get_record_endpoint(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_owner_or_admin),
):
    return await get_record(db, record_id)


@router.get("/api/records/{record_id}/receipt", response_class=HTMLResponse)
async def receipt_page(
    record_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserAccount = Depends(require_data_entry_access),
):
    record = await get_record(db, record_id)
    business_profile = await _get_receipt_business_profile(db, current_user)
    return templates.TemplateResponse(
        "receipt.html",
        {
            "request": request,
            "record": record,
            "business_profile": business_profile,
            "receipt_settings": _build_receipt_settings(business_profile),
        },
    )


@router.post("/api/records", response_model=RecordResponse, status_code=201)
async def create_record_endpoint(
    payload: RecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserAccount = Depends(require_data_entry_access),
):
    payload.payment_method = _validate_payment_method(payload.payment_method, CUSTOMER_PAYMENT_METHODS)

    if payload.txn_datetime is None:
        payload.txn_datetime = datetime.now()
    if payload.txn_date is None:
        payload.txn_date = payload.txn_datetime.date()

    if payload.due_date is None:
        raise HTTPException(status_code=400, detail="Due date is required")

    if payload.bill_amt <= 0:
        raise HTTPException(status_code=400, detail="Bill amount is required")
    if not _is_valid_cp_number(payload.cp_number):
        raise HTTPException(status_code=400, detail="CP number must be exactly 11 digits")

    initial_payload = payload.model_dump()
    if initial_payload.get("late_charge") in (None, 0) and initial_payload.get("amt2") is not None:
        initial_payload["late_charge"] = initial_payload.get("amt2")
    initial_payload.pop("amt2", None)
    initial_payload["processed_by_user_id"] = current_user.id
    record = await create_record(db, initial_payload)
    await upsert_customer_from_record(
        db,
        account=record.account,
        biller=record.biller,
        customer_name=record.customer_name,
        phone=record.cp_number or "",
    )
    await _log_record_audit(
        db,
        action="create",
        status="success",
        current_user=current_user,
        channel="web",
        record_id=record.id,
        detail=(
            f"reference={record.reference or '-'}, "
            f"payment_channel={record.payment_channel or '-'}"
        ),
    )
    if _is_valid_cp_number(record.cp_number):
        eta = _posting_eta_for_channel(record.payment_channel)
        message = _build_confirmation_message(
            customer_name=record.customer_name or "CUSTOMER",
            biller=record.biller or "-",
            total=float(record.total or 0),
            reference=record.reference or "-",
            payment_channel=record.payment_channel,
            posting_eta=eta,
        )
        try:
            dispatch = get_confirmation_service().send_confirmation(
                phone=record.cp_number,
                message=message,
                preferred_channel="sms",
            )
            await _log_record_audit(
                db,
                action="notify_customer",
                status="success",
                current_user=current_user,
                channel=dispatch.channel,
                record_id=record.id,
                detail=(
                    f"provider={dispatch.provider}, message_id={dispatch.message_id}, "
                    f"posting_eta={eta}, phone={record.cp_number}"
                ),
            )
        except Exception as exc:  # pragma: no cover - best effort notification
            await _log_record_audit(
                db,
                action="notify_customer",
                status="failed",
                current_user=current_user,
                channel="sms",
                record_id=record.id,
                detail=str(exc),
            )
    else:
        await _log_record_audit(
            db,
            action="notify_customer",
            status="skipped",
            current_user=current_user,
            channel="sms",
            record_id=record.id,
            detail="cp_number_missing_or_invalid",
        )
    return record


@router.put("/api/records/{record_id}", response_model=RecordResponse)
async def update_record_endpoint(
    record_id: int,
    payload: RecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserAccount = Depends(require_owner_or_admin),
):
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "due_date" in updates and updates["due_date"] is None:
        raise HTTPException(status_code=400, detail="Due date is required")
    if "cp_number" in updates and not _is_valid_cp_number(updates.get("cp_number")):
        raise HTTPException(status_code=400, detail="CP number must be exactly 11 digits")
    if "payment_method" in updates:
        updates["payment_method"] = _validate_payment_method(
            updates.get("payment_method"), PROCESSING_PAYMENT_METHODS
        )
    if "amt2" in updates and "late_charge" not in updates:
        updates["late_charge"] = updates.get("amt2")
    updates.pop("amt2", None)
    updates["processed_by_user_id"] = current_user.id

    record = await update_record(db, record_id, updates)
    await upsert_customer_from_record(
        db,
        account=record.account,
        biller=record.biller,
        customer_name=record.customer_name,
        phone=record.cp_number or "",
    )
    await _log_record_audit(
        db,
        action="update",
        status="success",
        current_user=current_user,
        channel="web",
        record_id=record_id,
        detail=(
            f"reference={record.reference or '-'}, "
            f"payment_channel={record.payment_channel or '-'}"
        ),
    )
    return record


@router.delete("/api/records/{record_id}", status_code=204)
async def delete_record_endpoint(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserAccount = Depends(require_owner_or_admin),
):
    try:
        record = await get_record(db, record_id)
        reference = record.reference or "-"
        await delete_record(db, record_id)
        await _log_record_audit(
            db,
            action="delete",
            status="success",
            current_user=current_user,
            channel="api",
            record_id=record_id,
            detail=f"reference={reference}",
        )
        return None
    except HTTPException as exc:
        await _log_record_audit(
            db,
            action="delete",
            status="failed",
            current_user=current_user,
            channel="api",
            record_id=record_id,
            detail=str(exc.detail),
        )
        raise


@router.post("/api/records/import-csv")
async def import_csv_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: UserAccount = Depends(require_owner_or_admin),
):
    try:
        if not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Please upload a CSV file")

        file_bytes = await file.read()
        result = await import_csv_records(
            db,
            file_bytes,
            processed_by_user_id=current_user.id,
            source_filename=file.filename,
        )
        await _log_record_audit(
            db,
            action="import_csv",
            status="success",
            current_user=current_user,
            channel="csv_upload",
            detail=(
                f"created={result.get('created', 0)}, "
                f"duplicates={result.get('duplicates', 0)}, "
                f"skipped={result.get('skipped', 0)}, "
                f"raw_logged={result.get('raw_logged', 0)}, "
                f"batch={result.get('import_batch_id', '')}"
            ),
        )
        return result
    except HTTPException as exc:
        await _log_record_audit(
            db,
            action="import_csv",
            status="failed",
            current_user=current_user,
            channel="csv_upload",
            detail=str(exc.detail),
        )
        raise
