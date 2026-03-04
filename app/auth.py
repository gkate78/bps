import hashlib
import hmac
import os
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_db
from app.models import UserAccount


def normalize_phone(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def validate_phone(phone: str) -> bool:
    return 10 <= len(phone) <= 15


def validate_pin(pin: str) -> bool:
    return pin.isdigit() and len(pin) == 4


def hash_pin(pin: str, salt_hex: Optional[str] = None) -> tuple[str, str]:
    if salt_hex:
        salt = bytes.fromhex(salt_hex)
    else:
        salt = secrets.token_bytes(16)
    pin_hash = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 120000)
    return pin_hash.hex(), salt.hex()


def verify_pin(pin: str, pin_hash: str, pin_salt: str) -> bool:
    computed, _ = hash_pin(pin, pin_salt)
    return hmac.compare_digest(computed, pin_hash)


def is_admin_phone(phone: str) -> bool:
    raw = os.getenv("ADMIN_PHONES", "")
    if not raw.strip():
        return False
    admin_set = set()
    for item in raw.split(","):
        if item.strip():
            admin_set.add(normalize_phone(item.strip()))
    return phone in admin_set


def is_encoder_phone(phone: str) -> bool:
    raw = os.getenv("ENCODER_PHONES", "")
    if not raw.strip():
        return False
    encoder_set = set()
    for item in raw.split(","):
        if item.strip():
            encoder_set.add(normalize_phone(item.strip()))
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

    result = await db.execute(
        select(UserAccount).where(UserAccount.id == user_id)
    )
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

    result = await db.execute(
        select(UserAccount).where(UserAccount.id == user_id)
    )
    return result.scalar_one_or_none()


def require_admin(
    current_user: UserAccount = Depends(get_current_user),
) -> UserAccount:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access only")
    return current_user


def require_data_entry_access(
    current_user: UserAccount = Depends(get_current_user),
) -> UserAccount:
    if current_user.role not in ("admin", "encoder"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Data entry access only")
    return current_user


_auth_app = None


def _create_auth_app():
    """Lazy app creation to avoid circular import with auth_routes."""
    import os
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    from app.routes.auth_routes import router as auth_router
    _app = FastAPI(title="BPS Auth")
    _app.add_middleware(
        SessionMiddleware,
        secret_key=os.getenv("SESSION_SECRET", "dev-only-change-me"),
        same_site="lax",
    )
    _app.include_router(auth_router)
    return _app


def __getattr__(name: str):
    """Lazy-load app only when accessed (e.g. uvicorn app.auth:app)."""
    if name == "app":
        global _auth_app
        if _auth_app is None:
            _auth_app = _create_auth_app()
        return _auth_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
