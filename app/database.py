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
    from app.models import BillerRule, BillRecord, BusinessProfile, UserAccount  # noqa: F401

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

        # Lightweight migration: add receipt settings columns for business_profiles.
        profile_columns = (await conn.execute(text("PRAGMA table_info(business_profiles)"))).fetchall()
        profile_col_names = {row[1] for row in profile_columns}
        if "receipt_show_headings" not in profile_col_names:
            await conn.execute(
                text("ALTER TABLE business_profiles ADD COLUMN receipt_show_headings INTEGER NOT NULL DEFAULT 1")
            )
        if "receipt_visible_fields" not in profile_col_names:
            await conn.execute(
                text(
                    "ALTER TABLE business_profiles ADD COLUMN receipt_visible_fields VARCHAR(255) NOT NULL "
                    "DEFAULT 'reference,txn_datetime,account,biller,customer_name,bill_amt,amt2,charge,total,cash,change_amt'"
                )
            )
        if "receipt_show_business_name" not in profile_col_names:
            await conn.execute(
                text("ALTER TABLE business_profiles ADD COLUMN receipt_show_business_name INTEGER NOT NULL DEFAULT 1")
            )
        if "receipt_show_business_address" not in profile_col_names:
            await conn.execute(
                text("ALTER TABLE business_profiles ADD COLUMN receipt_show_business_address INTEGER NOT NULL DEFAULT 1")
            )
        if "receipt_show_business_phone" not in profile_col_names:
            await conn.execute(
                text("ALTER TABLE business_profiles ADD COLUMN receipt_show_business_phone INTEGER NOT NULL DEFAULT 1")
            )
        if "receipt_show_business_email" not in profile_col_names:
            await conn.execute(
                text("ALTER TABLE business_profiles ADD COLUMN receipt_show_business_email INTEGER NOT NULL DEFAULT 0")
            )
        if "receipt_show_business_tin" not in profile_col_names:
            await conn.execute(
                text("ALTER TABLE business_profiles ADD COLUMN receipt_show_business_tin INTEGER NOT NULL DEFAULT 0")
            )

        # Lightweight migration: add auth hardening columns for user_accounts.
        user_columns = (await conn.execute(text("PRAGMA table_info(user_accounts)"))).fetchall()
        user_col_names = {row[1] for row in user_columns}
        if "otp_code_hash" not in user_col_names:
            await conn.execute(text("ALTER TABLE user_accounts ADD COLUMN otp_code_hash VARCHAR(128)"))
        if "otp_expires_at" not in user_col_names:
            await conn.execute(text("ALTER TABLE user_accounts ADD COLUMN otp_expires_at DATETIME"))
        if "otp_attempts" not in user_col_names:
            await conn.execute(text("ALTER TABLE user_accounts ADD COLUMN otp_attempts INTEGER NOT NULL DEFAULT 0"))
        if "pin_failed_attempts" not in user_col_names:
            await conn.execute(
                text("ALTER TABLE user_accounts ADD COLUMN pin_failed_attempts INTEGER NOT NULL DEFAULT 0")
            )
        if "locked_until" not in user_col_names:
            await conn.execute(text("ALTER TABLE user_accounts ADD COLUMN locked_until DATETIME"))

        rule_columns = (await conn.execute(text("PRAGMA table_info(biller_rules)"))).fetchall()
        rule_col_names = {row[1] for row in rule_columns}
        if "account_digits" not in rule_col_names:
            await conn.execute(text("ALTER TABLE biller_rules ADD COLUMN account_digits INTEGER"))

        # Seed default biller rules when empty.
        existing_rules = (await conn.execute(text("SELECT COUNT(1) FROM biller_rules"))).scalar_one()
        if int(existing_rules or 0) == 0:
            await conn.execute(
                text(
                    """
                    INSERT INTO biller_rules (biller, service_charge, late_charge, account_digits, is_active, created_at, updated_at)
                    VALUES
                      ('MERALCO', 15, 35, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('CONVERGE', 25, 0, 13, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('PLDT FIBER', 25, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('SSS', 30, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('GLOBE AT HOME', 25, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('STA MARIA WATER', 15, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('PLDT', 25, 0, 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('SMART POSTPAID', 25, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('BPICC', 25, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('PSA', 30, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('PRIME WATER', 25, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('GLOBE POSTPAID', 25, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('EASY TRIP', 25, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('AUTO SWEEP RFID', 25, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('SUN POSTPAID', 25, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                      ('NORZAGARAY WATER DISTRICT', 25, 0, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                )
            )
        await conn.execute(
            text(
                """
                UPDATE biller_rules
                SET account_digits = 13
                WHERE UPPER(TRIM(biller)) = 'CONVERGE'
                  AND (account_digits IS NULL OR account_digits <= 0)
                """
            )
        )
        await conn.execute(
            text(
                """
                UPDATE biller_rules
                SET account_digits = 10
                WHERE UPPER(TRIM(biller)) = 'PLDT'
                  AND (account_digits IS NULL OR account_digits <= 0)
                """
            )
        )
