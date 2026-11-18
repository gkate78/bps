"""
Tidy the descriptions of past shop sales and fill each service's pick list from them (DEC-075).

    venv/bin/python scripts/standardize_service_items.py --db ~/bps-data/bills_admin.db           # preview only
    venv/bin/python scripts/standardize_service_items.py --db ~/bps-data/bills_admin.db --apply   # change it

Descriptions: upper case, single spaces, "B&W"/"B &W" → "B & W", "W/" → "WITH", "EDITS" → "EDIT",
"2 X 2" → "2X2", known misspellings (ATIRE, CHINEESE, VELUM), "PHOTO PRINT" sizes as "3R PHOTO" like 4R/5R,
and "SHORT - BACK TO BACK" → "SHORT BACK TO BACK". Different products (COLORED vs FULL COLOR) are left apart.
The pick list gets every tidied description sold in a completed sale, with the latest price; items already in a
service's list are kept as they are. A backup is made next to the database before --apply changes anything.
"""
import argparse
import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

WORD_FIXES = {"ATIRE": "ATTIRE", "CHINEESE": "CHINESE", "VELUM": "VELLUM", "EDITS": "EDIT"}


def tidy(description: str) -> str:
    text = " ".join(str(description or "").upper().split())
    text = re.sub(r"\bB\s*&\s*W\b", "B & W", text)
    text = re.sub(r"\bW/\s*", "WITH ", text)
    text = re.sub(r"(\d(?:\.\d+)?)\s*X\s*(\d)", r"\1X\2", text)
    text = re.sub(r"\b(\d)R PHOTO PRINT\b", r"\1R PHOTO", text)
    text = re.sub(r"^(SHORT|LONG|A4) - BACK TO BACK$", r"\1 BACK TO BACK", text)
    text = " ".join(WORD_FIXES.get(word, word) for word in text.split())
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="change the database (otherwise only show what would change)")
    args = parser.parse_args()
    db = args.db.expanduser()
    if not db.exists():
        raise SystemExit(f"No database at {db}")

    conn = sqlite3.connect(f"file:{db}?mode={'rw' if args.apply else 'ro'}", uri=True)
    has_items = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pos_service_items'").fetchone()
    if args.apply and not has_items:
        raise SystemExit("pos_service_items doesn't exist yet: start BPS once with the new version, then run this again.")

    lines = conn.execute(
        "SELECT l.id, l.service_id, s.name, l.description, l.unit_price_cents, p.status FROM pos_sale_lines l"
        " JOIN pos_sales p ON p.id = l.sale_id LEFT JOIN pos_services s ON s.id = l.service_id"
        " WHERE l.kind = 'service' AND TRIM(COALESCE(l.description, '')) != '' ORDER BY l.id"
    ).fetchall()
    renames, latest = {}, {}
    for line_id, service_id, _service, description, price, status in lines:
        clean = tidy(description)
        if clean != description:
            renames.setdefault((description, clean), []).append(line_id)
        if status == "completed" and service_id:
            latest[(service_id, clean)] = price  # lines come oldest first, so the last price wins

    existing = set()
    if has_items:
        existing = {(sid, name) for sid, name in conn.execute("SELECT service_id, name FROM pos_service_items")}
    service_names = dict(conn.execute("SELECT id, name FROM pos_services"))
    new_items = sorted(
        ((sid, name, price) for (sid, name), price in latest.items() if (sid, name) not in existing),
        key=lambda x: (service_names.get(x[0], ""), x[1]),
    )

    print(f"Descriptions to tidy: {len(renames)} ({sum(len(v) for v in renames.values())} sale lines)")
    for (old, new), ids in sorted(renames.items()):
        print(f"  {old!r} → {new!r}  ({len(ids)})")
    print(f"\nPick list items to add: {len(new_items)}")
    for sid, name, price in new_items:
        print(f"  {service_names.get(sid, sid)}: {name}  ₱{price / 100:,.2f}")

    if not args.apply:
        print("\nPreview only. Run again with --apply to change the database.")
        return

    backup = db.with_name(f"{db.stem}-before-service-items-{datetime.now():%Y%m%d-%H%M%S}.db")
    if db.parent.joinpath("backups").is_dir():
        backup = db.parent / "backups" / backup.name
    conn.close()
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    dst = sqlite3.connect(backup)
    src.backup(dst)
    dst.close()
    src.close()
    print(f"\nBackup: {backup}")

    conn = sqlite3.connect(db, timeout=30)
    now = datetime.now().isoformat(sep=" ")
    with conn:
        for (old, new), ids in renames.items():
            conn.executemany("UPDATE pos_sale_lines SET description = ? WHERE id = ?", [(new, i) for i in ids])
        orders = {}
        for sid, name, price in new_items:
            orders[sid] = orders.get(sid) or (conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM pos_service_items WHERE service_id = ?", (sid,)
            ).fetchone()[0])
            orders[sid] += 1
            conn.execute(
                "INSERT INTO pos_service_items (service_id, name, price_cents, sort_order, is_active) VALUES (?, ?, ?, ?, 1)",
                (sid, name, price, orders[sid]),
            )
        conn.execute(
            "INSERT INTO pos_audit_log (entity, entity_id, action, user_id, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("service_item", 0, "standardize", None,
             json.dumps({"descriptions_tidied": len(renames), "lines": sum(len(v) for v in renames.values()),
                         "items_added": len(new_items)}), now),
        )
    print(f"Done: {sum(len(v) for v in renames.values())} sale lines tidied, {len(new_items)} pick list items added.")


if __name__ == "__main__":
    main()
