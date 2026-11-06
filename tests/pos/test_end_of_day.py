"""End of day: one count for bills and shop, and bill settlements by settled_at + payment_channel."""
from datetime import date, datetime, timedelta

from app.models import BillRecord
from tests.conftest import ADMIN_PHONE, ADMIN_PIN, ENCODER_PHONE, ENCODER_PIN

TODAY = date.today()


def bill(total: float, charge: float, method: str = "CASH", **extra) -> BillRecord:
    fields = {
        "txn_datetime": datetime.now(),
        "txn_date": TODAY,
        "account": "1234567890",
        "biller": "MERALCO",
        "customer_name": "JUAN DELA CRUZ",
        "cp_number": "09181112222",
        "bill_amt": total - charge,
        "charge": charge,
        "total": total,
        "cash": total,
        "due_date": TODAY + timedelta(days=5),
        "payment_method": method,
    }
    return BillRecord(**{**fields, **extra})


def test_settled_at_is_stamped_when_a_bill_is_paid_to_the_biller(shop):
    record = shop.add(bill(1015, 15))
    assert record.settled_at is None
    r = shop.client.put(f"/api/records/{record.id}", json={"payment_reference": "MER-1", "payment_channel": "CASH"})
    assert r.status_code == 200, r.text
    first = shop.client.get(f"/api/records/{record.id}").json()
    with shop.engine.connect() as conn:
        settled_at = conn.exec_driver_sql(f"SELECT settled_at FROM bill_records WHERE id = {record.id}").scalar()
    assert settled_at is not None and first["payment_reference"] == "MER-1"

    # Editing other fields keeps the time; clearing the reference clears it.
    shop.client.put(f"/api/records/{record.id}", json={"notes": "checked"})
    with shop.engine.connect() as conn:
        assert conn.exec_driver_sql(f"SELECT settled_at FROM bill_records WHERE id = {record.id}").scalar() == settled_at
    shop.client.put(f"/api/records/{record.id}", json={"payment_reference": ""})
    with shop.engine.connect() as conn:
        assert conn.exec_driver_sql(f"SELECT settled_at FROM bill_records WHERE id = {record.id}").scalar() is None


