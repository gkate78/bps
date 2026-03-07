import hashlib
import hmac
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


@dataclass
class OTPDispatchResult:
    expires_at: datetime
    delivery_channel: str
    # Only populated by local/dev provider for easier manual testing.
    debug_code: str | None = None


class OTPService(Protocol):
    def generate_code(self) -> str:
        ...

    def hash_code(self, code: str) -> tuple[str, str]:
        ...

    def verify_code(self, code: str, code_hash: str, salt_hex: str) -> bool:
        ...

    def send_otp(self, phone: str, code: str) -> OTPDispatchResult:
        ...


class LocalOTPService:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds

    def generate_code(self) -> str:
        return f"{random.randint(0, 999999):06d}"

    def hash_code(self, code: str) -> tuple[str, str]:
        salt = os.urandom(16)
        code_hash = hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, 120_000)
        return code_hash.hex(), salt.hex()

    def verify_code(self, code: str, code_hash: str, salt_hex: str) -> bool:
        salt = bytes.fromhex(salt_hex)
        computed = hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, 120_000).hex()
        return hmac.compare_digest(computed, code_hash)

    def send_otp(self, phone: str, code: str) -> OTPDispatchResult:
        expires_at = datetime.utcnow() + timedelta(seconds=self.ttl_seconds)
        print(f"[LOCAL_OTP] phone={phone} code={code} expires_at={expires_at.isoformat()}")
        return OTPDispatchResult(
            expires_at=expires_at,
            delivery_channel="local",
            debug_code=code,
        )


def get_otp_service() -> OTPService:
    provider = os.getenv("OTP_PROVIDER", "local").strip().lower()
    ttl_seconds = int(os.getenv("OTP_TTL_SECONDS", "300"))
    # Keep provider-agnostic contract; add real providers here later.
    if provider == "local":
        return LocalOTPService(ttl_seconds=ttl_seconds)
    return LocalOTPService(ttl_seconds=ttl_seconds)
