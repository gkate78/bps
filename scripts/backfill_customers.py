#!/usr/bin/env python3
"""
One-time backfill: copy distinct accounts from bill_records into customer_accounts.
For each account we use the most recent record (by txn_datetime, id) for biller, name, phone.
Uses only stdlib sqlite3 — run from project root: python3 scripts/backfill_customers.py
"""
import os
import sqlite3
from pathlib import Path

DATABASE_DIR = os.getenv("DATABASE_DIR", ".")
DATABASE_FILE = os.path.join(DATABASE_DIR, "bills_admin.db")


def backfill() -> None:
    db_path = Path(DATABASE_FILE)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Ensure customer_accounts exists (table created by app)
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='customer_accounts'"
    )
    if not cur.fetchone():
        print("Table customer_accounts not found. Run the app once to create it.")
        conn.close()
        return

    cur.execute(
        """
        SELECT account, biller, customer_name, cp_number
        FROM bill_records
        WHERE TRIM(COALESCE(account, '')) != ''
        ORDER BY txn_datetime DESC, id DESC
        """
    )
    rows = cur.fetchall()
    seen = set()
    filled = 0
    now = "datetime('now')"
    for row in rows:
        account = (row["account"] or "").strip()
        if not account or account in seen:
            continue
        seen.add(account)
        biller = (row["biller"] or "").strip()
        customer_name = (row["customer_name"] or "").strip()
        phone = ((row["cp_number"] or "").strip())[:11]

        cur.execute("SELECT id FROM customer_accounts WHERE account = ?", (account,))
        if cur.fetchone():
            cur.execute(
                """
                UPDATE customer_accounts
                SET biller = ?, customer_name = ?, phone = ?, updated_at = {}
                WHERE account = ?
                """.format(now),
                (biller, customer_name, phone, account),
            )
        else:
            cur.execute(
                """
                INSERT INTO customer_accounts (account, biller, customer_name, phone, created_at, updated_at)
                VALUES (?, ?, ?, ?, {}, {})
                """.format(now, now),
                (account, biller, customer_name, phone),
            )
        filled += 1
    conn.commit()
    conn.close()
    print(f"Backfill done: {filled} account(s) upserted into customer_accounts.")


if __name__ == "__main__":
    backfill()
