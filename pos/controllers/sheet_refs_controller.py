"""
Payment references typed in the Google Sheet's "PAYMENT REFERENCES" tab (DEC-072).

The backup replaces every other tab, so references typed there were lost. Each backup lists the pending bills
in this tab (txn date/time, account, biller, bill amount, due date, BPS reference) and the sheet keeps what was
typed beside them: the owner types the payment reference and channel (e.g. from home), and Records →
"Get Sheet References" reads the typed rows without a STATUS, checks each against the bills, and puts the
chosen ones on the bills that are still pending. The rows are then marked DONE in the sheet.
"""
import asyncio
from datetime import date, datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import BillRecord
from pos.controllers import gsheets_controller as gsheets
from pos.controllers.settings_controller import get_settings

TAB = "PAYMENT REFERENCES"
MAX_ROWS = 300
MAX_REFERENCE = 120
UPDATE_SCRIPT = (
    "Update the script in your Google Sheet first: Shop register → Settings → Backup to Google Sheets → Set up "
    "(once) → Copy script, paste it in Extensions → Apps Script, Save, then Deploy → Manage deployments → "
    "Edit → Version: New version → Deploy (the link stays the same)."
)

# What may be typed in the CHANNEL column → BPS's payment channel. Blank uses the one chosen in BPS.
CHANNELS = {
    "CASH": "CASH", "GCASH": "GCASH", "MAYA": "MAYA", "BAYAD": "BAYAD",
    "BPICC": "BPI_CC", "BPI CC": "BPI_CC", "BPI_CC": "BPI_CC", "BPI": "BPI",
}


def clean(value) -> str:
    return " ".join(str(value or "").split())


def channel_for(value) -> Optional[str]:
    """'' for blank, the BPS channel, or None when it isn't one BPS knows."""
    typed = clean(value).upper()
    return "" if not typed else CHANNELS.get(typed)


async def _connection(db: AsyncSession) -> tuple[str, str]:
    s = await get_settings(db)
    if not s.gsheets_url or not s.gsheets_password:
        raise gsheets.BackupError("Set up the Google Sheet backup first (Shop register → Settings → Backup to Google Sheets).")
    return s.gsheets_url, s.gsheets_password


def _call(url: str, payload: dict) -> dict:
    try:
        return gsheets.post_table(url, payload)
    except gsheets.BackupError as exc:
        if "didn't answer like the BPS script" in str(exc):
            raise gsheets.BackupError(UPDATE_SCRIPT) from exc
        raise


async def read_rows(db: AsyncSession) -> list[dict]:
    url, password = await _connection(db)
    answer = await asyncio.to_thread(_call, url, {"action": "read_references", "password": password})
    if "references" not in answer:
        raise gsheets.BackupError(UPDATE_SCRIPT)
    return list(answer["references"])[:MAX_ROWS]


async def mark_rows(db: AsyncSession, marks: list[dict]) -> int:
    if not marks:
        return 0
    url, password = await _connection(db)
    answer = await asyncio.to_thread(_call, url, {"action": "mark_references", "password": password, "marks": marks})
    return int(answer.get("marked") or 0)


async def _bills_by_reference(db: AsyncSession, references: list[str]) -> dict[str, BillRecord]:
    if not references:
        return {}
    rows = await db.execute(select(BillRecord).where(func.upper(BillRecord.reference).in_(references)))
    return {str(b.reference).upper(): b for b in rows.scalars().all()}


