from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class PosAuditLog(SQLModel, table=True):
    __tablename__ = "pos_audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    entity: str = Field(max_length=40, index=True)
    entity_id: Optional[int] = Field(default=None, index=True)
    action: str = Field(max_length=40)
    detail_json: Optional[str] = Field(default=None)
    user_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.now, index=True, nullable=False)
