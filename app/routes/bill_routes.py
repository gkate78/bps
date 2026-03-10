from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth import (
    get_current_user_optional,
    hash_pin,
    normalize_phone,
    require_admin,
    require_data_entry_access,
    validate_phone,
    validate_pin_policy,
)
from app.controllers.bill_controller import (
    get_biller_account_digits,
    create_record,
    datatable_query,
    delete_record,
    find_latest_by_account,
    get_biller_charges,
    get_biller_late_charges,
    get_distinct_billers,
    get_record,
    has_active_biller_rule,
    import_csv_records,
    reconciliation_summary,
    update_record,
)
from app.database import get_db
from app.models import BillerRule, BusinessProfile, UserAccount

router = APIRouter(tags=["bills"])
templates = Jinja2Templates(directory="app/templates")

RECEIPT_FIELD_KEYS = (
    "reference",
    "txn_datetime",
    "account",
    "biller",
    "customer_name",
    "bill_amt",
    "amt2",
    "charge",
    "total",
    "cash",
    "change_amt",
)


def _normalize_text(value: str) -> str:
    return value.strip().upper()


class RecordCreate(BaseModel):
    txn_datetime: Optional[datetime] = None
    txn_date: Optional[date] = None
    account: str = Field(min_length=1, max_length=64)
    biller: str = Field(min_length=1, max_length=120)
    customer_name: str = Field(min_length=1, max_length=160)
    cp_number: str = ""
    bill_amt: float = 0
    amt2: float = 0
    charge: float = 0
    total: float = 0
    cash: float = 0
    change_amt: float = 0
    due_date: Optional[date] = None
    notes: Optional[str] = None
    reference: Optional[str] = None
    payment_reference: Optional[str] = None


class RecordUpdate(BaseModel):
    txn_datetime: Optional[datetime] = None
    txn_date: Optional[date] = None
    account: Optional[str] = Field(default=None, min_length=1, max_length=64)
    biller: Optional[str] = Field(default=None, min_length=1, max_length=120)
    customer_name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    cp_number: Optional[str] = None
    bill_amt: Optional[float] = None
    amt2: Optional[float] = None
    charge: Optional[float] = None
    total: Optional[float] = None
    cash: Optional[float] = None
    change_amt: Optional[float] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    reference: Optional[str] = None
    payment_reference: Optional[str] = None


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
    if current_user and current_user.role == "admin":
        profile = await _get_profile_for_admin(db, current_user.id)
        if profile:
            return profile

    result = await db.execute(select(BusinessProfile).order_by(BusinessProfile.id.asc()).limit(1))
    return result.scalar_one_or_none()


def _visible_receipt_fields(raw: Optional[str]) -> set[str]:
    if not raw:
        return set(RECEIPT_FIELD_KEYS)
    selected = {part.strip() for part in raw.split(",") if part.strip()}
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
        "show_reference": "reference" in visible,
        "show_txn_datetime": "txn_datetime" in visible,
        "show_account": "account" in visible,
        "show_biller": "biller" in visible,
        "show_customer_name": "customer_name" in visible,
        "show_bill_amt": "bill_amt" in visible,
        "show_amt2": "amt2" in visible,
        "show_charge": "charge" in visible,
        "show_total": "total" in visible,
        "show_cash": "cash" in visible,
        "show_change_amt": "change_amt" in visible,
    }


@router.get("/admin/records", response_class=HTMLResponse, include_in_schema=False)
async def admin_records_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
    ):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)
    if current_user.role != "admin":
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


@router.get("/admin/processing", response_class=HTMLResponse, include_in_schema=False)
async def admin_processing_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)
    if current_user.role != "admin":
        return RedirectResponse(url="/customer/dashboard", status_code=303)
    billers = await get_distinct_billers(db)
    return templates.TemplateResponse(
        "processing.html",
        {"request": request, "billers": billers, "current_user": current_user},
    )


