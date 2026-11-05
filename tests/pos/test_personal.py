"""Admin's personal transactions: no service charge or fees; paid like a customer, or from shop funds."""
from datetime import date, timedelta

from app.models import BillerRule
from tests.conftest import ENCODER_PHONE, ENCODER_PIN

TODAY = date.today()
GLOBE, GCASH = 1, 1


def new_bill(**extra) -> dict:
    return {
        "account": "1234567890",
        "biller": "MERALCO",
        "customer_name": "KATE TEST",
        "cp_number": "09171234567",
        "bill_amt": 1000,
        "cash": 1000,
        "payment_method": "CASH",
        "due_date": (TODAY + timedelta(days=5)).isoformat(),
        **extra,
    }


def load(amount: str, **extra) -> dict:
    return {"kind": "load", "network_id": GLOBE, "wallet_id": GCASH, "mobile_no": "09181112222", "amount": amount, **extra}


def test_personal_bill_has_no_service_charge(shop):
    shop.add(BillerRule(biller="MERALCO", service_charge=15))
    client = shop.client
    assert 'id="personal"' in client.get("/entry/form").text
    register = client.get("/pos").text
    assert 'name="personal"' in register and 'name="w_personal"' in register
    assert "/pos/static/js/register.js?v=" in register  # so an update isn't run from an old cached script
    assert "/static/js/entry_form.js?v=" in client.get("/entry/form").text

    paid =client.post("/api/records", json=new_bill(personal="paid"))
    assert paid.status_code == 201, paid.text
    assert paid.json()["charge"] == 0 and paid.json()["total"] == 1000 and paid.json()["change_amt"] == 0

    shop_funds = client.post("/api/records", json=new_bill(account="1234567891", personal="shop", cash=0)).json()
    assert shop_funds["charge"] == 0 and shop_funds["cash"] == 0 and shop_funds["payment_method"] is None
    assert "FROM SHOP FUNDS" in client.get(f"/api/records/{shop_funds['id']}/receipt").text

    # Later edits keep it free of a service charge.
    edited = client.put(f"/api/records/{shop_funds['id']}", json={"bill_amt": 1200}).json()
    assert edited["charge"] == 0 and edited["total"] == 1200 and edited["personal"] == "shop"

    # Customer bills still get the charge.
    normal = client.post("/api/records", json=new_bill(account="1234567892", cash=1015)).json()
    assert normal["charge"] == 15 and normal["personal"] is None


def test_only_admins_can_enter_personal_transactions(shop):
    shop.add(BillerRule(biller="MERALCO", service_charge=15))
    shop.add_user(ENCODER_PHONE, ENCODER_PIN, "encoder", "ANA")
    shop.sign_in(ENCODER_PHONE, ENCODER_PIN)
    client = shop.client
    assert client.post("/api/records", json=new_bill(personal="paid")).status_code == 403
    r = client.post("/pos/api/sales", json={"lines": [load("100")], "personal": "shop"})
    assert r.status_code == 400 and "admin" in r.json()["detail"]
    r = client.post(
        "/pos/api/wallet-txns",
        json={"kind": "cash_in", "wallet_id": GCASH, "amount": "500", "customer_mobile": "09181112222", "reference": "X", "personal": "paid"},
    )
    assert r.status_code == 400
    assert 'name="personal"' not in client.get("/pos").text
    assert 'id="personal"' not in client.get("/entry/form").text


def test_personal_sale_loads_without_fees(shop):
    client = shop.client
    assert client.get("/pos/api/quote/load?amount=59&promo=true&personal=true").json()["total_cents"] == 5_900

    paid = client.post("/pos/api/sales", json={"lines": [load("59", is_promo=True)], "cash": "100", "personal": "paid"})
    assert paid.status_code == 200, paid.text
    assert paid.json()["change_cents"] == 4_100  # ₱59, no fee and no promo rounding

    r = client.post("/pos/api/sales", json={"lines": [load("100")], "personal": "paid", "is_job_order": True, "customer_name": "X", "down_payment": "10"})
    assert r.status_code == 400


def test_personal_from_shop_funds_in_summary_and_end_of_day(shop):
    shop.add(BillerRule(biller="MERALCO", service_charge=15))
    client = shop.client
    printing = {"kind": "service", "service_id": 1, "qty": 1}

    # A customer sale (₱100 cash), then the admin's own from shop funds: ₱200 printing, a ₱100 load,
    # a ₱500 GCash cash-in and a ₱1,000 bill. None of it brings cash in.
    client.post("/pos/api/sales", json={"lines": [{**printing, "unit_price": "100"}], "cash": "100"})
    sale = client.post("/pos/api/sales", json={"lines": [{**printing, "unit_price": "200"}, load("100")], "personal": "shop"})
    assert sale.status_code == 200, sale.text
    receipt = client.get(f"/pos/receipt/sale/{sale.json()['id']}").text
    assert "FROM SHOP FUNDS" in receipt and "CHANGE" not in receipt
    txn = client.post(
        "/pos/api/wallet-txns",
        json={"kind": "cash_in", "wallet_id": GCASH, "amount": "500", "customer_mobile": "09171234567", "reference": "GC9", "personal": "shop"},
    )
    assert txn.status_code == 200, txn.text
    assert txn.json()["change_cents"] == 0
    assert client.post("/api/records", json=new_bill(personal="shop", cash=0)).status_code == 201

    # A personal cash-out can't come from shop funds.
    r = client.post(
        "/pos/api/wallet-txns",
        json={"kind": "cash_out", "wallet_id": GCASH, "amount": "500", "customer_mobile": "09171234567", "reference": "GC10", "personal": "shop"},
    )
    assert r.status_code == 400

    summary = client.get("/pos/summary").text
    assert "Personal (admin) from shop funds: 2 transactions, ₱800.00" in summary  # 200 + 100 load + 500 cash-in

    day = TODAY.isoformat()
    r = client.post(f"/pos/api/eod/{day}", json={"opening_cash": "0", "counted_cash": "100", "wallets": [{"wallet_id": GCASH, "opening": "1000"}]})
    # Only the customer's ₱100 is in the drawer.
    assert r.json() == {"expected_cash_cents": 10_000, "difference_cents": 0}
    page = client.get("/pos/eod").text
    assert "3 personal (admin) transactions paid from shop funds (₱1,800.00)" in page
    # GCash: 1,000 - 100 load - 500 cash-in = 400
    assert "₱400.00" in page
