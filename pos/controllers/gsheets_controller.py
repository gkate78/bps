"""
Backup to Google Sheets: a readable copy of bills and shop records in the shop's own Google Sheet.

BPS posts each table to an Apps Script web app in that sheet (pos/gsheets/backup_script.gs), which
replaces that table's tab. Only listed tables and columns are sent (no PINs, login codes or settings).
Not for restoring: the database backups in ~/bps-data/backups are.
"""
import asyncio
import json
import secrets
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from app import database as bps_db
from pos.controllers.settings_controller import add_audit, get_settings

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "gsheets" / "backup_script.gs"
URL_PREFIX = "https://script.google.com/macros/s/"
TIMEOUT_SECONDS = 120

BILL_AMOUNTS = {"bill_amt", "late_charge", "charge", "total", "cash", "change_amt"}

# (tab, SQL). Amount columns ending in _cents are sent in pesos without the suffix.
TABLES = (
    (
        "BILLS",
        "SELECT id, txn_datetime, txn_date, account, biller, customer_name, cp_number, bill_amt,"
        " COALESCE(amt2, late_charge) AS late_charge, charge, total, cash, change_amt, due_date, notes, reference,"
        " confirmation_reference, payment_method, payment_channel, payment_reference, settled_at, processed_by_user_id,"
        " created_by_user_id, amount_review, created_at, updated_at FROM bill_records ORDER BY id",
    ),
    ("CUSTOMERS", "SELECT * FROM customer_accounts ORDER BY id"),
    ("BILLERS", "SELECT * FROM biller_rules ORDER BY id"),
    ("STAFF", "SELECT id, first_name, last_name, role FROM user_accounts ORDER BY id"),
    ("SHOP SALES", "SELECT * FROM pos_sales ORDER BY id"),
    ("SHOP SALE LINES", "SELECT * FROM pos_sale_lines ORDER BY id"),
    ("JOB ORDER PAYMENTS", "SELECT * FROM pos_sale_payments ORDER BY id"),
    ("GCASH MAYA CASH-IN OUT", "SELECT * FROM pos_wallet_txns ORDER BY id"),
    ("END OF DAY", "SELECT * FROM pos_day_closes ORDER BY day"),
    ("END OF DAY GCASH MAYA", "SELECT * FROM pos_day_wallets ORDER BY day, wallet_id"),
    ("CASH MOVEMENTS", "SELECT * FROM pos_cash_movements ORDER BY id"),
    ("SHOP SERVICES", "SELECT * FROM pos_services ORDER BY id"),
    ("GCASH MAYA ACCOUNTS", "SELECT * FROM pos_wallets ORDER BY id"),
)

_running = asyncio.Lock()


class BackupError(Exception):
    pass


def valid_url(url: str) -> bool:
    return url.startswith(URL_PREFIX) and url.endswith("/exec") and len(url) <= 500


def new_password() -> str:
    return secrets.token_urlsafe(18)


def script_text(password: str) -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8").replace("__PASSWORD__", password)


def _table(tab: str, columns: list[str], rows: list[tuple]) -> dict:
    names, formats, converters = [], [], []
    for i, name in enumerate(columns):
        values = [row[i] for row in rows if row[i] is not None]
        if name.endswith("_cents"):
            names.append(name[: -len("_cents")])
            formats.append("#,##0.00")
            converters.append(lambda v: v / 100)
            continue
        names.append(name)
        if name in BILL_AMOUNTS:
            formats.append("#,##0.00")
        elif any(isinstance(v, str) for v in values):
            formats.append("@")  # text: keeps phone numbers' leading 0 and dates as written
        else:
            formats.append("")
        converters.append(None)
    out_rows = [
        ["" if v is None else (convert(v) if convert else v) for v, convert in zip(row, converters)] for row in rows
    ]
    return {"tab": tab, "columns": names, "formats": formats, "rows": out_rows}


async def collect_tables() -> list[dict]:
    tables = []
    async with bps_db.AsyncSessionLocal() as db:
        for tab, sql in TABLES:
            result = await db.execute(text(sql))
            tables.append(_table(tab, list(result.keys()), [tuple(r) for r in result.fetchall()]))
    return tables


def post_table(url: str, payload: dict) -> dict:
    """POST one table to the Apps Script web app (it answers through a redirect, which urllib follows)."""
    request = urllib.request.Request(
        url, data=json.dumps(payload, default=str).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        raise BackupError(f"Couldn't reach Google ({getattr(exc, 'reason', exc)}). Check the internet connection.")
    except TimeoutError:
        raise BackupError("Google took too long to answer. Try again later.")
    try:
        answer = json.loads(body)
    except ValueError:
        raise BackupError("The link didn't answer like the BPS script. Check it's deployed as a Web app with access 'Anyone'.")
    if not answer.get("ok"):
        raise BackupError(f"Google Sheet said: {answer.get('error') or 'error'}")
    return answer


async def run_backup(trigger: str, user_id: int | None = None) -> str:
    """Send every table; records and returns the result message. Raises BackupError on failure."""
    if _running.locked():
        raise BackupError("A backup is already running.")
    async with _running:
        async with bps_db.AsyncSessionLocal() as db:
            s = await get_settings(db)
            url, password = s.gsheets_url or "", s.gsheets_password or ""
        if not url or not password:
            raise BackupError("Set up the Google Sheet link first.")
        sent_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        error, rows = None, 0
        try:
            for table in await collect_tables():
                await asyncio.to_thread(post_table, url, {**table, "password": password, "sent_at": sent_at})
                rows += len(table["rows"])
        except BackupError as exc:
            error = str(exc)
        message = error or f"Backed up {len(TABLES)} tabs ({rows:,} rows)"
        async with bps_db.AsyncSessionLocal() as db:
            s = await get_settings(db)
            s.gsheets_last_at = datetime.now()
            s.gsheets_last_result = f"{'FAILED: ' if error else ''}{message} ({trigger})"[:500]
            db.add(s)
            add_audit(db, "gsheets", 1, "backup_failed" if error else "backup", user_id, {"trigger": trigger, "result": message})
            await db.commit()
        if error:
            raise BackupError(error)
        return message


async def backup_after_eod(user_id: int) -> None:
    """Background run after End of day is saved, when turned on; the result shows in Settings."""
    async with bps_db.AsyncSessionLocal() as db:
        s = await get_settings(db)
        if not (s.gsheets_after_eod and s.gsheets_url and s.gsheets_password):
            return
    try:
        await run_backup("after End of day", user_id)
    except BackupError:
        pass  # recorded in Settings
