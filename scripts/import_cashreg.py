#!/usr/bin/env python3
"""
Move the standalone shop register's data (~/cashreg-data/cashreg.db) into the BPS database.

Copies every pos_* table with its ids (sales, lines, job order payments, GCash/Maya transactions,
fees, services, networks, wallets, settings, audit log), replacing the register's default rows in
BPS. Register users are matched to BPS accounts by phone number. Refuses if BPS already has
register transactions. Dry run unless --apply; backs up the BPS database first.

    venv/bin/python scripts/import_cashreg.py --from ~/cashreg-data/cashreg.db --db ~/bps-data/bills_admin.db
"""
import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backup_db import backup  # noqa: E402

# Copied in this order (parents first). Columns holding register user ids are remapped to BPS ids.
TABLES = {
    "pos_settings": (),
    "pos_fee_brackets": (),
    "pos_services": (),
    "pos_networks": (),
    "pos_wallets": (),
    "pos_sales": ("cashier_user_id", "voided_by_user_id"),
    "pos_sale_lines": (),
    "pos_sale_payments": ("cashier_user_id", "voided_by_user_id"),
    "pos_wallet_txns": ("cashier_user_id", "voided_by_user_id"),
    "pos_audit_log": ("user_id",),
}
TRANSACTION_TABLES = ("pos_sales", "pos_sale_payments", "pos_wallet_txns")


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def new_column_defaults(table: str, source_columns: set[str]) -> dict:
    """Plain defaults from the model for columns the source table doesn't have."""
    from sqlmodel import SQLModel

    import pos.models  # noqa: F401

    out = {}
    for column in SQLModel.metadata.tables[table].columns:
        if column.name in source_columns or column.primary_key:
            continue
        default = column.default.arg if column.default is not None and not callable(column.default.arg) else None
        if default is not None:
            out[column.name] = default
    return out


def create_register_tables(db_path: Path) -> None:
    """Same tables the app creates on start-up (pos.database.init_db), without seeding defaults."""
    from sqlalchemy import create_engine
    from sqlmodel import SQLModel

    import pos.models  # noqa: F401

    engine = create_engine(f"sqlite:///{db_path}")
    tables = [t for name, t in SQLModel.metadata.tables.items() if name.startswith("pos_")]
    SQLModel.metadata.create_all(engine, tables=tables)
    engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--from", dest="source", required=True, help="Standalone register database (cashreg.db)")
    parser.add_argument("--db", required=True, help="BPS database (bills_admin.db)")
    parser.add_argument("--apply", action="store_true", help="Make the changes (default: dry run)")
    args = parser.parse_args()

    source_path = Path(args.source).expanduser()
    target_path = Path(args.db).expanduser()
    for path in (source_path, target_path):
        if not path.exists():
            print(f"Not found: {path}")
            return 1

    src = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    if args.apply:
        print(f"Backup saved: {backup(target_path, target_path.parent / 'backups', keep=30)}")
        work = target_path
    else:
        # Dry run: do everything on a temporary copy so the real database isn't touched.
        work = Path(tempfile.mkdtemp()) / "dry_run.db"
        with sqlite3.connect(work) as copy:
            sqlite3.connect(f"file:{target_path}?mode=ro", uri=True).backup(copy)
    try:
        create_register_tables(work)
        return copy_data(src, sqlite3.connect(work), args.apply)
    finally:
        if not args.apply:
            shutil.rmtree(work.parent, ignore_errors=True)


def copy_data(src: sqlite3.Connection, dst: sqlite3.Connection, apply: bool) -> int:
    # Users: match by phone number.
    bps_users = {phone: uid for uid, phone in dst.execute("SELECT id, phone FROM user_accounts")}
    user_map, missing = {}, []
    for uid, phone, first, role in src.execute("SELECT id, phone, first_name, role FROM pos_users"):
        if phone in bps_users:
            user_map[uid] = bps_users[phone]
        else:
            missing.append(f"{first} ({role}, phone ending {phone[-4:]})")
    if missing:
        print("These register users have no BPS account with the same phone number. Add them in BPS first:")
        for item in missing:
            print(f"  - {item}")
        return 1

    existing = {t: dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TRANSACTION_TABLES}
    if any(existing.values()):
        print(f"BPS already has register transactions {existing}; refusing to overwrite them.")
        return 1

    for table, user_columns in TABLES.items():
        src_cols = columns(src, table)
        if not src_cols:
            print(f"{table}: not in the source, skipped")
            continue
        shared = [c for c in src_cols if c in set(columns(dst, table))]
        # Columns added after the standalone register get the model's default (e.g. starting cash = 0).
        defaults = new_column_defaults(table, set(src_cols))
        names = shared + list(defaults)
        rows = src.execute(f"SELECT {', '.join(shared)} FROM {table} ORDER BY id").fetchall()
        dst.execute(f"DELETE FROM {table}")  # the register's default rows
        positions = [shared.index(c) for c in user_columns if c in shared]
        for row in rows:
            row = list(row)
            for pos in positions:
                if row[pos] is not None:
                    row[pos] = user_map.get(row[pos], row[pos])
            dst.execute(
                f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
                row + list(defaults.values()),
            )
        print(f"{table}: {len(rows)} row(s)")

    if apply:
        dst.commit()
        print("Done. Start BPS with ./scripts/run_local.sh and check the shop register.")
    else:
        print("Dry run: nothing was changed. Run again with --apply to copy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
