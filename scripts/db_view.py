#!/usr/bin/env python3
import argparse
import sqlite3
from pathlib import Path


def print_rows(cur: sqlite3.Cursor, query: str, limit: int) -> None:
    try:
        cur.execute(f"{query} LIMIT ?", (limit,))
        rows = cur.fetchall()
    except sqlite3.OperationalError as exc:
        print(f"(query failed: {exc})")
        return
    for row in rows:
        print(row)
    if not rows:
        print("(no rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick SQLite viewer for bills_admin.db")
    parser.add_argument("--db", default="bills_admin.db", help="Path to sqlite database file")
    parser.add_argument(
        "--table",
        choices=["user_accounts", "bill_records", "auth_event_logs"],
        help="View a specific table only",
    )
    parser.add_argument("--limit", type=int, default=20, help="Row limit (default: 20)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Database file not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cur.fetchall()]
    except sqlite3.OperationalError as exc:
        raise SystemExit(f"Unable to read sqlite metadata: {exc}")
    print("Tables:")
    for name in tables:
        print(f"- {name}")

    if args.table == "user_accounts":
        print("\nUsers:")
        print_rows(
            cur,
            "SELECT id, first_name, last_name, phone, role, created_at FROM user_accounts ORDER BY id DESC",
            args.limit,
        )
    elif args.table == "bill_records":
        print("\nBill Records:")
        print_rows(
            cur,
            "SELECT id, txn_date, account, biller, bill_amt, amt2, total, due_date, reference FROM bill_records ORDER BY id DESC",
            args.limit,
        )
    elif args.table == "auth_event_logs":
        print("\nAuth Event Logs:")
        print_rows(
            cur,
            "SELECT id, user_id, phone, event_type, status, detail, created_at "
            "FROM auth_event_logs ORDER BY id DESC",
            args.limit,
        )
    else:
        print("\nUsers:")
        if "user_accounts" in tables:
            print_rows(
                cur,
                "SELECT id, first_name, last_name, phone, role, created_at FROM user_accounts ORDER BY id DESC",
                args.limit,
            )
        else:
            print("(table user_accounts not found)")

        print("\nBill Records:")
        if "bill_records" in tables:
            print_rows(
                cur,
                "SELECT id, txn_date, account, biller, bill_amt, amt2, total, due_date, reference FROM bill_records ORDER BY id DESC",
                args.limit,
            )
        else:
            print("(table bill_records not found)")

        print("\nAuth Event Logs:")
        if "auth_event_logs" in tables:
            print_rows(
                cur,
                "SELECT id, user_id, phone, event_type, status, detail, created_at "
                "FROM auth_event_logs ORDER BY id DESC",
                args.limit,
            )
        else:
            print("(table auth_event_logs not found)")

    conn.close()


if __name__ == "__main__":
    main()
