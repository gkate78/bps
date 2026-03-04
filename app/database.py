import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

DATABASE_DIR = os.getenv("DATABASE_DIR", "./")
DATABASE_FILE = os.path.join(DATABASE_DIR, "bills_admin.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_FILE}"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    from app.models import BillRecord, UserAccount  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        # Lightweight migration: add txn_datetime for existing databases.
        columns = (await conn.execute(text("PRAGMA table_info(bill_records)"))).fetchall()
        col_names = {row[1] for row in columns}
        if "txn_datetime" not in col_names:
            await conn.execute(text("ALTER TABLE bill_records ADD COLUMN txn_datetime DATETIME"))
            await conn.execute(
                text(
                    """
                    UPDATE bill_records
                    SET txn_datetime = COALESCE(created_at, txn_date || ' 00:00:00')
                    WHERE txn_datetime IS NULL
                    """
                )
            )