async def preview(db: AsyncSession, rows: list[dict]) -> list[dict]:
    """
    Each sheet row with its bill and what applying it would do. state: "ready" (checked), "warn" (can be
    checked by hand), "done" (the bill already has this reference; the row is marked in the sheet) or
    "error" (can't be applied). Nothing is saved.
    """
    rows = [dict(r, bps_reference=clean(r.get("bps_reference")).upper(), payment_reference=clean(r.get("payment_reference")))
            for r in rows]
    bills = await _bills_by_reference(db, sorted({r["bps_reference"] for r in rows if r["bps_reference"]}))

    typed_refs = sorted({r["payment_reference"] for r in rows if r["payment_reference"]})
    used: dict[str, str] = {}
    if typed_refs:
        found = await db.execute(
            select(BillRecord.payment_reference, BillRecord.reference).where(BillRecord.payment_reference.in_(typed_refs))
        )
        used = {payment_ref: ref for payment_ref, ref in found.all()}

    def count(key):
        counts: dict[str, int] = {}
        for r in rows:
            if r[key]:
                counts[r[key]] = counts.get(r[key], 0) + 1
        return counts

    bps_counts, ref_counts = count("bps_reference"), count("payment_reference")
    items = []
    for r in rows:
        bill = bills.get(r["bps_reference"])
        channel = channel_for(r.get("channel"))
        item = {
            "row": int(r.get("row") or 0), "bps_reference": r["bps_reference"], "payment_reference": r["payment_reference"],
            "channel_typed": clean(r.get("channel")), "channel": channel or "",
            "id": bill.id if bill else None, "biller": bill.biller if bill else "", "account": bill.account if bill else "",
            "customer_name": bill.customer_name if bill else "",
            "txn_date": bill.txn_date.isoformat() if bill and bill.txn_date else "",
            "bill_amt": round(float(bill.bill_amt or 0), 2) if bill else None,
            "state": "error", "reason": "",
        }
        current = clean(bill.payment_reference) if bill else ""
        if not r["bps_reference"]:
            item["reason"] = "No BPS reference"
        elif not r["payment_reference"]:
            item["reason"] = "No payment reference"
        elif len(r["payment_reference"]) > MAX_REFERENCE:
            item["reason"] = f"Payment reference is longer than {MAX_REFERENCE} characters"
        elif not bill:
            item["reason"] = "No bill with this BPS reference"
        elif bps_counts[r["bps_reference"]] > 1:
            item["reason"] = "This BPS reference is on more than one row"
        elif current and current.upper() == r["payment_reference"].upper():
            item.update(state="done", reason="Already in BPS")
        elif current:
            item["reason"] = f"Bill already has reference {current}"
        elif channel is None:
            item["reason"] = "Channel should be CASH, GCASH, MAYA, BAYAD, BPICC or BPI (or blank)"
        elif r["payment_reference"] in used:
            item.update(state="warn", reason=f"Reference already on bill {used[r['payment_reference']]}")
        elif ref_counts[r["payment_reference"]] > 1:
            item.update(state="warn", reason="Same payment reference on another row")
        else:
            item.update(state="ready", reason="Ready")
        items.append(item)
    return items


async def apply(db: AsyncSession, items: list[dict], default_channel: str, done_rows: list[dict], log) -> dict:
    """
    Put each chosen row's reference on its bill if the bill is still pending (others are skipped), commit,
    then mark the rows in the sheet. `log(record, reference, channel)` adds the audit entry.
    """
    from app.controllers.bill_controller import _stamp_settled

    bills = await _bills_by_reference(db, sorted({clean(i["bps_reference"]).upper() for i in items}))
    applied, skipped, marks = [], 0, []
    today = date.today().strftime("%m/%d/%Y")
    for item in items:
        bill = bills.get(clean(item["bps_reference"]).upper())
        reference = clean(item["payment_reference"])
        channel = channel_for(item.get("channel"))
        if not bill or not reference or len(reference) > MAX_REFERENCE or channel is None:
            skipped += 1
            continue
        current = clean(bill.payment_reference)
        if current:
            skipped += 1
            if current.upper() == reference.upper():
                marks.append({"row": item["row"], "bps_reference": bill.reference, "status": "ALREADY IN BPS"})
            continue
        bill.payment_reference = reference
        bill.payment_channel = channel or default_channel
        _stamp_settled(bill, had_payment_reference=False)
        bill.updated_at = datetime.utcnow()
        db.add(bill)
        await log(bill, reference, bill.payment_channel)
        applied.append(bill.reference)
        marks.append({"row": item["row"], "bps_reference": bill.reference, "status": f"DONE {today}"})
    await db.commit()

    marks += [{"row": d["row"], "bps_reference": clean(d["bps_reference"]).upper(), "status": "ALREADY IN BPS"} for d in done_rows]
    sheet_error = ""
    try:
        await mark_rows(db, marks)
    except gsheets.BackupError as exc:
        sheet_error = str(exc)
    return {"applied": len(applied), "skipped": skipped, "marked": len(marks), "sheet_error": sheet_error}
