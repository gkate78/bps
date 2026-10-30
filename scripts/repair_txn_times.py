#!/usr/bin/env python3
"""Restore time of day on imported records whose source CSV had the time in the DATE column.

Older imports read only the date from DATE, so txn_datetime was stored as midnight.
The original row is kept in bill_record_import_raw (ingest_note = record reference),
so the time can be recovered from there. Dry run by default; pass --apply to write.
"""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

DATETIME_FORMATS = (
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)


def parse_datetime(value: str) -> datetime | None:
    cleaned = (value or "").strip()
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="bills_admin.db", help="Path to the database file")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is a dry run)")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        "SELECT id, reference, txn_date FROM bill_records "
        "WHERE time(txn_datetime) = '00:00:00' AND reference IS NOT NULL"
    )
    midnight = {ref: (rid, txn_date) for rid, ref, txn_date in cur.fetchall()}

    cur.execute(
        "SELECT ingest_note, raw_row_json FROM bill_record_import_raw "
        "WHERE ingest_status = 'CREATED' AND ingest_note IS NOT NULL"
    )
    updates = []
    for reference, raw_json in cur.fetchall():
        if reference not in midnight:
            continue
        rid, txn_date = midnight[reference]
        row = {str(k).strip().upper(): v for k, v in json.loads(raw_json).items()}
        parsed = parse_datetime(row.get("DATE/TIME", "")) or parse_datetime(row.get("DATE", ""))
        if parsed is None or parsed.time() == datetime.min.time():
            continue
        if parsed.date().isoformat() != str(txn_date):
            continue
        updates.append((parsed.strftime("%Y-%m-%d %H:%M:%S.%f"), rid))

    print(f"Records at midnight: {len(midnight)}; times recoverable: {len(updates)}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to save.")
        return
    cur.executemany("UPDATE bill_records SET txn_datetime = ? WHERE id = ?", updates)
    conn.commit()
    print(f"Updated {len(updates)} records.")


if __name__ == "__main__":
    main()
