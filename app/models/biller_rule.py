from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class BillerRule(SQLModel, table=True):
    __tablename__ = "biller_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    biller: str = Field(max_length=120, index=True, unique=True, nullable=False)
    service_charge: float = Field(default=0, nullable=False)
    late_charge: float = Field(default=0, nullable=False)
    account_digits: Optional[int] = Field(default=None, nullable=True)
    is_active: bool = Field(default=True, nullable=False, index=True)
    route_online_enabled: bool = Field(default=True, nullable=False)
    route_online_max_amount: Optional[float] = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
