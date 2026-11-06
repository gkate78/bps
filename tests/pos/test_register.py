"""The shop register inside BPS: sales, loading, GCash/Maya, job orders, voids, summary, settings."""
from tests.conftest import ADMIN_PIN, CUSTOMER_PHONE, CUSTOMER_PIN, ENCODER_PHONE, ENCODER_PIN


def test_signed_out_and_customers_are_kept_out(shop):
    client = shop.client
    client.post("/auth/logout")
    assert client.get("/pos", follow_redirects=False).headers["location"] == "/auth/signin"
    assert client.post("/pos/api/sales", json={"lines": []}).status_code == 401
    shop.add_user(CUSTOMER_PHONE, CUSTOMER_PIN, "customer", "JUAN")
    shop.sign_in(CUSTOMER_PHONE, CUSTOMER_PIN)
    assert client.get("/pos", follow_redirects=False).status_code == 403
    assert client.post("/pos/api/sales", json={"lines": []}).status_code == 403
    assert "Shop register" not in client.get("/customer/dashboard").text


def test_bps_pages_link_to_the_register(shop):
    page = shop.client.get("/dashboard").text
    assert "Shop register" in page
    assert 'href="/dashboard"' in shop.client.get("/pos").text  # and back to Bills


def test_receipt_uses_bps_business_profile(shop):
    sale = shop.client.post(
        "/pos/api/sales", json={"lines": [{"kind": "service", "service_id": 1, "qty": 1, "unit_price": "5"}], "cash": "5"}
    ).json()
    receipt = shop.client.get(f"/pos/receipt/sale/{sale['id']}").text
    assert "DITTO DIGITAL PRINTSHOP" in receipt and "SAMPLE ADDRESS" in receipt
    assert "THIS IS NOT AN OFFICIAL RECEIPT" in receipt


def ids():
    """Service/network/wallet ids from the seeded defaults (ids follow seed order)."""
    return {"PRINTING": 1, "ID PICTURE": 4, "TARPAULIN": 6, "INVITATIONS": 7, "GLOBE": 1, "GCASH": 1, "MAYA": 2}


def test_shop_sale_with_services_and_load(shop):
    client = shop.client
    i = ids()
    body = {
        "lines": [
            {"kind": "service", "service_id": i["ID PICTURE"], "description": "id package", "qty": 1, "unit_price": "80"},
            {"kind": "service", "service_id": i["ID PICTURE"], "description": "change attire", "qty": 1, "unit_price": "20"},
            {"kind": "service", "service_id": i["PRINTING"], "description": "a4 colored", "qty": 3, "unit_price": "15"},
            {"kind": "load", "network_id": i["GLOBE"], "wallet_id": i["GCASH"], "mobile_no": "09181112222", "amount": "59", "is_promo": True},
        ],
        "cash": "300",
        "bir_invoice_no": "0123",
    }
    r = client.post("/pos/api/sales", json=body)
    assert r.status_code == 200, r.text
    sale = r.json()
    # 80 + 20 + 45 + promo 59 -> 70 = 215; change 85
    assert sale["sale_no"] == "S-000001"
    assert sale["change_cents"] == 8_500

    receipt = client.get(f"/pos/receipt/sale/{sale['id']}")
    assert receipt.status_code == 200
    assert "THIS IS NOT AN OFFICIAL RECEIPT" in receipt.text
    assert "215.00" in receipt.text and "ID PACKAGE" in receipt.text and "INVOICE NO. 0123" in receipt.text

    s = client.get("/pos/summary").text
    # income: services 145 + load income 11 (₱10 fee + ₱1 rounding)
    assert "₱156.00" in s
    # GCash balance went down by the actual promo price
    assert "-₱59.00" in s

    # Admin → Database shows the register's tables, amounts in pesos.
    db_view = client.get("/admin/database?table=pos_sales").text
    assert "Shop Sales" in db_view and "S-000001" in db_view and "215.00" in db_view and "total_cents" not in db_view
    assert "A4 COLORED" in client.get("/admin/database?table=pos_sale_lines").text