def test_end_of_day_one_count_for_bills_and_shop(shop):
    client = shop.client
    now = datetime.now()
    # Bills: ₱1,015 cash (₱15 charge), ₱510 paid by the customer through GCash (₱10 charge).
    # Settled today: the cash bill in cash, the GCash bill from GCash, and an older bill through Bayad.
    shop.add(
        bill(1015, 15, payment_reference="R1", payment_channel="CASH", settled_at=now),
        bill(510, 10, "GCASH", payment_reference="R2", payment_channel="GCASH", settled_at=now),
        bill(2015, 15, payment_reference="R3", payment_channel="BAYAD", settled_at=now, txn_date=TODAY - timedelta(days=1)),
        bill(300, 10),  # collected today, not yet paid to the biller
    )
    client.post("/pos/settings/business", data={"receipt_footer": "THANK YOU", "default_starting_cash": "1000"})

    # Shop: ₱100 printing in cash, ₱50 printing paid via Maya, a ₱100 Globe load from GCash (₱110 cash),
    # and a ₱1,000 GCash cash-in (₱1,020 cash).
    printing = {"kind": "service", "service_id": 1, "qty": 1}
    assert client.post("/pos/api/sales", json={"lines": [{**printing, "unit_price": "100"}], "cash": "100"}).status_code == 200
    client.post(
        "/pos/api/sales",
        json={"lines": [{**printing, "unit_price": "50"}], "payment_method": "wallet", "pay_wallet_id": 2, "payment_reference": "MY1"},
    )
    client.post(
        "/pos/api/sales",
        json={"lines": [{"kind": "load", "network_id": 1, "wallet_id": 1, "mobile_no": "09181112222", "amount": "100"}], "cash": "110"},
    )
    client.post(
        "/pos/api/wallet-txns",
        json={"kind": "cash_in", "wallet_id": 1, "amount": "1000", "customer_mobile": "09181112222", "reference": "GC1"},
    )

    # Cash movements: ₱300 owner pickup, ₱500 moved into GCash.
    day = TODAY.isoformat()
    assert client.post(f"/pos/api/eod/{day}/movements", json={"kind": "take_out", "amount": "300", "reason": "owner pickup"}).status_code == 200
    assert client.post(f"/pos/api/eod/{day}/movements", json={"kind": "to_wallet", "amount": "500", "reason": "top up", "wallet_id": 1}).status_code == 200
    assert client.post(f"/pos/api/eod/{day}/movements", json={"kind": "take_out", "amount": "50", "reason": ""}).status_code == 400

    page = client.get("/pos/eod").text
    # Drawer lines: bills in cash 1,315 (1,015 + 300), shop cash 210 (100 + 110 load), cash-in 1,020,
    # bill paid to the biller in cash -1,000, owner pickup -300, moved to GCash -500.
    assert "₱1,315.00" in page and "₱210.00" in page and "₱1,020.00" in page and "-₱1,000.00" in page
    assert "BAYAD" in page and "₱2,000.00" in page  # other channels, for reference
    assert "not yet paid to the billers (₱290.00)" in page

    r = client.post(
        f"/pos/api/eod/{day}",
        json={
            "opening_cash": "1000",
            "counted_cash": "1745",
            "wallets": [{"wallet_id": 1, "opening": "2000", "counted": "1400"}, {"wallet_id": 2, "opening": "0", "counted": "50"}],
        },
    )
    assert r.status_code == 200, r.text
    # 1,000 + 1,315 + 210 + 1,020 - 1,000 - 300 - 500 = 1,745
    assert r.json() == {"expected_cash_cents": 174_500, "difference_cents": 0}

    page = client.get("/pos/eod").text
    assert "Saved by KATE TEST" in page and "balanced" in page
    # GCash: 2,000 + 510 bill - 1,000 cash-in - 100 load - 500 bill settled + 500 moved = 1,410 (counted 1,400)
    assert "₱1,410.00" in page
    # Maya: 0 + 50 shop sale
    assert "₱50.00" in page

    # The next day starts from the counted wallet balances.
    tomorrow = client.get(f"/pos/eod?day={(TODAY + timedelta(days=1)).isoformat()}").text
    assert 'value="1400"' in tomorrow

    # Only an admin can remove a cash movement.
    assert client.post("/pos/api/cash-movements/1/void").status_code == 200
    assert "-₱300.00" not in client.get("/pos/eod").text


def test_encoder_does_a_blind_closing_count(shop):
    client = shop.client
    day = TODAY.isoformat()
    # the admin sets the starting cash and the GCash opening balance
    client.post(f"/pos/api/eod/{day}", json={"opening_cash": "1000", "wallets": [{"wallet_id": 1, "opening": "2000"}]})

    shop.add_user(ENCODER_PHONE, ENCODER_PIN, "encoder", "ANA")
    shop.sign_in(ENCODER_PHONE, ENCODER_PIN)
    assert client.get("/pos/summary", follow_redirects=False).status_code == 403
    page = client.get("/pos/eod").text
    assert 'href="/pos/summary"' not in page
    assert "Closing count" in page and "Cash counted in the drawer" in page
    assert "Expected cash in the drawer" not in page and 'name="opening_cash"' not in page
    assert "GCASH balance" in page and "₱2,000.00" in page  # expected wallet balance is shown
    # other days are the admin's
    assert "Closing count for" in client.get(f"/pos/eod?day={(TODAY - timedelta(days=1)).isoformat()}").text
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    assert client.post(f"/pos/api/eod/{yesterday}", json={"counted_cash": "1"}).status_code == 403

    # saving changes only the counts, and doesn't reveal the expected cash
    r = client.post(
        f"/pos/api/eod/{day}",
        json={"opening_cash": "5", "counted_cash": "990", "wallets": [{"wallet_id": 1, "opening": "5", "counted": "1990"}]},
    )
    assert r.status_code == 200 and r.json() == {"ok": True}
    page = client.get("/pos/eod").text
    assert "short" not in page and "over " not in page

    shop.sign_in(ADMIN_PHONE, ADMIN_PIN)
    page = client.get("/pos/eod").text
    assert 'name="opening_cash" inputmode="decimal" value="1000"' in page
    assert 'name="counted_cash" inputmode="decimal" value="990"' in page
    assert "short ₱10.00" in page and "Saved by ANA" in page
