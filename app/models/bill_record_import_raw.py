from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class BillRecordImportRaw(SQLModel, table=True):
    __tablename__ = "bill_record_import_raw"

    id: Optional[int] = Field(default=None, primary_key=True)
    import_batch_id: str = Field(max_length=40, index=True)
    row_number: int = Field(default=0, index=True)
    source_filename: Optional[str] = Field(default=None, max_length=255)
    imported_by_user_id: Optional[int] = Field(default=None, index=True)
    ingest_status: str = Field(default="SKIPPED", max_length=16, index=True)
    ingest_note: Optional[str] = Field(default=None, max_length=255)
    raw_row_json: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
