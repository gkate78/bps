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
    receipt_show_headings: bool = Field(default=True, nullable=False)
    receipt_visible_fields: str = Field(
        default="reference,txn_datetime,account,biller,customer_name,bill_amt,amt2,charge,total,cash,change_amt",
        max_length=255,
        nullable=False,
    )
    receipt_show_business_name: bool = Field(default=True, nullable=False)
    receipt_show_business_address: bool = Field(default=True, nullable=False)
    receipt_show_business_phone: bool = Field(default=True, nullable=False)
    receipt_show_business_email: bool = Field(default=False, nullable=False)
    receipt_show_business_tin: bool = Field(default=False, nullable=False)
    receipt_show_footer: bool = Field(default=True, nullable=False)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
