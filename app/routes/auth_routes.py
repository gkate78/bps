from datetime import datetime, timedelta
from typing import Optional
import os

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth import (
    get_current_user_optional,
    hash_pin,
    is_business_owner,
    normalize_phone,
    resolve_role_from_phone,
    validate_phone,
    validate_pin_policy,
    verify_pin,
)
from app.database import get_db
from app.models import AuthEventLog, BillRecord, BusinessProfile, Customer, UserAccount
from app.services import get_otp_service

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")
OTP_MAX_ATTEMPTS = 5
PIN_MAX_FAILED_ATTEMPTS = int(os.getenv("PIN_MAX_FAILED_ATTEMPTS", "5"))
PIN_LOCKOUT_MINUTES = int(os.getenv("PIN_LOCKOUT_MINUTES", "15"))


def _normalize_text(value: str) -> str:
    return value.strip().upper()


def _normalize_business_email(value: str) -> Optional[str]:
    """Strip only; do not uppercase (emails are case-insensitive but users expect normal casing)."""
    s = (value or "").strip()
    return s or None


def _render_signup(
    request: Request,
    error: Optional[str] = None,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
):
    return templates.TemplateResponse(
        "signup.html",
        {
            "request": request,
            "error": error,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
        },
    )


def _render_signin(
    request: Request,
    error: Optional[str] = None,
    phone: str = "",
    success: Optional[str] = None,
):
    return templates.TemplateResponse(
        "signin.html",
        {
            "request": request,
            "error": error,
            "success": success,
            "phone": phone,
        },
    )


def _mask_phone(phone: str) -> str:
    if len(phone) <= 4:
        return phone
    return f"{phone[:2]}{'*' * max(0, len(phone) - 4)}{phone[-2:]}"


def _render_signup_verify(
    request: Request,
    phone: str,
    error: Optional[str] = None,
    success: Optional[str] = None,
):
    return templates.TemplateResponse(
        "signup_verify.html",
        {
            "request": request,
            "phone": phone,
            "masked_phone": _mask_phone(phone),
            "error": error,
            "success": success,
        },
    )


def _render_pin_reset_request(
    request: Request,
    error: Optional[str] = None,
    success: Optional[str] = None,
    phone: str = "",
):
    return templates.TemplateResponse(
        "pin_reset_request.html",
        {
            "request": request,
            "error": error,
            "success": success,
            "phone": phone,
        },
    )


def _render_pin_reset_verify(
    request: Request,
    phone: str,
    error: Optional[str] = None,
    success: Optional[str] = None,
):
    return templates.TemplateResponse(
        "pin_reset_verify.html",
        {
            "request": request,
            "phone": phone,
            "masked_phone": _mask_phone(phone),
            "error": error,
            "success": success,
        },
    )


def _pack_otp_hash(hash_hex: str, salt_hex: str) -> str:
    return f"{salt_hex}:{hash_hex}"


