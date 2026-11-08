"""Cash is collected to the whole peso: under 50 centavos rounds down, 50 and up rounds up.
₱1,025.45 paid with ₱1,100 gets ₱75 change; ₱1,025.50 gets ₱74. GCash/Maya stay exact."""
from datetime import date, timedelta

from app.controllers.bill_controller import cash_to_collect
from app.models import BillerRule
from pos.money import cash_due_cents

TODAY = date.today()


def test_rounding_rule():
    assert cash_due_cents(102_545) == 102_500
    assert cash_due_cents(102_549) == 102_500
    assert cash_due_cents(102_550) == 102_600
    assert cash_due_cents(102_500) == 102_500
    assert cash_to_collect(1025.45, "CASH") == 1025 and cash_to_collect(1025.50, None) == 1026
    assert cash_to_collect(1025.45, "GCASH") == 1025.45


def new_bill(bill_amt: float, cash: float, method: str = "CASH", account: str = "1234567890") -> dict:
    return {
        "account": account,
        "biller": "MERALCO",
        "customer_name": "JUAN DELA CRUZ",
        "cp_number": "09171234567",
        "bill_amt": bill_amt,
        "cash": cash,
        "payment_method": method,
        "due_date": (TODAY + timedelta(days=5)).isoformat(),
    }


def test_bill_change_is_to_the_whole_peso(shop):
    shop.add(BillerRule(biller="MERALCO", service_charge=15))
    client = shop.client
    down = client.post("/api/records", json=new_bill(1010.45, 1100)).json()
    assert down["total"] == 1025.45 and down["change_amt"] == 75
    up = client.post("/api/records", json=new_bill(1010.50, 1100, account="1234567891")).json()
    assert up["total"] == 1025.50 and up["change_amt"] == 74
    exact = client.post("/api/records", json=new_bill(1010.45, 1025, account="1234567892")).json()
    assert exact["change_amt"] == 0
    # Paid through GCash: no rounding.
    gcash = client.post("/api/records", json=new_bill(1010.45, 1025.45, "GCASH", account="1234567893")).json()
    assert gcash["change_amt"] == 0

    # The drawer expects what was actually collected: 1,025 + 1,026 + 1,025 (the GCash bill isn't cash).
    page = client.get("/pos/eod").text
    assert "₱3,076.00" in page


def test_register_cash_change_is_to_the_whole_peso(shop):
    client = shop.client
    line = {"kind": "service", "service_id": 1, "qty": 1}
    down = client.post("/pos/api/sales", json={"lines": [{**line, "unit_price": "1025.45"}], "cash": "1025"})
    assert down.status_code == 200, down.text
    assert down.json()["change_cents"] == 0
    up = client.post("/pos/api/sales", json={"lines": [{**line, "unit_price": "1025.50"}], "cash": "1100"})
    assert up.json()["change_cents"] == 7_400
    short = client.post("/pos/api/sales", json={"lines": [{**line, "unit_price": "1025.50"}], "cash": "1025"})
    assert short.status_code == 400 and "1,026.00" in short.json()["detail"]

    # Drawer: ₱1,025 + ₱1,026 went in.
    day = TODAY.isoformat()
    r = client.post(f"/pos/api/eod/{day}", json={"opening_cash": "0", "counted_cash": "2051", "wallets": []})
    assert r.status_code == 200, r.text
    assert r.json() == {"expected_cash_cents": 205_100, "difference_cents": 0}


def test_job_order_balance_cash_is_to_the_whole_peso(shop):
    client = shop.client
    sale = client.post(
        "/pos/api/sales",
        json={
            "lines": [{"kind": "service", "service_id": 6, "qty": 1, "unit_price": "500.45"}],
            "is_job_order": True,
            "customer_name": "JUAN",
            "down_payment": "200",
            "cash": "200",
        },
    ).json()
    r = client.post(f"/pos/api/sales/{sale['id']}/payments", json={"cash": "300"})
    assert r.status_code == 200, r.text
    assert r.json()["change_cents"] == 0  # balance ₱300.45 is collected as ₱300
