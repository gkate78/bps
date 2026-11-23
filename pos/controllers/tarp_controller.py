"""
Tarpaulin jobs: every sale with a TARPAULIN line becomes a job for the designer set in Settings → Tarpaulin.
The designer sees their own jobs and moves them through the steps; admins see all and can reassign them.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pos.auth_adapter import STAFF_ROLES, User, display_name
from pos.controllers.settings_controller import add_audit, get_settings
from pos.models import PosSale, PosSaleLine
from pos.models.tarp_job import PosTarpJob

TARP_SERVICE = "TARPAULIN"
STEPS = {
    "layout": "For layout",
    "approved": "Approved by customer",
    "sent": "Sent to print shop",
    "ready": "Ready for pickup",
    "claimed": "Claimed",
}


class TarpError(ValueError):
    pass


def clean_specs(value: Optional[str]) -> Optional[str]:
    """As typed (the wording on a tarp is case-sensitive), each line trimmed, blank lines dropped; None when empty."""
    lines = [" ".join(line.split()) for line in str(value or "").splitlines()]
    text = "\n".join(line for line in lines if line)[:1000]
    return text or None


def has_tarp(lines: list[PosSaleLine]) -> bool:
    return any(line.kind == "service" and (line.service_name or "").upper() == TARP_SERVICE for line in lines)


async def add_for_sale(db: AsyncSession, sale: PosSale, lines: list[PosSaleLine], specs: Optional[str] = None) -> Optional[PosTarpJob]:
    """Called when a sale is saved (before its commit): a sale with a tarpaulin gets a job for the designer."""
    if not has_tarp(lines):
        return None
    settings = await get_settings(db)
    job = PosTarpJob(sale_id=sale.id, designer_user_id=settings.tarp_designer_user_id, specs=clean_specs(specs),
                     created_at=sale.created_at or datetime.now())
    db.add(job)
    return job


async def staff(db: AsyncSession) -> list[User]:
    rows = await db.execute(select(User).where(User.role.in_(STAFF_ROLES)).order_by(User.first_name, User.last_name))
    return list(rows.scalars().all())


async def list_jobs(db: AsyncSession, user: User, show: str = "open", designer_id: Optional[int] = None) -> list[dict]:
    """Jobs of non-voided sales. Staff see their own; admins see all (or one designer's, or unassigned with 0)."""
    query = select(PosTarpJob, PosSale).join(PosSale, PosSale.id == PosTarpJob.sale_id).where(PosSale.status != "voided")
    if user.role != "admin":
        query = query.where(PosTarpJob.designer_user_id == user.id)
    elif designer_id == 0:
        query = query.where(PosTarpJob.designer_user_id.is_(None))
    elif designer_id:
        query = query.where(PosTarpJob.designer_user_id == designer_id)
    if show == "open":
        query = query.where(PosTarpJob.status != "claimed")
    elif show == "claimed":
        query = query.where(PosTarpJob.status == "claimed")
    pairs = (await db.execute(query.order_by(PosTarpJob.created_at.desc()).limit(500))).all()
    lines: dict[int, list[PosSaleLine]] = {}
    names: dict[int, str] = {}
    if pairs:
        sale_ids = [sale.id for _, sale in pairs]
        result = await db.execute(
            select(PosSaleLine).where(PosSaleLine.sale_id.in_(sale_ids), PosSaleLine.kind == "service").order_by(PosSaleLine.id)
        )
        for line in result.scalars().all():
            lines.setdefault(line.sale_id, []).append(line)
        ids = {job.designer_user_id for job, _ in pairs if job.designer_user_id}
        if ids:
            names = {u.id: display_name(u) for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()}
    rows = []
    for job, sale in pairs:
        sale_lines = lines.get(sale.id, [])
        tarps = [l for l in sale_lines if (l.service_name or "").upper() == TARP_SERVICE]
        rows.append({
            "job": job,
            "sale": sale,
            "tarps": ", ".join(f"{l.description or 'TARPAULIN'}{f' × {l.qty}' if l.qty > 1 else ''}" for l in tarps),
            "others": ", ".join(f"{l.service_name} {l.description or ''}".strip() for l in sale_lines if l not in tarps),
            "designer": names.get(job.designer_user_id, "") if job.designer_user_id else "",
            "late": bool(sale.promised_date and sale.promised_date < date.today() and job.status not in ("ready", "claimed")),
        })
    if show == "open":
        # Soonest promised first; jobs without a date after, oldest first.
        rows.sort(key=lambda r: (r["sale"].promised_date is None, r["sale"].promised_date or date.max, r["job"].created_at))
    return rows


async def _job_for(db: AsyncSession, job_id: int, user: User) -> tuple[PosTarpJob, PosSale]:
    row = (
        await db.execute(select(PosTarpJob, PosSale).join(PosSale, PosSale.id == PosTarpJob.sale_id).where(PosTarpJob.id == job_id))
    ).first()
    if not row:
        raise TarpError("Tarpaulin job not found")
    job, sale = row
    if user.role != "admin" and job.designer_user_id != user.id:
        raise TarpError("This job is assigned to someone else")
    if sale.status == "voided":
        raise TarpError(f"Sale {sale.sale_no} was voided")
    return job, sale


async def set_status(db: AsyncSession, job_id: int, status: str, user: User) -> PosTarpJob:
    if status not in STEPS:
        raise TarpError("Choose a step")
    job, sale = await _job_for(db, job_id, user)
    if status == "claimed" and sale.balance_cents > 0:
        raise TarpError(f"{sale.sale_no} still has a balance of ₱{sale.balance_cents / 100:,.2f}. Collect it in Job orders first.")
    before = job.status
    job.status = status
    job.updated_at = datetime.now()
    job.claimed_at = job.updated_at if status == "claimed" else None
    db.add(job)
    add_audit(db, "tarp_job", job.id, "status", user.id, {"sale_no": sale.sale_no, "from": before, "to": status})
    await db.commit()
    return job


async def set_notes(db: AsyncSession, job_id: int, notes: str, user: User) -> PosTarpJob:
    job, sale = await _job_for(db, job_id, user)
    job.notes = " ".join((notes or "").split())[:500] or None
    job.updated_at = datetime.now()
    db.add(job)
    add_audit(db, "tarp_job", job.id, "notes", user.id, {"sale_no": sale.sale_no})
    await db.commit()
    return job


async def set_specs(db: AsyncSession, job_id: int, specs: str, user: User) -> PosTarpJob:
    """The customer's specs, corrected or added later (e.g. the customer called back)."""
    job, sale = await _job_for(db, job_id, user)
    job.specs = clean_specs(specs)
    job.updated_at = datetime.now()
    db.add(job)
    add_audit(db, "tarp_job", job.id, "specs", user.id, {"sale_no": sale.sale_no})
    await db.commit()
    return job


async def assign(db: AsyncSession, job_id: int, designer_id: Optional[int], user: User) -> PosTarpJob:
    if user.role != "admin":
        raise TarpError("Only an admin can reassign a job")
    job, sale = await _job_for(db, job_id, user)
    if designer_id and designer_id not in {u.id for u in await staff(db)}:
        raise TarpError("Choose a staff member")
    job.designer_user_id = designer_id or None
    job.updated_at = datetime.now()
    db.add(job)
    add_audit(db, "tarp_job", job.id, "assign", user.id, {"sale_no": sale.sale_no, "designer_user_id": job.designer_user_id})
    await db.commit()
    return job


async def assign_unassigned(db: AsyncSession, designer_id: int, user: User) -> int:
    """When a designer is set in Settings, the open jobs no one has yet go to them (not committed here)."""
    query = (
        select(PosTarpJob).join(PosSale, PosSale.id == PosTarpJob.sale_id)
        .where(PosTarpJob.designer_user_id.is_(None), PosTarpJob.status != "claimed", PosSale.status != "voided")
    )
    jobs = (await db.execute(query)).scalars().all()
    now = datetime.now()
    for job in jobs:
        job.designer_user_id, job.updated_at = designer_id, now
        db.add(job)
    if jobs:
        add_audit(db, "tarp_job", 0, "assign_unassigned", user.id, {"designer_user_id": designer_id, "jobs": [j.id for j in jobs]})
    return len(jobs)


async def open_count(db: AsyncSession, user: User) -> int:
    from sqlalchemy import func

    query = (
        select(func.count(PosTarpJob.id)).join(PosSale, PosSale.id == PosTarpJob.sale_id)
        .where(PosSale.status != "voided", PosTarpJob.status != "claimed")
    )
    if user.role != "admin":
        query = query.where(PosTarpJob.designer_user_id == user.id)
    return (await db.execute(query)).scalar() or 0
