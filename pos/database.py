"""
The register uses the BPS database (bills_admin.db) through BPS's engine; its tables are all `pos_*`.
Looked up at call time, so tests that point app.database at a temporary file cover the register too.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, select

from app import database as bps_db

DEFAULT_SERVICES = [
    "PRINTING", "XEROX", "SCAN", "ID PICTURE", "LAMINATION", "TARPAULIN", "INVITATIONS", "SUPPLIES", "OTHER",
]
DEFAULT_NETWORKS = ["GLOBE", "TM", "SMART", "TNT", "DITO", "GOMO"]
DEFAULT_WALLETS = [("GCASH", "GCASH"), ("MAYA", "MAYA")]


async def get_db() -> AsyncSession:
    async with bps_db.AsyncSessionLocal() as session:
        yield session


async def _add_missing_columns(conn, table: str, columns: tuple[tuple[str, str], ...]) -> set[str]:
    """create_all doesn't add new columns to existing tables; returns the columns that were added."""
    existing = {row[1] for row in (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()}
    added = set()
    for name, ddl in columns:
        if name not in existing:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            added.add(name)
    return added


async def init_db() -> None:
    """Create the register tables and seed defaults. Call after BPS's own init_db()."""
    from pos import models  # noqa: F401  (registers the tables)
    from pos.models import PosFeeBracket, PosNetwork, PosService, PosSettings, PosWallet

    async with bps_db.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await _add_missing_columns(
            conn,
            "pos_sales",
            (
                ("payment_method", "VARCHAR(10) NOT NULL DEFAULT 'cash'"),
                ("pay_wallet_id", "INTEGER"),
                ("pay_wallet_name", "VARCHAR(60)"),
                ("payment_reference", "VARCHAR(60)"),
            ),
        )
        # Job orders. Sales made before them were all paid in full at checkout.
        added = await _add_missing_columns(
            conn,
            "pos_sales",
            (
                ("checkout_paid_cents", "INTEGER NOT NULL DEFAULT 0"),
                ("amount_paid_cents", "INTEGER NOT NULL DEFAULT 0"),
                ("is_job_order", "BOOLEAN NOT NULL DEFAULT 0"),
                ("job_status", "VARCHAR(12)"),
                ("promised_date", "DATE"),
                ("completed_at", "DATETIME"),
            ),
        )
        if "checkout_paid_cents" in added:
            await conn.execute(text("UPDATE pos_sales SET checkout_paid_cents = total_cents, amount_paid_cents = total_cents"))
        await _add_missing_columns(conn, "pos_settings", (("default_starting_cash_cents", "INTEGER NOT NULL DEFAULT 0"),))

    # Seed defaults once, only into empty tables.
    async with bps_db.AsyncSessionLocal() as db:
        if (await db.execute(select(PosSettings.id).limit(1))).first() is None:
            db.add(PosSettings(id=1))
        if (await db.execute(select(PosFeeBracket.id).limit(1))).first() is None:
            db.add(PosFeeBracket(min_cents=100, max_cents=49_900, fee_cents=1_000))
            db.add(PosFeeBracket(min_cents=50_000, max_cents=99_900, fee_cents=2_000))
        if (await db.execute(select(PosService.id).limit(1))).first() is None:
            for order, name in enumerate(DEFAULT_SERVICES):
                db.add(PosService(name=name, sort_order=order))
        if (await db.execute(select(PosNetwork.id).limit(1))).first() is None:
            for order, name in enumerate(DEFAULT_NETWORKS):
                db.add(PosNetwork(name=name, sort_order=order))
        if (await db.execute(select(PosWallet.id).limit(1))).first() is None:
            for name, provider in DEFAULT_WALLETS:
                db.add(PosWallet(name=name, provider=provider))
        await db.commit()
