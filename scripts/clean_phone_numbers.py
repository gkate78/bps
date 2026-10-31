#!/usr/bin/env python3
"""Normalize stored phone numbers: blank placeholders like NA and restore a dropped leading 0.

Also fills a customer's missing phone from their most recent record that has one.
Dry run by default; pass --apply to write. Run from the project root with the venv python.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.controllers.bill_controller import normalize_cp_number  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="bills_admin.db", help="Path to the database file")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is a dry run)")
    args = parser.parse_args()

    conn = sqlite3.connect(Path(args.db).expanduser())
    cur = conn.cursor()

    record_updates = []
    for rid, phone in cur.execute("SELECT id, cp_number FROM bill_records").fetchall():
        cleaned = normalize_cp_number(phone)
        if cleaned != (phone or ""):
            record_updates.append((cleaned, rid))

    # Latest valid phone per account, after cleaning.
    latest_phone: dict[str, str] = {}
    for account, phone in cur.execute(
        "SELECT account, cp_number FROM bill_records ORDER BY txn_date, txn_datetime, id"
    ).fetchall():
        cleaned = normalize_cp_number(phone)
        if len(cleaned) == 11:
            latest_phone[account] = cleaned

    customer_updates = []
    filled = 0
    for cid, account, phone in cur.execute("SELECT id, account, phone FROM customer_accounts").fetchall():
        cleaned = normalize_cp_number(phone)
        if not cleaned and account in latest_phone:
            cleaned = latest_phone[account]
            filled += 1
        if cleaned != (phone or ""):
            customer_updates.append((cleaned[:11], cid))

    print(f"Record phone numbers to fix: {len(record_updates)}")
    print(f"Customer phone numbers to fix: {len(customer_updates)} (of which filled from a recent record: {filled})")
    for cleaned, rid in record_updates[:5]:
        print(f"  e.g. record {rid} -> {cleaned or '(blank)'}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to save.")
        return
    cur.executemany("UPDATE bill_records SET cp_number = ? WHERE id = ?", record_updates)
    cur.executemany("UPDATE customer_accounts SET phone = ? WHERE id = ?", customer_updates)
    conn.commit()
    print("Saved.")


if __name__ == "__main__":
    main()
