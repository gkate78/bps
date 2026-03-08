from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class AuthEventLog(SQLModel, table=True):
    __tablename__ = "auth_event_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user_accounts.id", index=True)
    phone: Optional[str] = Field(default=None, max_length=20, index=True)
    event_type: str = Field(max_length=64, index=True)
    status: str = Field(max_length=32, index=True)
    detail: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