@router.get("/api/admin/reconciliation-summary")
async def get_reconciliation_summary(
    summary_date: Optional[date] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    for_date = summary_date or date.today()
    return await reconciliation_summary(db, for_date)


@router.get("/admin/settings", response_class=HTMLResponse, include_in_schema=False)
async def admin_settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserAccount = Depends(require_admin),
):
    profile = await _get_profile_for_admin(db, current_user.id)
    biller_rules = await _list_biller_rules(db)
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
            "biller_rules": biller_rules,
            "error": request.query_params.get("error", "").strip(),
            "success": request.query_params.get("success", "").strip(),
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
    db: AsyncSession = Depends(get_db),
    current_user: UserAccount = Depends(require_admin),
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
            business_email=_normalize_text(business_email) or None,
            tin_number=_normalize_text(tin_number) or None,
            receipt_footer=_normalize_text(receipt_footer) or None,
            receipt_show_headings=receipt_show_headings is not None,
            receipt_visible_fields=_serialize_visible_fields(list(RECEIPT_FIELD_KEYS)),
            receipt_show_business_name=receipt_show_business_name is not None,
            receipt_show_business_address=receipt_show_business_address is not None,
            receipt_show_business_phone=receipt_show_business_phone is not None,
            receipt_show_business_email=receipt_show_business_email is not None,
            receipt_show_business_tin=receipt_show_business_tin is not None,
        )
    else:
        profile.business_name = cleaned_name
        profile.business_address = cleaned_address
        profile.business_phone = _normalize_text(business_phone) or None
        profile.business_email = _normalize_text(business_email) or None
        profile.tin_number = _normalize_text(tin_number) or None
        profile.receipt_footer = _normalize_text(receipt_footer) or None
        profile.receipt_show_headings = receipt_show_headings is not None
        profile.receipt_visible_fields = _serialize_visible_fields(list(RECEIPT_FIELD_KEYS))
        profile.receipt_show_business_name = receipt_show_business_name is not None
        profile.receipt_show_business_address = receipt_show_business_address is not None
        profile.receipt_show_business_phone = receipt_show_business_phone is not None
        profile.receipt_show_business_email = receipt_show_business_email is not None
        profile.receipt_show_business_tin = receipt_show_business_tin is not None
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
    _: UserAccount = Depends(require_admin),
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
    late_charge: float = Form(0),
    account_digits: Optional[int] = Form(None),
    is_active: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    cleaned_biller = biller.strip().upper()
    if not cleaned_biller:
        return RedirectResponse(url="/admin/settings?error=Biller+name+is+required", status_code=303)
    if service_charge < 0 or late_charge < 0:
        return RedirectResponse(url="/admin/settings?error=Charges+must+not+be+negative", status_code=303)
    if account_digits is not None and account_digits <= 0:
        return RedirectResponse(url="/admin/settings?error=Account+digits+must+be+greater+than+zero", status_code=303)

    existing = await db.execute(select(BillerRule).where(BillerRule.biller == cleaned_biller))
    rule = existing.scalar_one_or_none()
    if rule is None:
        rule = BillerRule(
            biller=cleaned_biller,
            service_charge=round(float(service_charge), 2),
            late_charge=round(float(late_charge), 2),
            account_digits=int(account_digits) if account_digits else None,
            is_active=is_active is not None,
        )
    else:
        rule.service_charge = round(float(service_charge), 2)
        rule.late_charge = round(float(late_charge), 2)
        rule.account_digits = int(account_digits) if account_digits else None
        rule.is_active = is_active is not None
        rule.updated_at = datetime.utcnow()

    db.add(rule)
    await db.commit()
    return RedirectResponse(url="/admin/settings?success=Biller+rule+saved", status_code=303)


@router.post("/admin/settings/biller-rules/{rule_id}/delete", include_in_schema=False)
async def delete_biller_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
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
    _: UserAccount = Depends(require_admin),
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
    return templates.TemplateResponse(
        "entry_form.html",
        {
            "request": request,
            "billers": billers,
            "biller_charges": await get_biller_charges(db),
            "biller_late_charges": await get_biller_late_charges(db),
            "biller_account_digits": await get_biller_account_digits(db),
            "current_user": current_user,
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
    _: UserAccount = Depends(require_admin),
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
async def list_billers(db: AsyncSession = Depends(get_db), _: UserAccount = Depends(require_admin)):
    return {"billers": await get_distinct_billers(db)}


@router.get("/api/admin/users")
async def list_users(db: AsyncSession = Depends(get_db), _: UserAccount = Depends(require_admin)):
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


@router.post("/api/admin/users")
async def upsert_user(
    payload: AdminUserCreate,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
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


@router.get("/api/records/{record_id}", response_model=RecordResponse)
async def get_record_endpoint(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
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
    _: UserAccount = Depends(require_data_entry_access),
):
    if payload.txn_datetime is None:
        payload.txn_datetime = datetime.utcnow()
    if payload.txn_date is None:
        payload.txn_date = payload.txn_datetime.date()

    if payload.due_date is None:
        raise HTTPException(status_code=400, detail="Due date is required")

    if payload.bill_amt <= 0:
        raise HTTPException(status_code=400, detail="Bill amount is required")
    if not await has_active_biller_rule(db, payload.biller):
        raise HTTPException(status_code=400, detail="Biller rule is not configured")
    required_digits = await _required_account_digits_for_biller(db, payload.biller)
    if required_digits is not None:
        account_digits = "".join(ch for ch in str(payload.account or "") if ch.isdigit())
        if len(account_digits) != required_digits:
            raise HTTPException(
                status_code=400,
                detail=f"Account must be exactly {required_digits} digits for {str(payload.biller).strip().upper()}",
            )

    record = await create_record(db, payload.model_dump())
    return record


@router.put("/api/records/{record_id}", response_model=RecordResponse)
async def update_record_endpoint(
    record_id: int,
    payload: RecordUpdate,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "due_date" in updates and updates["due_date"] is None:
        raise HTTPException(status_code=400, detail="Due date is required")
    if "biller" in updates and not await has_active_biller_rule(db, str(updates.get("biller", ""))):
        raise HTTPException(status_code=400, detail="Biller rule is not configured")
    if "account" in updates or "biller" in updates:
        biller_for_validation = str(updates.get("biller", "")).strip()
        if not biller_for_validation:
            current = await get_record(db, record_id)
            biller_for_validation = current.biller
        required_digits = await _required_account_digits_for_biller(db, biller_for_validation)
        if required_digits is not None:
            account_value = str(updates.get("account", "")).strip()
            if not account_value:
                current = await get_record(db, record_id)
                account_value = current.account
            account_digits = "".join(ch for ch in account_value if ch.isdigit())
            if len(account_digits) != required_digits:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Account must be exactly {required_digits} digits for "
                        f"{str(biller_for_validation).strip().upper()}"
                    ),
                )

    record = await update_record(db, record_id, updates)
    return record


@router.delete("/api/records/{record_id}", status_code=204)
async def delete_record_endpoint(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    await delete_record(db, record_id)
    return None


@router.post("/api/records/import-csv")
async def import_csv_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")

    file_bytes = await file.read()
    result = await import_csv_records(db, file_bytes)
    return result
