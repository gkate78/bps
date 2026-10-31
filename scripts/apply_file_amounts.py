#!/usr/bin/env python3
"""Restore the import file's own amounts on records imported before imports kept them.

Older imports recalculated late charge, service charge, total and change from the biller rules.
The original rows are kept in bill_record_import_raw (ingest_note = record reference), so the
amounts actually collected can be put back, with an amount review note where they differ from
the rules or don't add up. Records whose bill amount, biller or due date were edited since import
are left alone. Dry run by default; pass --apply to write. Run from the project root with the venv python.
"""
import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.controllers.bill_controller import (  # noqa: E402
    _apply_file_amounts,
    _csv_cell,
    _parse_date,
    _parse_float,
)

FILE_AMOUNT_COLUMNS = (
    ("late_charge", ("LATE_CHARGE", "LATE CHARGE", "AMT2")),
    ("charge", ("CHARGE", "SERVICE CHARGE")),
    ("total", ("TOTAL",)),
    ("change_amt", ("CHANGE", "CHANGE_AMT")),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="bills_admin.db", help="Path to the database file")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is a dry run)")
    args = parser.parse_args()

    conn = sqlite3.connect(Path(args.db).expanduser())
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cols = {row[1] for row in cur.execute("PRAGMA table_info(bill_records)")}
    if "amount_review" not in cols:
        print("Start the app once first so the database gets the amount_review column.")
        return

    rules = cur.execute("SELECT biller, service_charge, late_charge FROM biller_rules WHERE is_active = 1").fetchall()
    charge_map = {str(r["biller"]).strip().upper(): round(float(r["service_charge"] or 0), 2) for r in rules}
    late_map = {str(r["biller"]).strip().upper(): round(float(r["late_charge"] or 0), 2) for r in rules}

    records = {
        r["reference"]: r
        for r in cur.execute(
            "SELECT id, reference, txn_date, biller, bill_amt, cash, due_date, late_charge, charge, total, change_amt, "
            "amount_review FROM bill_records WHERE reference IS NOT NULL"
        )
    }

    updates = []
    stats = collections.Counter()
    for (reference, raw_json) in cur.execute(
        "SELECT ingest_note, raw_row_json FROM bill_record_import_raw WHERE ingest_status = 'CREATED'"
    ).fetchall():
        record = records.get(reference)
        if record is None:
            stats["record no longer exists"] += 1
            continue
        row = json.loads(raw_json)
        bill_amt = round(_parse_float(_csv_cell(row, "AMT", "BILL AMT", "bill_amt", "BILL_AMT")), 2)
        biller = _csv_cell(row, "BILLER", "biller").upper()
        due_date = _parse_date(_csv_cell(row, "DUE DATE", "due_date", "DUE_DATE"))
        if (
            abs(bill_amt - float(record["bill_amt"] or 0)) >= 0.01
            or biller != str(record["biller"] or "").upper()
            or str(due_date or "") != str(record["due_date"] or "")
        ):
            stats["edited since import (left alone)"] += 1
            continue

        file_amounts = {}
        for key, aliases in FILE_AMOUNT_COLUMNS:
            cell = _csv_cell(row, *aliases)
            file_amounts[key] = _parse_float(cell) if cell else None
        payload = {
            "biller": record["biller"],
            "bill_amt": bill_amt,
            "cash": record["cash"],
            "due_date": due_date,
            "txn_date": _parse_date(str(record["txn_date"])),
        }
        payload, review = _apply_file_amounts(payload, file_amounts, charge_map, late_map)
        new_values = (payload["late_charge"], payload["charge"], payload["total"], payload["change_amt"])
        old_values = tuple(round(float(record[k] or 0), 2) for k in ("late_charge", "charge", "total", "change_amt"))
        review_json = json.dumps(review) if review else None
        if review:
            for issue in review["issues"]:
                stats[issue] += 1
        if new_values == old_values and review_json == record["amount_review"]:
            stats["already matches file"] += 1
            continue
        stats["amounts restored from file" if new_values != old_values else "review note added"] += 1
        updates.append((*new_values, payload["late_charge"], review_json, record["id"]))

    for label, count in sorted(stats.items()):
        print(f"  {label}: {count}")
    print(f"Records to update: {len(updates)}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to save.")
        return
    cur.executemany(
        "UPDATE bill_records SET late_charge = ?, charge = ?, total = ?, change_amt = ?, amt2 = ?, amount_review = ? "
        "WHERE id = ?",
        updates,
    )
    conn.commit()
    print("Saved.")


if __name__ == "__main__":
    main()
