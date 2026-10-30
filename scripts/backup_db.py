#!/usr/bin/env python3
import argparse
import sqlite3
from datetime import datetime
from pathlib import Path


def backup(db_path: Path, backup_dir: Path, keep: int) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"bills_admin-{stamp}.db"

    # sqlite3 backup API gives a consistent copy even while the app is running.
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    backups = sorted(backup_dir.glob("bills_admin-*.db"))
    for old in backups[:-keep] if keep > 0 else []:
        old.unlink()
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up the BPS SQLite database.")
    parser.add_argument("--db", default="bills_admin.db", help="Path to the database file")
    parser.add_argument("--dir", default=None, help="Backup folder (default: <db folder>/backups)")
    parser.add_argument("--keep", type=int, default=30, help="Number of backups to keep (0 = keep all)")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"No database at {db_path}, nothing to back up.")
        return
    backup_dir = Path(args.dir).expanduser() if args.dir else db_path.parent / "backups"
    target = backup(db_path, backup_dir, args.keep)
    print(f"Backup saved: {target}")


if __name__ == "__main__":
    main()
