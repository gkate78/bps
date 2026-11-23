"""
Payment references from Santa Maria Water District's Billing Inquiry (https://smwdbulacan.gov.ph/).

The site's inquiry takes the 11-digit ID number (201811-34651) and shows the month's statement with the
latest payment: Reference No. (the office O.R. number for payments there, an online code for GCash and
the like), Amount Paid and Date Paid. BPS looks up its pending STA MARIA WATER bills there, matches each
to the payment, and the owner applies the matches as payment references (DEC-070).
"""
import asyncio
import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import BillRecord

INQUIRY_URL = "https://smwdbulacan.gov.ph/?page_id=4971"
BILLERS = ("STA MARIA WATER",)
TIMEOUT_SECONDS = 20
PAUSE_SECONDS = 0.5  # between lookups, so the site isn't flooded
MAX_BILLS = 100


class SmwdError(Exception):
    pass


@dataclass
class Statement:
    """What the inquiry shows for one ID number (None where the page has nothing)."""
    bill_no: Optional[str]
    total_due: Optional[float]
    penalty: Optional[float]
    reference: Optional[str]
    amount_paid: Optional[float]
    date_paid: Optional[datetime]


def is_smwd_biller(biller: Optional[str]) -> bool:
    return str(biller or "").strip().upper() in BILLERS


def id_number(account: str) -> str:
    """20181134651 → 201811-34651, as the site's form sends it."""
    digits = "".join(ch for ch in str(account or "") if ch.isdigit())
    return f"{digits[:6]}-{digits[6:]}" if len(digits) == 11 else digits


def _cell(page: str, label: str) -> Optional[str]:
    match = re.search(r"<td>\s*" + re.escape(label) + r"\s*</td>\s*<td>(.*?)</td>", page, re.S)
    if not match:
        return None
    value = html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
    return value or None


def _amount(value: Optional[str]) -> Optional[float]:
    try:
        return round(float(str(value).replace(",", "").strip("() ")), 2) if value else None
    except ValueError:
        return None


def _when(value: Optional[str]) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value or "").strip(), fmt)
        except ValueError:
            continue
    return None


def parse_statement(page: str) -> Statement:
    return Statement(
        bill_no=_cell(page, "Bill No."),
        total_due=_amount(_cell(page, "Total Amount Due")),
        penalty=_amount(_cell(page, "Penalty (10%)")),
        reference=_cell(page, "Reference No."),
        amount_paid=_amount(_cell(page, "Amount Paid")),
        date_paid=_when(_cell(page, "Date Paid")),
    )


def _fetch(account: str) -> str:
    body = urllib.parse.urlencode({"IDNoVal": id_number(account), "submit": "View"}).encode()
    request = urllib.request.Request(
        INQUIRY_URL, data=body, method="POST",
        headers={"User-Agent": "Mozilla/5.0 (BPS bills payment)", "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="ignore")
    except TimeoutError as exc:
        raise SmwdError("SMWD's site took too long to answer") from exc
    except OSError as exc:
        raise SmwdError(f"Couldn't reach SMWD's site ({getattr(exc, 'reason', exc)})") from exc


async def lookup(account: str) -> Statement:
    return parse_statement(await asyncio.to_thread(_fetch, account))


def _cents(value) -> int:
    return int(round(float(value or 0) * 100))


async def preview(db: AsyncSession, bills: list[BillRecord], fetch=None) -> list[dict]:
    """
    Each pending bill with SMWD's latest payment for its ID number and whether it matches: paid on or after
    the bill's date, for the bill amount (or the bill plus the late charge or SMWD's penalty), with a
    reference not already on another bill. Nothing is saved.
    """
    fetch = fetch or lookup  # looked up when called, so tests can stand in for the site
    bills = [b for b in bills if is_smwd_biller(b.biller)][:MAX_BILLS]
    statements: dict[str, object] = {}
    for index, account in enumerate(dict.fromkeys(b.account for b in bills)):
        if index:
            await asyncio.sleep(PAUSE_SECONDS)
        try:
            statements[account] = await fetch(account)
        except SmwdError as exc:
            statements[account] = exc

    references = [s.reference for s in statements.values() if isinstance(s, Statement) and s.reference]
    used = {}
    if references:
        rows = await db.execute(
            select(BillRecord.payment_reference, BillRecord.reference).where(BillRecord.payment_reference.in_(references))
        )
        used = {payment_ref: ref for payment_ref, ref in rows.all()}

    items, claimed = [], set()
    # Newest first, so with two pending bills for one account the latest one gets the payment.
    for bill in sorted(bills, key=lambda b: (b.txn_datetime or datetime.min), reverse=True):
        s = statements.get(bill.account)
        item = {
            "id": bill.id, "reference": bill.reference, "account": bill.account, "id_number": id_number(bill.account),
            "customer_name": bill.customer_name, "txn_date": bill.txn_date.isoformat() if bill.txn_date else "",
            "bill_amt": round(float(bill.bill_amt or 0), 2), "late_charge": round(float(bill.late_charge or 0), 2),
            "smwd_reference": None, "amount_paid": None, "date_paid": None, "matched": False, "reason": "",
        }
        if isinstance(s, SmwdError):
            item["reason"] = str(s)
        elif not s or not s.reference:
            item["reason"] = "No payment found at SMWD yet"
        else:
            item.update(smwd_reference=s.reference, amount_paid=s.amount_paid,
                        date_paid=s.date_paid.isoformat(timespec="minutes") if s.date_paid else None)
            accepted = {_cents(bill.bill_amt), _cents(bill.bill_amt) + _cents(bill.late_charge),
                        _cents(bill.bill_amt) + _cents(s.penalty)}
            if s.date_paid and bill.txn_date and s.date_paid.date() < bill.txn_date:
                item["reason"] = f"SMWD's latest payment ({s.date_paid:%m/%d/%Y}) is before this bill"
            elif s.amount_paid is None or _cents(s.amount_paid) not in accepted:
                item["reason"] = "Amount paid differs from this bill"
            elif s.reference in used:
                item["reason"] = f"Reference already on bill {used[s.reference]}"
            elif s.reference in claimed:
                item["reason"] = "This payment matches a newer bill of the same account"
            else:
                item["matched"] = True
                claimed.add(s.reference)
        items.append(item)
    return items


def checked_reference(value: Optional[str]) -> str:
    reference = " ".join(str(value or "").split())
    if not reference or len(reference) > 120:
        raise SmwdError("Each bill needs a reference")
    return reference
