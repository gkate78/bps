from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth import (
    get_current_user_optional,
    hash_pin,
    normalize_phone,
    resolve_role_from_phone,
    validate_phone,
    validate_pin,
    verify_pin,
)
from app.database import get_db
from app.models import UserAccount

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


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


def _render_signin(request: Request, error: Optional[str] = None, phone: str = ""):
    return templates.TemplateResponse(
        "signin.html",
        {
            "request": request,
            "error": error,
            "phone": phone,
        },
    )


@router.get("/auth/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup_page(request: Request, current_user: Optional[UserAccount] = Depends(get_current_user_optional)):
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return _render_signup(request)


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
    cleaned_first = first_name.strip()
    cleaned_last = last_name.strip()
    normalized_phone = normalize_phone(phone)

    if not cleaned_first or not cleaned_last:
        return _render_signup(request, "First name and last name are required", cleaned_first, cleaned_last, phone)
    if not validate_phone(normalized_phone):
        return _render_signup(request, "Please enter a valid phone number", cleaned_first, cleaned_last, phone)
    if not validate_pin(pin):
        return _render_signup(request, "PIN must be exactly 4 digits", cleaned_first, cleaned_last, phone)
    if pin != pin_confirm:
        return _render_signup(request, "PIN entries do not match", cleaned_first, cleaned_last, phone)

    existing = await db.execute(select(UserAccount).where(UserAccount.phone == normalized_phone))
    if existing.scalar_one_or_none():
        return _render_signup(request, "Phone number is already registered", cleaned_first, cleaned_last, phone)

    pin_hash, pin_salt = hash_pin(pin)
    role = resolve_role_from_phone(normalized_phone)

    user = UserAccount(
        first_name=cleaned_first,
        last_name=cleaned_last,
        phone=normalized_phone,
        pin_hash=pin_hash,
        pin_salt=pin_salt,
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    request.session["user_id"] = user.id
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/auth/signin", response_class=HTMLResponse, include_in_schema=False)
async def signin_page(request: Request, current_user: Optional[UserAccount] = Depends(get_current_user_optional)):
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return _render_signin(request)


@router.post("/auth/signin", response_class=HTMLResponse, include_in_schema=False)
async def signin_submit(
    request: Request,
    phone: str = Form(...),
    pin: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    normalized_phone = normalize_phone(phone)
    result = await db.execute(select(UserAccount).where(UserAccount.phone == normalized_phone))
    user = result.scalar_one_or_none()

    if not user or not verify_pin(pin, user.pin_hash, user.pin_salt):
        return _render_signin(request, "Invalid phone number or PIN", phone)

    resolved_role = resolve_role_from_phone(user.phone)
    if user.role != resolved_role:
        user.role = resolved_role
        user.updated_at = datetime.utcnow()
        db.add(user)
        await db.commit()

    request.session["user_id"] = user.id
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/auth/logout", include_in_schema=False)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/signin", status_code=303)


@router.get("/dashboard", include_in_schema=False)
async def dashboard(current_user: Optional[UserAccount] = Depends(get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)

    if current_user.role == "admin":
        return RedirectResponse(url="/admin/records", status_code=303)
    if current_user.role == "encoder":
        return RedirectResponse(url="/entry/form", status_code=303)
    return RedirectResponse(url="/customer/dashboard", status_code=303)


@router.get("/customer/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def customer_dashboard(
    request: Request,
    current_user: Optional[UserAccount] = Depends(get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/auth/signin", status_code=303)

    if current_user.role == "admin":
        return RedirectResponse(url="/admin/records", status_code=303)
    if current_user.role == "encoder":
        return RedirectResponse(url="/entry/form", status_code=303)

    return templates.TemplateResponse(
        "customer_dashboard.html",
        {
            "request": request,
            "current_user": current_user,
        },
    )
