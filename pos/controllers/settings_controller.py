import json
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pos.fees import FeeSchedule
from app.models import BusinessProfile
from pos.models import PosAuditLog, PosFeeBracket, PosNetwork, PosService, PosSettings, PosWallet


async def get_settings(db: AsyncSession) -> PosSettings:
    settings = (await db.execute(select(PosSettings).where(PosSettings.id == 1))).scalar_one_or_none()
    return settings or PosSettings(id=1)


async def receipt_business(db: AsyncSession) -> dict:
    """Receipt header from the BPS business profile, with the same show/hide settings as bill receipts."""
    profile = (await db.execute(select(BusinessProfile).order_by(BusinessProfile.id).limit(1))).scalar_one_or_none()
    if not profile:
        s = await get_settings(db)
        return {"name": s.business_name, "lines": [s.business_address] if s.business_address else []}
    lines = []
    if profile.receipt_show_business_address and profile.business_address:
        lines.append(profile.business_address)
    if profile.receipt_show_business_phone and profile.business_phone:
        lines.append(profile.business_phone)
    if profile.receipt_show_business_email and profile.business_email:
        lines.append(profile.business_email)
    if profile.receipt_show_business_tin and profile.tin_number:
        lines.append(f"TIN: {profile.tin_number}")
    return {"name": profile.business_name if profile.receipt_show_business_name else "", "lines": lines}


async def get_fee_brackets(db: AsyncSession) -> list[PosFeeBracket]:
    return list((await db.execute(select(PosFeeBracket).order_by(PosFeeBracket.min_cents))).scalars().all())


async def get_fee_schedule(db: AsyncSession) -> FeeSchedule:
    s = await get_settings(db)
    brackets = await get_fee_brackets(db)
    return FeeSchedule(
        block_cents=s.fee_block_cents,
        block_fee_cents=s.fee_block_fee_cents,
        brackets=tuple((b.min_cents, b.max_cents, b.fee_cents) for b in brackets),
        load_small_max_cents=s.load_small_max_cents,
        load_small_fee_cents=s.load_small_fee_cents,
        promo_round_cents=s.promo_round_cents,
    )


async def list_services(db: AsyncSession, active_only: bool = False) -> list[PosService]:
    query = select(PosService).order_by(PosService.sort_order, PosService.name)
    if active_only:
        query = query.where(PosService.is_active)
    return list((await db.execute(query)).scalars().all())


async def list_networks(db: AsyncSession, active_only: bool = False) -> list[PosNetwork]:
    query = select(PosNetwork).order_by(PosNetwork.sort_order, PosNetwork.name)
    if active_only:
        query = query.where(PosNetwork.is_active)
    return list((await db.execute(query)).scalars().all())


async def list_wallets(db: AsyncSession, active_only: bool = False) -> list[PosWallet]:
    query = select(PosWallet).order_by(PosWallet.id)
    if active_only:
        query = query.where(PosWallet.is_active)
    return list((await db.execute(query)).scalars().all())


def add_audit(
    db: AsyncSession,
    entity: str,
    entity_id: Optional[int],
    action: str,
    user_id: Optional[int],
    detail: Optional[dict] = None,
) -> None:
    db.add(
        PosAuditLog(
            entity=entity,
            entity_id=entity_id,
            action=action,
            user_id=user_id,
            detail_json=json.dumps(detail, default=str) if detail is not None else None,
        )
    )
