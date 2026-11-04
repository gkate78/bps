"""Parked transactions: the register screen put on hold so another customer can be served first."""
import json
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pos.auth_adapter import User, display_name
from pos.models import PosParkedTxn
from pos.schemas import ParkIn

MAX_DATA_CHARS = 50_000


class ParkError(ValueError):
    pass


def _clip(text: str, length: int) -> str:
    return " ".join((text or "").split())[:length]


async def list_parked(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(PosParkedTxn).order_by(PosParkedTxn.parked_at, PosParkedTxn.id))).scalars().all()
    names = {}
    user_ids = {r.parked_by_user_id for r in rows if r.parked_by_user_id}
    if user_ids:
        users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        names = {u.id: display_name(u) for u in users}
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "label": r.label,
            "summary": r.summary,
            "total_cents": r.total_cents,
            "parked_at": r.parked_at.isoformat(timespec="seconds"),
            "parked_by": names.get(r.parked_by_user_id, ""),
        }
        for r in rows
    ]


async def park(db: AsyncSession, data: ParkIn, user: User) -> PosParkedTxn:
    payload = json.dumps(data.data, separators=(",", ":"))
    if len(payload) > MAX_DATA_CHARS:
        raise ParkError("This transaction is too large to park")
    row = PosParkedTxn(
        kind=data.kind,
        label=_clip(data.label, 160).upper() or "WALK-IN",
        summary=_clip(data.summary, 300),
        total_cents=max(int(data.total_cents or 0), 0),
        data_json=payload,
        parked_by_user_id=user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def take(db: AsyncSession, parked_id: int) -> Optional[dict]:
    """Remove a parked transaction and return it to put back on the screen; None if it's already gone."""
    row = await db.get(PosParkedTxn, parked_id)
    if row is None:
        return None
    result = {"id": row.id, "kind": row.kind, "label": row.label, "data": json.loads(row.data_json)}
    await db.delete(row)
    await db.commit()
    return result