def _unpack_otp_hash(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not raw or ":" not in raw:
        return None, None
    salt_hex, hash_hex = raw.split(":", 1)
    if not salt_hex or not hash_hex:
        return None, None
    return hash_hex, salt_hex


def _render_admin_signup(
    request: Request,
    error: Optional[str] = None,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    business_name: str = "",
    business_address: str = "",
    business_phone: str = "",
    business_email: str = "",
    tin_number: str = "",
    receipt_footer: str = "",
):
    return templates.TemplateResponse(
        "admin_signup.html",
        {
            "request": request,
            "error": error,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "business_name": business_name,
            "business_address": business_address,
            "business_phone": business_phone,
            "business_email": business_email,
            "tin_number": tin_number,
            "receipt_footer": receipt_footer,
        },
    )


async def _has_admin_account(db: AsyncSession) -> bool:
    result = await db.execute(select(UserAccount.id).where(UserAccount.role == "admin").limit(1))
    return result.scalar_one_or_none() is not None


async def _log_auth_event(
    db: AsyncSession,
    *,
    event_type: str,
    status: str,
    phone: Optional[str] = None,
    user_id: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    db.add(
        AuthEventLog(
            user_id=user_id,
            phone=phone,
            event_type=event_type,
            status=status,
            detail=detail,
        )
    )
    await db.commit()


@router.get("/auth/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=303)
    if not await _has_admin_account(db):
        return RedirectResponse(url="/auth/admin/signup", status_code=303)
    return _render_signup(request)


@router.get("/auth/signup/verify", response_class=HTMLResponse, include_in_schema=False)
async def signup_verify_page(
    request: Request,
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=303)

    pending_signup = request.session.get("pending_signup")
    if not pending_signup:
        return RedirectResponse(url="/auth/signup", status_code=303)

    return _render_signup_verify(request, phone=pending_signup.get("phone", ""))


@router.get("/auth/admin/signup", response_class=HTMLResponse, include_in_schema=False)
async def admin_signup_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=303)

    if await _has_admin_account(db):
        return RedirectResponse(url="/auth/signin", status_code=303)

    return _render_admin_signup(request)


@router.post("/auth/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup_submit(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    phone: str = Form(...),
    pin: str = Form(...),
    pin_confirm: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    cleaned_first = _normalize_text(first_name)
    cleaned_last = _normalize_text(last_name)
    normalized_phone = normalize_phone(phone)

    if not cleaned_first or not cleaned_last:
        return _render_signup(request, "First name and last name are required", cleaned_first, cleaned_last, phone)
    if not validate_phone(normalized_phone):
        return _render_signup(request, "Please enter a valid phone number", cleaned_first, cleaned_last, phone)
    pin_ok, pin_error = validate_pin_policy(pin)
    if not pin_ok:
        return _render_signup(request, pin_error or "Invalid PIN", cleaned_first, cleaned_last, phone)
    if pin != pin_confirm:
        return _render_signup(request, "PIN entries do not match", cleaned_first, cleaned_last, phone)

    existing = await db.execute(select(UserAccount).where(UserAccount.phone == normalized_phone))
    if existing.scalar_one_or_none():
        return _render_signup(request, "Phone number is already registered", cleaned_first, cleaned_last, phone)

    pin_hash, pin_salt = hash_pin(pin)
    role = resolve_role_from_phone(normalized_phone)
    otp_service = get_otp_service()
    otp_code = otp_service.generate_code()
    otp_hash, otp_salt = otp_service.hash_code(otp_code)
    dispatch = otp_service.send_otp(normalized_phone, otp_code)

    request.session["pending_signup"] = {
        "first_name": cleaned_first,
        "last_name": cleaned_last,
        "phone": normalized_phone,
        "pin_hash": pin_hash,
        "pin_salt": pin_salt,
        "role": role,
        "otp_code_hash": otp_hash,
        "otp_salt": otp_salt,
        "otp_expires_at": dispatch.expires_at.isoformat(),
        "otp_attempts": 0,
    }
    return RedirectResponse(url="/auth/signup/verify", status_code=303)


@router.post("/auth/signup/verify", response_class=HTMLResponse, include_in_schema=False)
async def signup_verify_submit(
    request: Request,
    otp_code: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    pending_signup = request.session.get("pending_signup")
    if not pending_signup:
        return RedirectResponse(url="/auth/signup", status_code=303)

    now = datetime.utcnow()
    expires_raw = pending_signup.get("otp_expires_at")
    if not expires_raw:
        request.session.pop("pending_signup", None)
        return _render_signup(request, "OTP session is invalid. Please sign up again.")
    expires_at = datetime.fromisoformat(expires_raw)
    if now > expires_at:
        request.session.pop("pending_signup", None)
        return _render_signup(request, "OTP has expired. Please sign up again.")

    otp_value = "".join(ch for ch in otp_code if ch.isdigit())
    otp_service = get_otp_service()
    is_valid = otp_service.verify_code(
        otp_value,
        pending_signup.get("otp_code_hash", ""),
        pending_signup.get("otp_salt", ""),
    )
    if not is_valid:
        attempts = int(pending_signup.get("otp_attempts", 0)) + 1
        pending_signup["otp_attempts"] = attempts
        request.session["pending_signup"] = pending_signup
        if pending_signup.get("phone"):
            await _log_auth_event(
                db,
                event_type="signup_otp_verify",
                status="failed",
                phone=pending_signup.get("phone"),
                detail="invalid_otp_code",
            )
        if attempts >= OTP_MAX_ATTEMPTS:
            request.session.pop("pending_signup", None)
            if pending_signup.get("phone"):
                await _log_auth_event(
                    db,
                    event_type="signup_otp_verify",
                    status="blocked",
                    phone=pending_signup.get("phone"),
                    detail="max_attempts_reached",
                )
            return _render_signup(request, "Too many OTP attempts. Please sign up again.")
        attempts_left = OTP_MAX_ATTEMPTS - attempts
        return _render_signup_verify(
            request,
            phone=pending_signup.get("phone", ""),
            error=f"Invalid OTP code. {attempts_left} attempt(s) remaining.",
        )

    existing = await db.execute(select(UserAccount).where(UserAccount.phone == pending_signup.get("phone")))
    if existing.scalar_one_or_none():
        request.session.pop("pending_signup", None)
        return _render_signup(request, "Phone number is already registered.")

    user = UserAccount(
        first_name=pending_signup["first_name"],
        last_name=pending_signup["last_name"],
        phone=pending_signup["phone"],
        pin_hash=pending_signup["pin_hash"],
        pin_salt=pending_signup["pin_salt"],
        role=pending_signup["role"],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await _log_auth_event(
        db,
        event_type="signup_otp_verify",
        status="success",
        phone=user.phone,
        user_id=user.id,
        detail="account_activated",
    )

    request.session.pop("pending_signup", None)
    request.session["user_id"] = user.id
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/auth/signup/resend-otp", response_class=HTMLResponse, include_in_schema=False)
async def signup_resend_otp(request: Request):
    pending_signup = request.session.get("pending_signup")
    if not pending_signup:
        return RedirectResponse(url="/auth/signup", status_code=303)

    otp_service = get_otp_service()
    otp_code = otp_service.generate_code()
    otp_hash, otp_salt = otp_service.hash_code(otp_code)
    dispatch = otp_service.send_otp(pending_signup["phone"], otp_code)

    pending_signup["otp_code_hash"] = otp_hash
    pending_signup["otp_salt"] = otp_salt
    pending_signup["otp_expires_at"] = dispatch.expires_at.isoformat()
    pending_signup["otp_attempts"] = 0
    request.session["pending_signup"] = pending_signup

    return _render_signup_verify(
        request,
        phone=pending_signup["phone"],
        success="A new OTP code was sent.",
    )


@router.get("/auth/pin/reset", response_class=HTMLResponse, include_in_schema=False)
async def pin_reset_page(
    request: Request,
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return _render_pin_reset_request(request)


@router.post("/auth/pin/reset/request", response_class=HTMLResponse, include_in_schema=False)
async def pin_reset_request_submit(
    request: Request,
    phone: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    normalized_phone = normalize_phone(phone)
    if not validate_phone(normalized_phone):
        return _render_pin_reset_request(request, error="Please enter a valid phone number", phone=phone)

    result = await db.execute(select(UserAccount).where(UserAccount.phone == normalized_phone))
    user = result.scalar_one_or_none()
    if not user:
        return _render_pin_reset_request(
            request,
            success="If the phone number is registered, an OTP was sent.",
            phone=phone,
        )

    otp_service = get_otp_service()
    otp_code = otp_service.generate_code()
    otp_hash, otp_salt = otp_service.hash_code(otp_code)
    dispatch = otp_service.send_otp(normalized_phone, otp_code)

    user.otp_code_hash = _pack_otp_hash(otp_hash, otp_salt)
    user.otp_expires_at = dispatch.expires_at
    user.otp_attempts = 0
    user.updated_at = datetime.utcnow()
    db.add(user)
    await db.commit()

    request.session["pending_pin_reset_phone"] = normalized_phone
    return RedirectResponse(url="/auth/pin/reset/verify", status_code=303)


@router.get("/auth/pin/reset/verify", response_class=HTMLResponse, include_in_schema=False)
async def pin_reset_verify_page(
    request: Request,
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=303)
    phone = request.session.get("pending_pin_reset_phone")
    if not phone:
        return RedirectResponse(url="/auth/pin/reset", status_code=303)
    return _render_pin_reset_verify(request, phone=phone)


@router.post("/auth/pin/reset/verify", response_class=HTMLResponse, include_in_schema=False)
async def pin_reset_verify_submit(
    request: Request,
    otp_code: str = Form(...),
    new_pin: str = Form(...),
    new_pin_confirm: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    phone = request.session.get("pending_pin_reset_phone")
    if not phone:
        return RedirectResponse(url="/auth/pin/reset", status_code=303)

    result = await db.execute(select(UserAccount).where(UserAccount.phone == phone))
    user = result.scalar_one_or_none()
    if not user:
        request.session.pop("pending_pin_reset_phone", None)
        return _render_pin_reset_request(request, error="Reset session expired. Please try again.")

    if not user.otp_expires_at or datetime.utcnow() > user.otp_expires_at:
        user.otp_code_hash = None
        user.otp_expires_at = None
        user.otp_attempts = 0
        user.updated_at = datetime.utcnow()
        db.add(user)
        await db.commit()
        request.session.pop("pending_pin_reset_phone", None)
        await _log_auth_event(
            db,
            event_type="pin_reset_otp_verify",
            status="failed",
            phone=phone,
            user_id=user.id,
            detail="otp_expired",
        )
        return _render_pin_reset_request(request, error="OTP expired. Request a new reset code.")

    otp_hash, otp_salt = _unpack_otp_hash(user.otp_code_hash)
    if not otp_hash or not otp_salt:
        request.session.pop("pending_pin_reset_phone", None)
        await _log_auth_event(
            db,
            event_type="pin_reset_otp_verify",
            status="failed",
            phone=phone,
            user_id=user.id,
            detail="otp_state_invalid",
        )
        return _render_pin_reset_request(request, error="Reset session invalid. Request a new code.")

    otp_value = "".join(ch for ch in otp_code if ch.isdigit())
    otp_service = get_otp_service()
    if not otp_service.verify_code(otp_value, otp_hash, otp_salt):
        user.otp_attempts = int(user.otp_attempts or 0) + 1
        user.updated_at = datetime.utcnow()
        db.add(user)
        await db.commit()
        await _log_auth_event(
            db,
            event_type="pin_reset_otp_verify",
            status="failed",
            phone=phone,
            user_id=user.id,
            detail="invalid_otp_code",
        )
        if user.otp_attempts >= OTP_MAX_ATTEMPTS:
            user.otp_code_hash = None
            user.otp_expires_at = None
            user.otp_attempts = 0
            user.updated_at = datetime.utcnow()
            db.add(user)
            await db.commit()
            request.session.pop("pending_pin_reset_phone", None)
            await _log_auth_event(
                db,
                event_type="pin_reset_otp_verify",
                status="blocked",
                phone=phone,
                user_id=user.id,
                detail="max_attempts_reached",
            )
            return _render_pin_reset_request(request, error="Too many OTP attempts. Request a new code.")

        attempts_left = OTP_MAX_ATTEMPTS - user.otp_attempts
        return _render_pin_reset_verify(
            request,
            phone=phone,
            error=f"Invalid OTP code. {attempts_left} attempt(s) remaining.",
        )

    pin_ok, pin_error = validate_pin_policy(new_pin)
    if not pin_ok:
        return _render_pin_reset_verify(request, phone=phone, error=pin_error or "Invalid PIN")
    if new_pin != new_pin_confirm:
        return _render_pin_reset_verify(request, phone=phone, error="PIN entries do not match")

    pin_hash, pin_salt = hash_pin(new_pin)
    user.pin_hash = pin_hash
    user.pin_salt = pin_salt
    user.pin_failed_attempts = 0
    user.locked_until = None
    user.otp_code_hash = None
    user.otp_expires_at = None
    user.otp_attempts = 0
    user.updated_at = datetime.utcnow()
    db.add(user)
    await db.commit()
    await _log_auth_event(
        db,
        event_type="pin_reset_otp_verify",
        status="success",
        phone=phone,
        user_id=user.id,
        detail="otp_verified_and_pin_reset",
    )

    request.session.pop("pending_pin_reset_phone", None)
    return _render_signin(request, success="PIN reset successful. You can now sign in.", phone=phone)


@router.post("/auth/pin/reset/resend-otp", response_class=HTMLResponse, include_in_schema=False)
async def pin_reset_resend_otp(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    phone = request.session.get("pending_pin_reset_phone")
    if not phone:
        return RedirectResponse(url="/auth/pin/reset", status_code=303)

    result = await db.execute(select(UserAccount).where(UserAccount.phone == phone))
    user = result.scalar_one_or_none()
    if not user:
        request.session.pop("pending_pin_reset_phone", None)
        return RedirectResponse(url="/auth/pin/reset", status_code=303)

    otp_service = get_otp_service()
    otp_code = otp_service.generate_code()
    otp_hash, otp_salt = otp_service.hash_code(otp_code)
    dispatch = otp_service.send_otp(phone, otp_code)

    user.otp_code_hash = _pack_otp_hash(otp_hash, otp_salt)
    user.otp_expires_at = dispatch.expires_at
    user.otp_attempts = 0
    user.updated_at = datetime.utcnow()
    db.add(user)
    await db.commit()

    return _render_pin_reset_verify(request, phone=phone, success="A new OTP code was sent.")


@router.post("/auth/admin/signup", response_class=HTMLResponse, include_in_schema=False)
async def admin_signup_submit(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    phone: str = Form(...),
    pin: str = Form(...),
    pin_confirm: str = Form(...),
    business_name: str = Form(...),
    business_address: str = Form(...),
    business_phone: str = Form(""),
    business_email: str = Form(""),
    tin_number: str = Form(""),
    receipt_footer: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if await _has_admin_account(db):
        return RedirectResponse(url="/auth/signin", status_code=303)

    cleaned_first = _normalize_text(first_name)
    cleaned_last = _normalize_text(last_name)
    normalized_phone = normalize_phone(phone)
    cleaned_business_name = _normalize_text(business_name)
    cleaned_business_address = _normalize_text(business_address)

    if not cleaned_first or not cleaned_last:
        return _render_admin_signup(
            request, "First name and last name are required", cleaned_first, cleaned_last, phone
        )
    if not validate_phone(normalized_phone):
        return _render_admin_signup(
            request, "Please enter a valid phone number", cleaned_first, cleaned_last, phone
        )
    pin_ok, pin_error = validate_pin_policy(pin)
    if not pin_ok:
        return _render_admin_signup(request, pin_error or "Invalid PIN", cleaned_first, cleaned_last, phone)
    if pin != pin_confirm:
        return _render_admin_signup(
            request, "PIN entries do not match", cleaned_first, cleaned_last, phone
        )
    if not cleaned_business_name:
        return _render_admin_signup(
            request,
            "Business name is required",
            cleaned_first,
            cleaned_last,
            phone,
            cleaned_business_name,
            cleaned_business_address,
            business_phone,
            business_email,
            tin_number,
            receipt_footer,
        )
    if not cleaned_business_address:
        return _render_admin_signup(
            request,
            "Business address is required",
            cleaned_first,
            cleaned_last,
            phone,
            cleaned_business_name,
            cleaned_business_address,
            business_phone,
            business_email,
            tin_number,
            receipt_footer,
        )

    existing = await db.execute(select(UserAccount).where(UserAccount.phone == normalized_phone))
    if existing.scalar_one_or_none():
        return _render_admin_signup(
            request,
            "Phone number is already registered",
            cleaned_first,
            cleaned_last,
            phone,
            cleaned_business_name,
            cleaned_business_address,
            business_phone,
            business_email,
            tin_number,
            receipt_footer,
        )

    pin_hash, pin_salt = hash_pin(pin)
    user = UserAccount(
        first_name=cleaned_first,
        last_name=cleaned_last,
        phone=normalized_phone,
        pin_hash=pin_hash,
        pin_salt=pin_salt,
        role="admin",
    )
    db.add(user)
    await db.flush()

    profile = BusinessProfile(
        admin_user_id=user.id,
        business_name=cleaned_business_name,
        business_address=cleaned_business_address,
        business_phone=_normalize_text(business_phone) or None,
        business_email=_normalize_business_email(business_email),
        tin_number=_normalize_text(tin_number) or None,
        receipt_footer=_normalize_text(receipt_footer) or None,
    )
    db.add(profile)

    await db.commit()
    await db.refresh(user)

    request.session["user_id"] = user.id
    return RedirectResponse(url="/admin/settings?welcome=1", status_code=303)


@router.get("/auth/signin", response_class=HTMLResponse, include_in_schema=False)
async def signin_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=303)
    if not await _has_admin_account(db):
        return RedirectResponse(url="/auth/admin/signup", status_code=303)
    return _render_signin(request)


@router.post("/auth/signin", response_class=HTMLResponse, include_in_schema=False)
async def signin_submit(
    request: Request,
    phone: str = Form(...),
    pin: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    normalized_phone = normalize_phone(phone)
    now = datetime.utcnow()
    result = await db.execute(select(UserAccount).where(UserAccount.phone == normalized_phone))
    user = result.scalar_one_or_none()

    if not user:
        await _log_auth_event(
            db,
            event_type="signin",
            status="failed",
            phone=normalized_phone,
            detail="user_not_found",
        )
        return _render_signin(request, "Invalid phone number or PIN", phone)

    if user.locked_until and user.locked_until > now:
        remaining_minutes = max(1, int((user.locked_until - now).total_seconds() // 60))
        await _log_auth_event(
            db,
            event_type="signin",
            status="blocked",
            phone=user.phone,
            user_id=user.id,
            detail="account_locked",
        )
        return _render_signin(
            request,
            f"Account temporarily locked. Try again in about {remaining_minutes} minute(s).",
            phone,
        )

    if not verify_pin(pin, user.pin_hash, user.pin_salt):
        user.pin_failed_attempts = int(user.pin_failed_attempts or 0) + 1
        user.updated_at = now
        if user.pin_failed_attempts >= PIN_MAX_FAILED_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=PIN_LOCKOUT_MINUTES)
            user.pin_failed_attempts = 0
            db.add(user)
            await db.commit()
            await _log_auth_event(
                db,
                event_type="signin",
                status="locked",
                phone=user.phone,
                user_id=user.id,
                detail="max_failed_attempts_reached",
            )
            return _render_signin(
                request,
                f"Too many failed attempts. Account locked for {PIN_LOCKOUT_MINUTES} minute(s).",
                phone,
            )

        attempts_left = PIN_MAX_FAILED_ATTEMPTS - user.pin_failed_attempts
        db.add(user)
        await db.commit()
        await _log_auth_event(
            db,
            event_type="signin",
            status="failed",
            phone=user.phone,
            user_id=user.id,
            detail="invalid_pin",
        )
        return _render_signin(
            request,
            f"Invalid phone number or PIN. {attempts_left} attempt(s) remaining before lockout.",
            phone,
        )

    # Successful signin resets lockout counters.
    had_auth_flags = bool(user.pin_failed_attempts) or user.locked_until is not None
    user.pin_failed_attempts = 0
    user.locked_until = None

    resolved_role = user.role
    if user.role not in {"admin", "encoder"}:
        resolved_role = resolve_role_from_phone(user.phone)

    if user.role != resolved_role or had_auth_flags:
        user.role = resolved_role
        user.updated_at = now
        db.add(user)
        await db.commit()

    await _log_auth_event(
        db,
        event_type="signin",
        status="success",
        phone=user.phone,
        user_id=user.id,
        detail=f"role={resolved_role}",
    )

    request.session["user_id"] = user.id
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/auth/logout", include_in_schema=False)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/signin", status_code=303)


@router.get("/dashboard", include_in_schema=False)
async def dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)

    if current_user.role == "admin":
        return RedirectResponse(url="/admin/records", status_code=303)
    if await is_business_owner(db, current_user.id):
        return RedirectResponse(url="/admin/records", status_code=303)
    if current_user.role == "encoder":
        return RedirectResponse(url="/entry/form", status_code=303)
    return RedirectResponse(url="/customer/dashboard", status_code=303)


@router.get("/customer/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def customer_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)

    if current_user.role == "admin":
        return RedirectResponse(url="/admin/records", status_code=303)
    if await is_business_owner(db, current_user.id):
        return RedirectResponse(url="/admin/records", status_code=303)
    if current_user.role == "encoder":
        return RedirectResponse(url="/entry/form", status_code=303)

    customer_result = await db.execute(
        select(Customer)
        .where((Customer.user_id == current_user.id) | (Customer.phone == current_user.phone))
        .order_by(Customer.updated_at.desc(), Customer.id.desc())
        .limit(1)
    )
    customer_profile = customer_result.scalar_one_or_none()
    if customer_profile and customer_profile.user_id is None:
        customer_profile.user_id = current_user.id
        db.add(customer_profile)
        await db.commit()
        await db.refresh(customer_profile)

    bills = []
    if customer_profile:
        bills_result = await db.execute(
            select(BillRecord)
            .where(BillRecord.account == customer_profile.account)
            .order_by(BillRecord.txn_datetime.desc(), BillRecord.id.desc())
            .limit(300)
        )
        bills = bills_result.scalars().all()

    return templates.TemplateResponse(
        "customer_dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "customer_profile": customer_profile,
            "bills": bills,
        },
    )
