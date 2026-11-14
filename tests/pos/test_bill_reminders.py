"""A bill paid twice to the biller (noted DOUBLE PAYMENT) reminds the cashier on the account's next bill."""
from datetime import date, datetime, timedelta

from app.models import BillerRule, BillRecord

TODAY = date.today()
DUE = (TODAY + timedelta(days=5)).isoformat()


def setup(shop):
    shop.add(BillerRule(biller="MERALCO", service_charge=15), BillerRule(biller="STA MARIA WATER", service_charge=15))
    earlier = TODAY - timedelta(days=10)
    shop.add(BillRecord(txn_datetime=datetime.combine(earlier, datetime.min.time()), txn_date=earlier, account="1980595543",
                        biller="MERALCO", customer_name="ADRIANO FLORITA", cp_number="09358135809", bill_amt=2684.73,
                        total=2734.73, cash=2734.73, reference="REF-DOUBLE", payment_reference="R793",
                        notes="DOUBLE PAYMENT VIA BPICC R79396995740419603"),
             BillRecord(txn_datetime=datetime.combine(earlier, datetime.min.time()), txn_date=earlier, account="5555555555",
                        biller="MERALCO", customer_name="OTHER", cp_number="09170000000", bill_amt=100, total=115,
                        reference="REF-NOTE", notes="15.00"))


def reminders(client, **params):
    r = client.get("/pos/api/bills/reminders", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_reminder_by_account_or_phone_until_paid_back(shop):
    setup(shop)
    client = shop.client
    (r,) = reminders(client, account="1980595543")
    assert r["reference"] == "REF-DOUBLE" and r["bill_amt"] == 2684.73 and "BPICC R79396995740419603" in r["notes"]
    # The same customer paying another biller: found by the CP number.
    assert [x["reference"] for x in reminders(client, account="20190937068", phone="09358135809")] == ["REF-DOUBLE"]
    # Other notes aren't reminders; nothing typed yet, nothing found.
    assert reminders(client, account="5555555555") == []
    assert reminders(client, phone="0935") == [] and reminders(client) == []

    # Saving the account's next bill doesn't clear it: only paying it back does.
    bill = {"account": "1980595543", "biller": "MERALCO", "customer_name": "adriano florita",
            "cp_number": "09358135809", "due_date": DUE, "bill_amt": "1000"}
    assert client.post("/pos/api/bills", json={"bills": [bill], "cash": "1015"}).status_code == 200
    assert len(reminders(client, account="1980595543")) == 1


def payback(reference="REF-DOUBLE") -> dict:
    return {"kind": "payback", "reference": reference}


def test_paid_back_with_the_next_bill(shop):
    setup(shop)
    client = shop.client
    bill = {"kind": "bill", "qty": 1, "bill": {"account": "1980595543", "biller": "MERALCO", "customer_name": "adriano florita",
                                                "cp_number": "09358135809", "due_date": DUE, "bill_amt": "1000"}}
    # ₱1,015 bill + ₱2,684.73 paid back = ₱3,699.73 → ₱3,700 in cash
    assert client.post("/pos/api/sales", json={"lines": [bill, payback()], "cash": "3699"}).status_code == 400
    r = client.post("/pos/api/sales", json={"lines": [bill, payback()], "cash": "3700"})
    assert r.status_code == 200, r.text
    sale = r.json()
    assert sale["change_cents"] == 0
    assert reminders(client, account="1980595543") == [] and reminders(client, phone="09358135809") == []

    receipt = client.get(f"/pos/receipt/sale/{sale['id']}").text
    assert "DOUBLE PAYMENT PAID BACK" in receipt and "REF-DOUBLE" in receipt and "2,684.73" in receipt

    # Received in the drawer, not income.
    page = client.get("/pos/summary").text
    assert "Double payments paid back by customers: 1, ₱2,684.73" in page
    assert "Shop ₱0.00 (services" in page  # not shop income

    # Only once; and only for a bill noted as a double payment.
    r = client.post("/pos/api/sales", json={"lines": [payback()], "cash": "3000"})
    assert r.status_code == 400 and "already paid back" in r.json()["detail"]
    r = client.post("/pos/api/sales", json={"lines": [payback("REF-NOTE")], "cash": "200"})
    assert r.status_code == 400 and "isn't noted as a double payment" in r.json()["detail"]
    r = client.post("/pos/api/sales", json={"lines": [payback("NOPE")], "cash": "200"})
    assert r.status_code == 400 and "not found" in r.json()["detail"]


def test_payback_alone_and_voided(shop):
    setup(shop)
    client = shop.client
    r = client.post("/pos/api/sales", json={"lines": [payback(), payback()], "cash": "6000"})
    assert r.status_code == 400 and "already paid back" in r.json()["detail"]
    r = client.post("/pos/api/sales", json={"lines": [payback()], "is_job_order": True, "customer_name": "X", "down_payment": "1"})
    assert r.status_code == 400 and "job order" in r.json()["detail"]
    r = client.post("/pos/api/sales", json={"lines": [payback()], "cash": "2685"})  # ₱2,684.73 → ₱2,685
    assert r.status_code == 200, r.text
    assert reminders(client, account="1980595543") == []
    # Voiding the sale brings the reminder back.
    from tests.conftest import ADMIN_PIN
    assert client.post(f"/pos/api/sales/{r.json()['id']}/void", json={"reason": "wrong", "admin_pin": ADMIN_PIN}).status_code == 200
    assert len(reminders(client, account="1980595543")) == 1


def test_reminders_need_a_signed_in_cashier(shop):
    shop.client.post("/auth/logout")
    assert shop.client.get("/pos/api/bills/reminders?account=1").status_code == 401
