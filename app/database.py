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
    from app.models import BillerRule, BillRecord, BusinessProfile, Customer, RecordAuditLog, UserAccount  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        # Enforce unique account on customer_accounts: dedupe (keep one per account) then add index.
        await conn.execute(
            text(
                "DELETE FROM customer_accounts WHERE id NOT IN ("
                "SELECT MAX(id) FROM customer_accounts GROUP BY account)"
            )
        )
        await conn.execute(
            text("DROP INDEX IF EXISTS uq_customer_account_biller")
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_account "
                "ON customer_accounts(account)"
            )
        )
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
        if "payment_reference" not in col_names:
            await conn.execute(text("ALTER TABLE bill_records ADD COLUMN payment_reference VARCHAR(120)"))
        if "confirmation_reference" not in col_names:
            await conn.execute(text("ALTER TABLE bill_records ADD COLUMN confirmation_reference VARCHAR(120)"))
        if "payment_channel" not in col_names:
            await conn.execute(text("ALTER TABLE bill_records ADD COLUMN payment_channel VARCHAR(32)"))
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_bill_records_payment_channel ON bill_records(payment_channel)")
            )
        if "processed_by_user_id" not in col_names:
            await conn.execute(text("ALTER TABLE bill_records ADD COLUMN processed_by_user_id INTEGER"))
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_bill_records_processed_by_user_id ON bill_records(processed_by_user_id)")
            )
        if "late_charge" not in col_names:
            await conn.execute(text("ALTER TABLE bill_records ADD COLUMN late_charge FLOAT NOT NULL DEFAULT 0"))
            if "amt2" in col_names:
                await conn.execute(text("UPDATE bill_records SET late_charge = COALESCE(amt2, 0)"))
        elif "amt2" in col_names:
            await conn.execute(text("UPDATE bill_records SET late_charge = COALESCE(late_charge, amt2, 0)"))
            await conn.execute(text("UPDATE bill_records SET amt2 = COALESCE(amt2, late_charge, 0)"))

        # Lightweight migration: add per-method system charges for biller rules.
        biller_columns = (await conn.execute(text("PRAGMA table_info(biller_rules)"))).fetchall()
        biller_col_names = {row[1] for row in biller_columns}
        if "system_charge_cash" not in biller_col_names:
            await conn.execute(text("ALTER TABLE biller_rules ADD COLUMN system_charge_cash FLOAT NOT NULL DEFAULT 0"))
        if "system_charge_gcash" not in biller_col_names:
            await conn.execute(text("ALTER TABLE biller_rules ADD COLUMN system_charge_gcash FLOAT NOT NULL DEFAULT 0"))
        if "system_charge_maya" not in biller_col_names:
            await conn.execute(text("ALTER TABLE biller_rules ADD COLUMN system_charge_maya FLOAT NOT NULL DEFAULT 0"))
        if "system_charge_bayad" not in biller_col_names:
            await conn.execute(text("ALTER TABLE biller_rules ADD COLUMN system_charge_bayad FLOAT NOT NULL DEFAULT 0"))
        if "system_charge_bpi_cc" not in biller_col_names:
            await conn.execute(text("ALTER TABLE biller_rules ADD COLUMN system_charge_bpi_cc FLOAT NOT NULL DEFAULT 0"))
        if "system_charge_bpi" not in biller_col_names:
            await conn.execute(text("ALTER TABLE biller_rules ADD COLUMN system_charge_bpi FLOAT NOT NULL DEFAULT 0"))

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
                    "DEFAULT 'reference,txn_datetime,account,biller,customer_name,bill_amt,late_charge,charge,total,cash,change_amt'"
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
        if "receipt_show_footer" not in profile_col_names:
            await conn.execute(
                text("ALTER TABLE business_profiles ADD COLUMN receipt_show_footer INTEGER NOT NULL DEFAULT 1")
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

        # Data normalization: keep form text fields uppercase in existing rows.
        await conn.execute(
            text(
                """
                UPDATE user_accounts
                SET
                    first_name = UPPER(TRIM(first_name)),
                    last_name = UPPER(TRIM(last_name))
                """
            )
        )
        await conn.execute(
            text(
                """
                UPDATE business_profiles
                SET
                    business_name = UPPER(TRIM(business_name)),
                    business_address = UPPER(TRIM(business_address)),
                    business_phone = CASE WHEN business_phone IS NULL THEN NULL ELSE UPPER(TRIM(business_phone)) END,
                    business_email = CASE WHEN business_email IS NULL THEN NULL ELSE UPPER(TRIM(business_email)) END,
                    tin_number = CASE WHEN tin_number IS NULL THEN NULL ELSE UPPER(TRIM(tin_number)) END,
                    receipt_footer = CASE WHEN receipt_footer IS NULL THEN NULL ELSE UPPER(TRIM(receipt_footer)) END
                """
            )
        )
        await conn.execute(
            text(
                """
                UPDATE bill_records
                SET
                    account = UPPER(TRIM(account)),
                    biller = UPPER(TRIM(biller)),
                    customer_name = UPPER(TRIM(customer_name)),
                    cp_number = UPPER(TRIM(cp_number)),
                    notes = CASE WHEN notes IS NULL THEN NULL ELSE UPPER(TRIM(notes)) END,
                    reference = CASE WHEN reference IS NULL THEN NULL ELSE UPPER(TRIM(reference)) END
                """
            )
        )

        # Data normalization: keep form text fields uppercase in existing rows.
        await conn.execute(
            text(
                """
                UPDATE user_accounts
                SET
                    first_name = UPPER(TRIM(first_name)),
                    last_name = UPPER(TRIM(last_name))
                """
            )
        )
        await conn.execute(
            text(
                """
                UPDATE business_profiles
                SET
                    business_name = UPPER(TRIM(business_name)),
                    business_address = UPPER(TRIM(business_address)),
                    business_phone = CASE WHEN business_phone IS NULL THEN NULL ELSE UPPER(TRIM(business_phone)) END,
                    business_email = CASE WHEN business_email IS NULL THEN NULL ELSE UPPER(TRIM(business_email)) END,
                    tin_number = CASE WHEN tin_number IS NULL THEN NULL ELSE UPPER(TRIM(tin_number)) END,
                    receipt_footer = CASE WHEN receipt_footer IS NULL THEN NULL ELSE UPPER(TRIM(receipt_footer)) END
                """
            )
        )
        await conn.execute(
            text(
                """
                UPDATE bill_records
                SET
                    account = UPPER(TRIM(account)),
                    biller = UPPER(TRIM(biller)),
                    customer_name = UPPER(TRIM(customer_name)),
                    cp_number = UPPER(TRIM(cp_number)),
                    notes = CASE WHEN notes IS NULL THEN NULL ELSE UPPER(TRIM(notes)) END,
                    reference = CASE WHEN reference IS NULL THEN NULL ELSE UPPER(TRIM(reference)) END
                """
            )
        )
