from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class UserAccount(SQLModel, table=True):
    __tablename__ = "user_accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    first_name: str = Field(max_length=80)
    last_name: str = Field(max_length=80)
    phone: str = Field(max_length=11, index=True, unique=True)
    pin_hash: str = Field(max_length=128)
    pin_salt: str = Field(max_length=64)
    role: str = Field(default="customer", max_length=20, index=True)
    otp_code_hash: Optional[str] = Field(default=None, max_length=128)
    otp_expires_at: Optional[datetime] = Field(default=None)
    otp_attempts: int = Field(default=0, nullable=False)
    pin_failed_attempts: int = Field(default=0, nullable=False)
    locked_until: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
