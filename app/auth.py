import hashlib
import hmac
import os
import re
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_db
from app.models import BusinessProfile, UserAccount


def normalize_phone(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def validate_phone(phone: str) -> bool:
    return phone.isdigit() and len(phone) == 11


def validate_pin(pin: str) -> bool:
    return pin.isdigit() and len(pin) == 4


def validate_business_email(email: Optional[str]) -> bool:
    cleaned = str(email or "").strip()
    if cleaned == "":
        return True
    pattern = r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
    return re.fullmatch(pattern, cleaned) is not None


def _weak_pin_set() -> set[str]:
    default_weak = {
        "0000",
        "1111",
        "1234",
        "4321",
        "1212",
        "1122",
        "1004",
        "2000",
        "2580",
    }
    custom = os.getenv("PIN_WEAK_LIST", "").strip()
    if not custom:
        return default_weak
    merged = set(default_weak)
    merged.update(item.strip() for item in custom.split(",") if item.strip())
    return merged


def validate_pin_policy(pin: str) -> tuple[bool, Optional[str]]:
    if not validate_pin(pin):
        return False, "PIN must be exactly 4 digits"
    if pin in _weak_pin_set():
        return False, "Please choose a less common PIN"
    return True, None


def hash_pin(pin: str, salt_hex: Optional[str] = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    pin_hash = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 120_000)
    return pin_hash.hex(), salt.hex()


def verify_pin(pin: str, pin_hash: str, pin_salt: str) -> bool:
    computed, _ = hash_pin(pin, pin_salt)
    return hmac.compare_digest(computed, pin_hash)


def is_admin_phone(phone: str) -> bool:
    raw = os.getenv("ADMIN_PHONES", "")
    if not raw.strip():
        return False

    admin_set = {normalize_phone(item) for item in raw.split(",") if item.strip()}
    return phone in admin_set


def is_encoder_phone(phone: str) -> bool:
    raw = os.getenv("ENCODER_PHONES", "")
    if not raw.strip():
        return False

    encoder_set = {normalize_phone(item) for item in raw.split(",") if item.strip()}
    return phone in encoder_set


def resolve_role_from_phone(phone: str) -> str:
    if is_admin_phone(phone):
        return "admin"
    if is_encoder_phone(phone):
        return "encoder"
    return "customer"


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserAccount:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in")

    result = await db.execute(select(UserAccount).where(UserAccount.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in")
    return user


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[UserAccount]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    result = await db.execute(select(UserAccount).where(UserAccount.id == user_id))
    return result.scalar_one_or_none()


async def require_admin(current_user: UserAccount = Depends(get_current_user)) -> UserAccount:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access only")
    return current_user


async def is_business_owner(db: AsyncSession, user_id: int) -> bool:
    """True if this user is the registered owner (BusinessProfile.admin_user_id)."""
    result = await db.execute(
        select(BusinessProfile.id).where(BusinessProfile.admin_user_id == user_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def require_owner_or_admin(
    current_user: UserAccount = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserAccount:
    """Admin role, or the business profile owner, may access full admin APIs and records."""
    if current_user.role == "admin":
        return current_user
    if await is_business_owner(db, current_user.id):
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Business owner or admin access required",
    )


async def require_data_entry_access(current_user: UserAccount = Depends(get_current_user)) -> UserAccount:
    if current_user.role not in {"admin", "encoder"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Data entry access only")
    return current_user
