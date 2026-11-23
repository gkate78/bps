"""
Sign-in and roles for the register, using BPS accounts (user_accounts, phone + PIN, BPS session).
BPS `admin` = register admin; BPS `encoder` = cashier. Customers can't use the register.
"""
from typing import Optional

from fastapi import Depends, HTTPException, status

from app.auth import get_current_user_optional as bps_current_user
from app.auth import normalize_phone as _digits_only
from app.auth import validate_phone, verify_pin
from app.models import UserAccount as User

STAFF_ROLES = {"admin", "encoder"}


class NotSignedIn(Exception):
    """Raised for page requests without a session; register_pos redirects to the BPS sign-in page."""


def normalize_phone(phone: str) -> str:
    digits = _digits_only(phone or "")
    if digits.startswith("63") and len(digits) == 12:
        digits = "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("9"):
        digits = "0" + digits
    return digits


def validate_mobile(phone: str) -> bool:
    return validate_phone(phone) and phone.startswith("09")


def display_name(user: Optional[User]) -> str:
    if not user:
        return "-"
    return f"{user.first_name} {user.last_name}".strip()


def pin_matches(user: User, pin: str) -> bool:
    """Re-check the signed-in user's own PIN before a sensitive action (voids)."""
    return bool(pin) and verify_pin(pin, user.pin_hash, user.pin_salt)


async def get_current_user(user: Optional[User] = Depends(bps_current_user)) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in")
    if user.role not in STAFF_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access only")
    return user


async def page_user(user: Optional[User] = Depends(bps_current_user)) -> User:
    if not user:
        raise NotSignedIn()
    if user.role not in STAFF_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access only")
    return user


async def page_admin(user: User = Depends(page_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access only")
    return user
