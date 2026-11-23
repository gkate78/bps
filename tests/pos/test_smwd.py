"""SMWD payment references: parse the Billing Inquiry page, match pending water bills, apply. No network."""
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session, select

from app.controllers import smwd_controller as smwd
from app.models import BillRecord

TODAY = date.today()

PAGE = """<table><tr><td>Bill No.</td><td>2611BAL000001</td></tr>
<tr><td>Total Amount Due</td><td>1,075.10</td></tr><tr><td>Penalty (10%)</td><td>104.90</td></tr>
<tr><td colspan="2">Payment Details</td></tr><tr><td>Reference No.</td><td>04961602</td></tr>
<tr>
  <td>Amount Paid</td>
  <td>
    1,180.00    </td>
</tr>
<tr><td>Date Paid</td><td> {paid} 07:35 AM </td></tr></table>"""


def test_parse_statement_and_id_number():
    s = smwd.parse_statement(PAGE.format(paid="2026-11-13"))
    assert (s.bill_no, s.total_due, s.penalty, s.reference, s.amount_paid) == ("2611BAL000001", 1075.10, 104.90, "04961602", 1180.00)
    assert s.date_paid == datetime(2026, 11, 13, 7, 35)
    empty = smwd.parse_statement("<p>no statement</p>")
    assert empty.reference is None and empty.amount_paid is None
    assert smwd.id_number("20181134651") == "201811-34651"


def add(shop, account, amount, ref, days_ago=2, paid_ref=None, biller="STA MARIA WATER"):
    when = TODAY - timedelta(days=days_ago)
    shop.add(BillRecord(txn_datetime=datetime.combine(when, datetime.min.time()), txn_date=when, account=account,
                        biller=biller, customer_name="X", cp_number="", bill_amt=amount, charge=15, total=amount + 15,
                        cash=amount + 15, due_date=when, reference=ref, payment_reference=paid_ref))


@pytest.fixture
def fake_site(monkeypatch):
    paid = (TODAY - timedelta(days=1)).isoformat()
    statements = {
        "20140722010": smwd.parse_statement(PAGE.format(paid=paid)),  # 1,075.10 + penalty = 1,180.00
        "20181134651": smwd.Statement("B", 335.5, 32.4, "E8E0A4A2F0A2", 335.5, datetime.now()),
        "20000000001": smwd.Statement("B", 500, 0, None, None, None),  # nothing paid yet
        "20000000002": smwd.Statement("B", 500, 0, "OLD123", 500, datetime.now() - timedelta(days=40)),
        "20000000003": smwd.Statement("B", 500, 0, "R999", 480, datetime.now()),
    }
    calls = []

    async def fetch(account):
        calls.append(account)
        if account == "20000000004":
            raise smwd.SmwdError("Couldn't reach SMWD's site (timed out)")
        return statements[account]

    monkeypatch.setattr(smwd, "lookup", fetch)
    monkeypatch.setattr(smwd, "PAUSE_SECONDS", 0)
    return calls


def test_preview_matches_and_apply(shop, fake_site):
    add(shop, "20140722010", 1075.10, "REF-CASH")
    add(shop, "20181134651", 335.50, "REF-GCASH")
    add(shop, "20000000001", 500, "REF-NOTYET")
    add(shop, "20000000002", 500, "REF-OLDPAY")
    add(shop, "20000000003", 500, "REF-DIFF")
    add(shop, "20000000004", 500, "REF-DOWN")
    add(shop, "20000000005", 500, "REF-DONE", paid_ref="ALREADY")  # processed: not looked up
    add(shop, "20000000006", 500, "REF-METER", biller="MERALCO")
    client = shop.client

    assert client.post("/api/records/smwd/preview", params={"biller": "MERALCO"}).status_code == 400
    r = client.post("/api/records/smwd/preview", params={"biller": "STA MARIA WATER"})
    assert r.status_code == 200, r.text
    items = {i["reference"]: i for i in r.json()["items"]}
    assert set(items) == {"REF-CASH", "REF-GCASH", "REF-NOTYET", "REF-OLDPAY", "REF-DIFF", "REF-DOWN"}
    assert "20000000005" not in fake_site
    assert items["REF-CASH"]["matched"] and items["REF-CASH"]["smwd_reference"] == "04961602"
    assert items["REF-GCASH"]["matched"]
    assert items["REF-NOTYET"]["reason"] == "No payment found at SMWD yet"
    assert "before this bill" in items["REF-OLDPAY"]["reason"]
    assert items["REF-DIFF"]["reason"] == "Amount paid differs from this bill"
    assert "Couldn't reach" in items["REF-DOWN"]["reason"]

    ids = {ref: item["id"] for ref, item in items.items()}
    r = client.post("/api/records/smwd/apply", json={"channel": "CASH", "items": [
        {"id": ids["REF-CASH"], "reference": "04961602"}, {"id": ids["REF-GCASH"], "reference": "E8E0A4A2F0A2"}]})
    assert r.json() == {"applied": 2, "skipped": 0}
    with Session(shop.engine) as session:
        cash = session.exec(select(BillRecord).where(BillRecord.reference == "REF-CASH")).one()
        assert (cash.payment_reference, cash.payment_channel) == ("04961602", "CASH") and cash.settled_at
    # Applying again: no longer pending, so skipped; and the reference now counts as used.
    assert client.post("/api/records/smwd/apply", json={"items": [{"id": ids["REF-CASH"], "reference": "X"}]}).json()["skipped"] == 1
    add(shop, "20140722010", 1075.10, "REF-CASH2", days_ago=1)
    again = {i["reference"]: i for i in client.post("/api/records/smwd/preview", params={"biller": "STA MARIA WATER"}).json()["items"]}
    assert again["REF-CASH2"]["reason"] == "Reference already on bill REF-CASH"
