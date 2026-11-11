"""Unsaved register work kept on the server (see PosDraft): one copy per cashier and kind."""
import json
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from pos.auth_adapter import User
from pos.controllers.parked_controller import MAX_DATA_CHARS, ParkError, _clip
from pos.models import PosDraft
from pos.schemas import ParkIn


async def list_drafts(db: AsyncSession, user: User) -> list[dict]:
    rows = (await db.execute(select(PosDraft).where(PosDraft.user_id == user.id).order_by(PosDraft.id))).scalars().all()
    return [
        {"kind": r.kind, "label": r.label, "summary": r.summary, "total_cents": r.total_cents,
         "data": json.loads(r.data_json), "at": r.updated_at.isoformat(timespec="seconds")}
        for r in rows
    ]


async def keep(db: AsyncSession, data: ParkIn, user: User) -> None:
    payload = json.dumps(data.data, separators=(",", ":"))
    if len(payload) > MAX_DATA_CHARS:
        raise ParkError("This transaction is too large to keep")
    row = (
        await db.execute(select(PosDraft).where(PosDraft.user_id == user.id, PosDraft.kind == data.kind))
    ).scalars().first()
    if row is None:
        row = PosDraft(user_id=user.id, kind=data.kind, data_json=payload)
        db.add(row)
    row.label = _clip(data.label, 160).upper()
    row.summary = _clip(data.summary, 300)
    row.total_cents = max(int(data.total_cents or 0), 0)
    row.data_json = payload
    row.updated_at = datetime.now()
    await db.commit()


async def clear(db: AsyncSession, user: User, kind: str) -> None:
    await db.execute(delete(PosDraft).where(PosDraft.user_id == user.id, PosDraft.kind == kind))
    await db.commit()
