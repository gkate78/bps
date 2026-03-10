from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class RecordAuditLog(SQLModel, table=True):
    __tablename__ = "record_audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    record_id: Optional[int] = Field(default=None, index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user_accounts.id", index=True)
    actor_name: Optional[str] = Field(default=None, max_length=160)
    actor_role: Optional[str] = Field(default=None, max_length=20, index=True)
    action: str = Field(max_length=32, index=True)
    channel: str = Field(max_length=32, index=True)
    status: str = Field(max_length=20, index=True)
    detail: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