def test_shop_sale_paid_via_gcash(shop):
    client = shop.client
    i = ids()
    line = {"kind": "service", "service_id": i["PRINTING"], "qty": 4, "unit_price": "25"}
    # reference is required
    r = client.post("/pos/api/sales", json={"lines": [line], "payment_method": "wallet", "pay_wallet_id": i["GCASH"]})
    assert r.status_code == 400 and "reference" in r.json()["detail"]
    r = client.post(
        "/pos/api/sales",
        json={"lines": [line], "payment_method": "wallet", "pay_wallet_id": i["GCASH"], "payment_reference": "gc999"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["change_cents"] == 0
    receipt = client.get(f"/pos/receipt/sale/{r.json()['id']}").text
    assert "PAID VIA GCASH" in receipt and "REF GC999" in receipt and "CHANGE" not in receipt

    s = client.get("/pos/summary").text
    assert "Shop payments received via GCASH" in s
    # GCash balance went up by ₱100; the drawer didn't move
    assert "₱100.00" in s
    assert "Cash drawer change</span>\n        <strong>₱0.00" in s
    assert "paid via GCASH ref GC999" in client.get("/pos/sales").text


def test_suggestions_from_past_sales(shop):
    client = shop.client
    i = ids()

    def sell(desc, price, status_void=False):
        r = client.post(
            "/pos/api/sales",
            json={"lines": [{"kind": "service", "service_id": i["ID PICTURE"], "description": desc, "qty": 1, "unit_price": price}], "cash": "500"},
        )
        if status_void:
            client.post(f"/pos/api/sales/{r.json()['id']}/void", json={"reason": "test", "admin_pin": ADMIN_PIN})

    sell("pds package", "100")
    sell("id package", "80")
    sell("id package", "85")  # latest price wins
    sell("pds pakage", "100", status_void=True)  # voided sales aren't suggested
    sell("50% off promo", "40")

    r = client.get(f"/pos/api/suggest/service?service_id={i['ID PICTURE']}&q=")
    assert [s["description"] for s in r.json()][:1] == ["ID PACKAGE"]  # most used first
    assert r.json()[0]["price_cents"] == 8_500
    assert "PDS PAKAGE" not in [s["description"] for s in r.json()]
    assert [s["description"] for s in client.get(f"/pos/api/suggest/service?service_id={i['ID PICTURE']}&q=pd").json()] == ["PDS PACKAGE"]
    # % is matched literally, not as a wildcard
    assert [s["description"] for s in client.get(f"/pos/api/suggest/service?service_id={i['ID PICTURE']}&q=50%").json()] == ["50% OFF PROMO"]
    assert client.get(f"/pos/api/suggest/service?service_id={i['PRINTING']}&q=").json() == []

    client.post(
        "/pos/api/sales",
        json={"lines": [{"kind": "load", "network_id": i["GLOBE"], "wallet_id": i["GCASH"], "mobile_no": "09181112222", "amount": "100"}],
              "cash": "200", "customer_name": "juan"},
    )
    client.post(
        "/pos/api/wallet-txns",
        json={"kind": "cash_in", "wallet_id": i["GCASH"], "amount": "500", "customer_mobile": "09181113333", "customer_name": "maria", "reference": "r1"},
    )
    found = client.get("/pos/api/suggest/mobile?q=0918111").json()
    assert {m["mobile"]: (m["name"], m["network_id"]) for m in found} == {
        "09181112222": ("JUAN", i["GLOBE"]),
        "09181113333": ("MARIA", None),
    }
    assert found[0]["mobile"] == "09181113333"  # newest first
    assert client.get("/pos/api/suggest/mobile?q=09").json() == []  # needs 3+ digits
    assert client.get("/pos/api/suggest/mobile?q=0918").json() != []


def test_sale_validation(shop):
    client = shop.client
    i = ids()
    line = {"kind": "service", "service_id": i["PRINTING"], "qty": 1, "unit_price": "10"}
    assert client.post("/pos/api/sales", json={"lines": [], "cash": "10"}).status_code == 400
    r = client.post("/pos/api/sales", json={"lines": [line], "cash": "5"})
    assert r.status_code == 400 and "less than the amount due" in r.json()["detail"]
    r = client.post("/pos/api/sales", json={"lines": [{**line, "unit_price": "1.234"}], "cash": "50"})
    assert r.status_code == 400
    bad_load = {"kind": "load", "network_id": i["GLOBE"], "wallet_id": i["GCASH"], "mobile_no": "12345", "amount": "50"}
    assert client.post("/pos/api/sales", json={"lines": [bad_load], "cash": "100"}).status_code == 400


def test_cash_in_and_cash_out(shop):
    client = shop.client
    i = ids()
    r = client.post(
        "/pos/api/wallet-txns",
        json={"kind": "cash_in", "wallet_id": i["GCASH"], "amount": "1000", "customer_mobile": "09181112222", "reference": "abc1", "tendered": "1100"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["change_cents"] == 8_000  # 1,100 - 1,020

    r = client.post(
        "/pos/api/wallet-txns",
        json={"kind": "cash_out", "wallet_id": i["MAYA"], "amount": "1000", "fee_mode": "deducted", "customer_mobile": "09181112222", "reference": "x2"},
    )
    assert r.json()["give_cents"] == 98_000

    r = client.post(
        "/pos/api/wallet-txns",
        json={"kind": "cash_out", "wallet_id": i["MAYA"], "amount": "1500", "fee_mode": "paid_in_cash", "customer_mobile": "09181112222", "reference": "x3"},
    )
    assert r.json()["give_cents"] == 150_000

    # reference is required
    r = client.post(
        "/pos/api/wallet-txns",
        json={"kind": "cash_in", "wallet_id": i["GCASH"], "amount": "100", "customer_mobile": "09181112222", "reference": " "},
    )
    assert r.status_code == 400

    receipt = client.get(f"/pos/receipt/wallet/3").text
    assert "FEE PAID IN CASH" in receipt and "1,500.00" in receipt

    s = client.get("/pos/summary").text
    # drawer: +1,020 - 980 - (1,500 - 40) = -1,420
    assert "-₱1,420.00" in s
    # fees: 20 + 20 + 40
    assert "₱80.00" in s


def test_cash_out_with_fee_included(shop):
    """Customer sends ₱6,120 to receive exactly ₱6,000: the fee is ₱120, not ₱130 on ₱6,120."""
    client = shop.client
    i = ids()
    q = client.get("/pos/api/quote/wallet", params={"kind": "cash_out", "amount": "6120", "fee_mode": "included"}).json()
    assert (q["fee_cents"], q["give_cents"]) == (12_000, 600_000)
    bad = client.get("/pos/api/quote/wallet", params={"kind": "cash_out", "amount": "6125", "fee_mode": "included"})
    assert bad.status_code == 400 and "Deduct from payout" in bad.json()["detail"]

    r = client.post(
        "/pos/api/wallet-txns",
        json={"kind": "cash_out", "wallet_id": i["GCASH"], "amount": "6120", "fee_mode": "included", "customer_mobile": "09181112222", "reference": "inc1"},
    )
    assert r.status_code == 200, r.text
    txn = r.json()
    assert txn["give_cents"] == 600_000
    receipt = client.get(f"/pos/receipt/wallet/{txn['id']}").text
    assert "FEE (INCLUDED)" in receipt and "6,120.00" in receipt and "-120.00" in receipt and "6,000.00" in receipt


def test_void_needs_admin_pin_and_drops_from_totals(shop):
    client = shop.client
    i = ids()
    # a BPS encoder works the register as a cashier
    shop.add_user(ENCODER_PHONE, ENCODER_PIN, "encoder", "ANA")
    shop.sign_in(ENCODER_PHONE, ENCODER_PIN)
    assert client.get("/pos").status_code == 200
    assert client.get("/pos/settings", follow_redirects=False).status_code == 403

    sale = client.post(
        "/pos/api/sales",
        json={"lines": [{"kind": "service", "service_id": i["PRINTING"], "qty": 2, "unit_price": "5"}], "cash": "10"},
    ).json()
    r = client.post(f"/pos/api/sales/{sale['id']}/void", json={"reason": "wrong item", "admin_pin": ENCODER_PIN})
    assert r.status_code == 400
    r = client.post(f"/pos/api/sales/{sale['id']}/void", json={"reason": "wrong item", "admin_pin": ADMIN_PIN})
    assert r.status_code == 200
    r = client.post(f"/pos/api/sales/{sale['id']}/void", json={"reason": "again", "admin_pin": ADMIN_PIN})
    assert r.status_code == 400

    s = client.get("/pos/summary").text
    assert "wrong item" in s.lower()
    assert "Approved by KATE TEST" in s
    listing = client.get("/pos/sales").text
    assert "VOIDED" in listing
    assert "VOIDED" in client.get(f"/pos/receipt/sale/{sale['id']}").text


def test_fee_settings_change_applies(shop):
    client = shop.client
    r = client.post(
        "/pos/settings/fees",
        data={
            "block": "1000", "block_fee": "25",
            "b_min": ["1", "500", ""], "b_max": ["499", "999", ""], "b_fee": ["15", "25", ""],
            "small_max": "50", "small_fee": "5", "promo_round": "10",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    q = client.get("/pos/api/quote/wallet?kind=cash_in&amount=1200").json()
    assert q["fee_cents"] == 4_000  # 25 + 15

    # a gap in the brackets is refused and the old fees stay
    client.post(
        "/pos/settings/fees",
        data={"block": "1000", "block_fee": "20", "b_min": ["1", "600"], "b_max": ["499", "999"], "b_fee": ["10", "20"],
              "small_max": "50", "small_fee": "5", "promo_round": "10"},
    )
    assert client.get("/pos/api/quote/wallet?kind=cash_in&amount=1200").json()["fee_cents"] == 4_000


def test_pages_render(shop):
    client = shop.client
    for path in ("/pos", "/pos/sales", "/pos/summary", "/pos/settings", "/pos/jobs", "/pos/eod", "/pos/eod?day=bad",
                 "/pos/sales?kind=wallet&q=x&start=2026-01-01&end=bad"):
        assert client.get(path).status_code == 200, path


def test_job_order_down_payment_then_balance(shop):
    client = shop.client
    i = ids()
    tarp = {"kind": "service", "service_id": i["TARPAULIN"], "description": "3x5 birthday", "qty": 1, "unit_price": "350"}
    invite = {"kind": "service", "service_id": i["INVITATIONS"], "description": "wedding", "qty": 50, "unit_price": "3"}
    job = {"lines": [tarp, invite], "is_job_order": True, "customer_name": "ana cruz", "customer_phone": "09170001111"}

    # validation
    assert client.post("/pos/api/sales", json={**job, "down_payment": "500", "cash": "500"}).status_code == 400  # = total
    assert client.post("/pos/api/sales", json={**job, "customer_name": "", "down_payment": "200", "cash": "200"}).status_code == 400
    load = {"kind": "load", "network_id": i["GLOBE"], "wallet_id": i["GCASH"], "mobile_no": "09181112222", "amount": "50"}
    r = client.post("/pos/api/sales", json={**job, "lines": [tarp, load], "down_payment": "100", "cash": "100"})
    assert r.status_code == 400 and "Load" in r.json()["detail"]

    # total 350 + 150 = 500; down payment 200 from 250 cash
    r = client.post("/pos/api/sales", json={**job, "down_payment": "200", "cash": "250", "promised_date": "2026-11-10"})
    assert r.status_code == 200, r.text
    sale = r.json()
    assert (sale["change_cents"], sale["balance_cents"]) == (5_000, 30_000)
    receipt = client.get(f"/pos/receipt/sale/{sale['id']}").text
    assert "JOB ORDER" in receipt and "DOWN PAYMENT" in receipt and "300.00" in receipt and "READY ON 11/10/2026" in receipt

    jobs = client.get("/pos/jobs").text
    assert "ANA CRUZ" in jobs and "In progress" in jobs and "₱300.00" in jobs
    assert client.post(f"/pos/api/sales/{sale['id']}/job-status", json={"status": "ready"}).status_code == 200
    assert "Ready for pickup" in client.get("/pos/jobs").text

    # part of the balance via GCash, the rest in cash
    r = client.post(f"/pos/api/sales/{sale['id']}/payments", json={"amount": "100", "payment_method": "wallet", "pay_wallet_id": i["GCASH"]})
    assert r.status_code == 400  # reference required
    r = client.post(
        f"/pos/api/sales/{sale['id']}/payments",
        json={"amount": "100", "payment_method": "wallet", "pay_wallet_id": i["GCASH"], "payment_reference": "gc1"},
    )
    gcash_payment = r.json()
    assert gcash_payment["balance_cents"] == 20_000
    assert client.post(f"/pos/api/sales/{sale['id']}/payments", json={"amount": "250", "cash": "500"}).status_code == 400  # over balance
    r = client.post(f"/pos/api/sales/{sale['id']}/payments", json={"cash": "500"})  # blank amount = full balance
    assert r.json()["balance_cents"] == 0 and r.json()["change_cents"] == 30_000
    assert client.post(f"/pos/api/sales/{sale['id']}/payments", json={"cash": "500"}).status_code == 400  # already paid
    assert "ANA CRUZ" not in client.get("/pos/jobs").text  # no longer open
    assert "ANA CRUZ" in client.get("/pos/jobs?show=completed").text

    pay_receipt = client.get(f"/pos/receipt/payment/{r.json()['id']}").text
    assert "PREVIOUSLY PAID" in pay_receipt and "300.00" in pay_receipt and "FULLY PAID" in pay_receipt

    s = client.get("/pos/summary").text
    assert "Down payments received" in s and "Balances collected" in s
    # drawer: 200 down + 200 cash balance; GCash +100
    assert "Cash drawer change</span>\n        <strong>₱400.00" in s
    assert "Shop payments received via GCASH" in s
    listing = client.get("/pos/sales").text
    assert "Job order payment" in listing and "Balance payment for S-000001" in listing

    # voiding the GCash payment puts ₱100 back on the balance
    r = client.post(f"/pos/api/payments/{gcash_payment['id']}/void", json={"reason": "wrong ref", "admin_pin": ADMIN_PIN})
    assert r.status_code == 200
    jobs = client.get("/pos/jobs").text
    assert "ANA CRUZ" in jobs and "₱100.00" in jobs and "Ready for pickup" in jobs

    # voiding the job order voids its remaining payments too
    r = client.post(f"/pos/api/sales/{sale['id']}/void", json={"reason": "cancelled", "admin_pin": ADMIN_PIN})
    assert r.status_code == 200
    assert "ANA CRUZ" not in client.get("/pos/jobs?show=all").text
    s = client.get("/pos/summary").text
    assert "Cash drawer change</span>\n        <strong>₱0.00" in s
    assert client.post(f"/pos/api/sales/{sale['id']}/payments", json={"cash": "100"}).status_code == 400


def test_rename_service_keeps_old_sales(shop):
    client = shop.client
    i = ids()
    client.post("/pos/api/sales", json={"lines": [{"kind": "service", "service_id": i["TARPAULIN"], "qty": 1, "unit_price": "100"}], "cash": "100"})
    r = client.post(f"/pos/settings/services/{i['TARPAULIN']}/rename", data={"name": "tarp printing"}, follow_redirects=False)
    assert r.status_code == 303
    assert "TARP PRINTING" in client.get("/pos").text
    assert "TARPAULIN" in client.get("/pos/receipt/sale/1").text  # old sale keeps its name
    r = client.post(f"/pos/settings/services/{i['TARPAULIN']}/rename", data={"name": "printing"})  # name taken
    assert "PRINTING already exists" in r.text


def test_maya_load_discount(shop):
    """Maya deducts ₱96.03 for a ₱99 load (3% off); the wallet and income use what was deducted."""
    client = shop.client
    i = ids()
    q = client.get(f"/pos/api/quote/load?amount=99&promo=true&wallet_id={i['MAYA']}").json()
    assert q["cost_cents"] == 9_603 and q["total_cents"] == 11_000  # ₱99 promo → ₱100 + ₱10 fee
    assert client.get(f"/pos/api/quote/load?amount=99&promo=true&wallet_id={i['GCASH']}").json()["cost_cents"] == 9_900

    load = {"kind": "load", "network_id": i["GLOBE"], "wallet_id": i["MAYA"], "mobile_no": "09181112222", "amount": "99", "is_promo": True}
    assert client.post("/pos/api/sales", json={"lines": [load], "cash": "110"}).status_code == 200
    # The app showed a different amount once: typed in, it's used instead.
    assert client.post("/pos/api/sales", json={"lines": [{**load, "deducted": "96.50"}], "cash": "110"}).status_code == 200
    bad = client.post("/pos/api/sales", json={"lines": [{**load, "deducted": "120"}], "cash": "110"})
    assert bad.status_code == 400 and "not more than the load" in bad.text

    s = client.get("/pos/summary").text
    assert "₱192.53" in s  # deducted: 96.03 + 96.50
    assert "₱27.47" in s  # load income: 220 - 192.53
    assert "-₱192.53" in s  # Maya balance

    # Discounts are set per account in Settings.
    r = client.post("/pos/settings/wallets/discounts", data={f"discount_{i['GCASH']}": "2.5", f"discount_{i['MAYA']}": "3"})
    assert "Discounts saved" in r.text
    assert client.get(f"/pos/api/quote/load?amount=100&wallet_id={i['GCASH']}").json()["cost_cents"] == 9_750
    assert "from 0 to 49.99" in client.post("/pos/settings/wallets/discounts", data={f"discount_{i['MAYA']}": "abc"}).text
