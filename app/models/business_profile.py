from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class BusinessProfile(SQLModel, table=True):
    __tablename__ = "business_profiles"

    id: Optional[int] = Field(default=None, primary_key=True)
    admin_user_id: int = Field(index=True, unique=True, nullable=False)
    business_name: str = Field(max_length=160, nullable=False)
    business_address: str = Field(max_length=255, nullable=False)
    business_phone: Optional[str] = Field(default=None, max_length=40)
    business_email: Optional[str] = Field(default=None, max_length=120)
    tin_number: Optional[str] = Field(default=None, max_length=64)
    receipt_footer: Optional[str] = Field(default=None, max_length=255)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
