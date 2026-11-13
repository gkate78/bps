"""Bills at the register: several bills, any billers, one payment; each saved to bill_records."""
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.models import BillerRule, BillRecord
from tests.conftest import ENCODER_PHONE, ENCODER_PIN

TODAY = date.today()
DUE = (TODAY + timedelta(days=5)).isoformat()
GCASH = 1


def bill(account="1234567890", biller="MERALCO", amount="1000", **extra) -> dict:
    return {"account": account, "biller": biller, "customer_name": "kate test", "cp_number": "09171234567",
            "due_date": DUE, "bill_amt": amount, **extra}


def rules(shop):
    shop.add(BillerRule(biller="MERALCO", service_charge=15, late_charge=50), BillerRule(biller="PLDT", service_charge=15))


def saved(shop) -> list[BillRecord]:
    with Session(shop.engine) as session:
        return list(session.exec(select(BillRecord).order_by(BillRecord.id)).all())


def test_several_bills_paid_together_in_cash(shop):
    rules(shop)
    r = shop.client.post(
        "/pos/api/bills",
        json={"bills": [bill(amount="1000.45"), bill(account="0012345678", biller="PLDT", amount="1499.50")], "cash": "3000"},
    )
    assert r.status_code == 200, r.text
    result = r.json()
    # ₱1,015.45 → ₱1,015 and ₱1,514.50 → ₱1,515: each bill to the whole peso.
    assert result["count"] == 2 and result["total_cents"] == 252_995
    assert result["due_cents"] == 253_000 and result["change_cents"] == 47_000

    meralco, pldt = saved(shop)
    assert (meralco.biller, meralco.customer_name, meralco.total, meralco.payment_method) == ("MERALCO", "KATE TEST", 1015.45, "CASH")
    assert meralco.cash == 1015 and meralco.change_amt == 0
    # The change is on the last bill, so the bills add up to the cash handed over.
    assert pldt.cash == 1985 and pldt.change_amt == 470
    assert meralco.reference != pldt.reference and meralco.created_by_user_id == pldt.created_by_user_id

    page = shop.client.get(f"/api/receipts/bills?ids={meralco.id},{pldt.id}")
    assert page.status_code == 200
    # Each bill's two copies together (MERALCO, MERALCO, PLDT, PLDT), printed as one job.
    assert page.text.count('<div class="receipt">') == 4 and meralco.reference in page.text and pldt.reference in page.text
    assert page.text.index(pldt.reference) > page.text.rindex(meralco.reference)
    assert shop.client.get(f"/api/receipts/bills?ids={meralco.id},{pldt.id}&copies=1").text.count('<div class="receipt">') == 2
    assert shop.client.get(f"/api/records/{pldt.id}/receipt?copies=1").text.count('<div class="receipt">') == 1

    # The Bills tab saves them as one sale (zero own total) and prints the bills from it, with the one payment.
    sale_page = shop.client.get(f"/pos/receipt/sale/{result['sale_id']}").text
    assert sale_page.count('<div class="receipt">') == 4
    assert sale_page.count(f"PAID TOGETHER: 2 BILLS ({result['sale_no']})") == 4
    assert sale_page.count("3,000.00") == 4 and sale_page.count("470.00") == 4  # cash handed over, change
    assert "1,985.00" not in sale_page  # not the last bill's own cash
    assert result["sale_no"] in shop.client.get("/pos/sales").text

    mine = shop.client.get("/api/records/mine").json()
    assert mine["count"] == 2


def test_nothing_is_saved_when_one_bill_is_wrong(shop):
    rules(shop)
    client = shop.client
    r = client.post("/pos/api/bills", json={"bills": [bill(), bill(biller="NEW BILLER")], "cash": "5000"})
    assert r.status_code == 400 and "Bill 2 (NEW BILLER" in r.json()["detail"] and "no biller rule" in r.json()["detail"]
    r = client.post("/pos/api/bills", json={"bills": [bill(), bill(account="12AB")], "cash": "5000"})
    assert r.status_code == 400 and "numbers only" in r.json()["detail"]
    r = client.post("/pos/api/bills", json={"bills": [bill(), bill()], "cash": "5000"})
    assert r.status_code == 400 and "same account and amount is already in the list" in r.json()["detail"]
    # Same account and amount under another biller is still a duplicate.
    r = client.post("/pos/api/bills", json={"bills": [bill(), bill(biller="PLDT")], "cash": "5000"})
    assert r.status_code == 400 and "Bill 2 (PLDT" in r.json()["detail"]
    r = client.post("/pos/api/bills", json={"bills": [bill(), bill(account="1234567891")], "cash": "2000"})
    assert r.status_code == 400 and "less than the total (₱2,030.00)" in r.json()["detail"]
    assert saved(shop) == []

    # Already entered today (from the register or the entry form): refused before anything is saved.
    assert client.post("/pos/api/bills", json={"bills": [bill()], "cash": "1015"}).status_code == 200
    r = client.post("/pos/api/bills", json={"bills": [bill(account="1234567891"), bill()], "cash": "5000"})
    assert r.status_code == 400 and "Bill 2" in r.json()["detail"] and "already has a bill of ₱1,000.00 this month" in r.json()["detail"]
    assert len(saved(shop)) == 1


def test_bills_paid_by_gcash_share_one_reference_used_once(shop):
    rules(shop)
    client = shop.client
    two = [bill(), bill(account="0012345678", biller="PLDT", amount="500")]
    r = client.post("/pos/api/bills", json={"bills": two, "payment_method": "GCASH"})
    assert r.status_code == 400 and "reference no." in r.json()["detail"]

    r = client.post("/pos/api/bills", json={"bills": two, "payment_method": "GCASH", "reference": "ref 777"})
    assert r.status_code == 200, r.text
    assert r.json()["change_cents"] == 0 and r.json()["due_cents"] == 153_000
    for record in saved(shop):
        assert record.payment_method == "GCASH" and record.confirmation_reference == "REF 777"
        assert record.cash == record.total and record.change_amt == 0

    page = client.get(f"/pos/receipt/sale/{r.json()['sale_id']}").text
    assert page.count("PAID VIA GCASH") == 4 and page.count("REF REF 777") == 4 and "CHANGE" not in page

    # The same transfer can't be claimed again: not for a cash-in, not for more bills.
    claimed = client.get("/pos/api/wallet-txns/claimed?reference=REF777").json()
    assert claimed["claimed"] and "2 bills (MERALCO, PLDT)" in claimed["message"]
    r = client.post(
        "/pos/api/wallet-txns",
        json={"kind": "cash_out", "wallet_id": GCASH, "amount": "1000", "customer_mobile": "09181112222", "reference": "REF 777"},
    )
    assert r.status_code == 400 and "already used" in r.json()["detail"]
    r = client.post("/pos/api/bills", json={"bills": [bill(account="1111111111")], "payment_method": "GCASH", "reference": "REF777"})
    assert r.status_code == 400 and "already used" in r.json()["detail"]

    # A bank transfer's reference is optional.
    r = client.post("/pos/api/bills", json={"bills": [bill(account="2222222222")], "payment_method": "BPI"})
    assert r.status_code == 200, r.text


def test_personal_bills_at_the_register(shop):
    rules(shop)
    r = shop.client.post("/pos/api/bills", json={"bills": [bill(), bill(account="0012345678", biller="PLDT")], "personal": "shop"})
    assert r.status_code == 200, r.text
    assert r.json()["due_cents"] == 0
    for record in saved(shop):
        assert record.personal == "shop" and record.charge == 0 and record.cash == 0 and record.payment_method is None

    shop.add_user(ENCODER_PHONE, ENCODER_PIN, "encoder", "ANA")
    shop.sign_in(ENCODER_PHONE, ENCODER_PIN)
    r = shop.client.post("/pos/api/bills", json={"bills": [bill(account="1111111111")], "personal": "paid", "cash": "1000"})
    assert r.status_code == 400 and "admin" in r.json()["detail"]
    r = shop.client.post("/pos/api/bills", json={"bills": [bill(account="1111111111")], "cash": "1015"})
    assert r.status_code == 200, r.text


def test_bill_quote(shop):
    rules(shop)
    client = shop.client
    q = client.get("/pos/api/quote/bill?biller=meralco&amount=1000&due_date=" + (TODAY - timedelta(days=1)).isoformat()).json()
    assert q == {"needs_rule": False, "biller": "MERALCO", "bill_cents": 100_000, "late_charge_cents": 5_000,
                 "rule_late_charge_cents": 5_000, "charge_cents": 1_500, "total_cents": 106_500}
    assert client.get("/pos/api/quote/bill?biller=MERALCO&amount=1000&personal=true").json()["charge_cents"] == 0
    assert client.get("/pos/api/quote/bill?biller=NEW&amount=1000").json() == {"needs_rule": True, "biller": "NEW"}
    r = client.get("/pos/api/quote/bill?biller=MERALCO&account=12AB&amount=1000")
    assert r.status_code == 400 and "numbers only" in r.json()["detail"]

    client.post("/pos/api/bills", json={"bills": [bill()], "cash": "1015"})
    r = client.get("/pos/api/quote/bill?biller=MERALCO&account=1234567890&amount=1000")
    assert r.status_code == 400 and "Duplicate: account 1234567890 already has a bill" in r.json()["detail"]


def test_entry_form_moves_to_the_register(shop):
    client = shop.client
    r = client.get("/entry/form", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/pos?tab=bills"
    page = client.get("/pos").text
    assert 'id="tab-bills"' in page and 'data-tab="bills"' in page
    assert "/pos?tab=bills" in client.get("/admin/records").text

    parked = client.post("/pos/api/parked", json={"kind": "bills", "label": "kate", "summary": "1 bill: MERALCO",
                                                   "total_cents": 101_500, "data": {"bills": []}})
    assert parked.status_code == 200


def test_same_account_and_amount_once_a_month(shop):
    rules(shop)
    client = shop.client
    first_of_month = TODAY.replace(day=1)
    last_month = first_of_month - timedelta(days=1)
    earlier = dict(txn_date=first_of_month, account="1234567890", biller="PLDT", customer_name="KATE TEST", cp_number="",
                   bill_amt=1000, total=1015, reference="REF-EARLIER")
    if TODAY != first_of_month:
        shop.add(BillRecord(txn_datetime=datetime.combine(first_of_month, datetime.min.time()), **earlier))
    else:  # the 1st: put the earlier bill today
        shop.add(BillRecord(txn_datetime=datetime.now(), **earlier))
    # Last month's bill of the same amount doesn't count.
    shop.add(BillRecord(txn_datetime=datetime.combine(last_month, datetime.min.time()), **{**earlier, "txn_date": last_month,
                                                                                         "account": "5555555555", "reference": "REF-OLD"}))

    r = client.post("/pos/api/bills", json={"bills": [bill()], "cash": "1015"})  # MERALCO, same account and amount
    assert r.status_code == 400 and "REF-EARLIER" in r.json()["detail"] and "PLDT" in r.json()["detail"]
    r = client.get("/pos/api/quote/bill?biller=MERALCO&account=1234567890&amount=1000")
    assert r.status_code == 400 and "this month" in r.json()["detail"]
    # The bills entry form (online) follows the same rule.
    r = client.post("/api/records", json={"account": "1234567890", "biller": "MERALCO", "customer_name": "KATE TEST",
                                          "cp_number": "09171234567", "bill_amt": 1000, "cash": 1015, "payment_method": "CASH",
                                          "due_date": DUE})
    assert r.status_code == 409 and "this month" in r.json()["detail"]

    # A different amount, or an account only paid last month, is fine.
    assert client.post("/pos/api/bills", json={"bills": [bill(amount="1000.50")], "cash": "1016"}).status_code == 200
    assert client.post("/pos/api/bills", json={"bills": [bill(account="5555555555")], "cash": "1015"}).status_code == 200


def test_entry_form_needs_the_mode_of_payment(shop):
    rules(shop)
    record = {"account": "1234567890", "biller": "MERALCO", "customer_name": "KATE TEST", "cp_number": "09171234567",
              "bill_amt": 1000, "cash": 1015, "due_date": DUE}
    r = shop.client.post("/api/records", json=record)
    assert r.status_code == 400 and "mode of payment" in r.json()["detail"]
    assert saved(shop) == []
    # From shop funds nothing is received, so there's no mode of payment.
    r = shop.client.post("/api/records", json={**record, "cash": 0, "personal": "shop"})
    assert r.status_code == 201, r.text
    assert shop.client.post("/api/records", json={**record, "account": "1111111111", "payment_method": "CASH"}).status_code == 201


def test_bills_in_the_register_summary(shop):
    rules(shop)
    client = shop.client
    assert client.post("/pos/api/bills", json={"bills": [bill(amount="1000.45")], "cash": "2000"}).status_code == 200  # ₱1,015 in the drawer
    assert client.post("/pos/api/bills", json={"bills": [bill(account="0012345678", biller="PLDT", amount="500")],
                                               "payment_method": "GCASH", "reference": "REF 9"}).status_code == 200
    assert client.post("/pos/api/bills", json={"bills": [bill(account="2222222222", amount="300")], "personal": "shop"}).status_code == 200
    # The MERALCO cash bill is paid to the biller in cash today: ₱1,000.45 leaves the drawer.
    with Session(shop.engine) as session:
        meralco = session.exec(select(BillRecord).where(BillRecord.account == "1234567890")).one()
        meralco.settled_at, meralco.payment_channel = datetime.now(), "CASH"
        session.add(meralco)
        session.commit()

    from pos.controllers import sale_controller as sales
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    async def summary():
        engine = create_async_engine(str(shop.engine.url).replace("sqlite://", "sqlite+aiosqlite://"))
        async with AsyncSession(engine) as db:
            from pos.controllers.settings_controller import list_wallets
            out = await sales.day_summary(db, TODAY, TODAY)
            return await sales.add_bills(db, out, TODAY, TODAY, await list_wallets(db, active_only=True))

    s = asyncio.run(summary())
    assert s.bill_count == 3 and s.bill_charge_cents == 3_000 and s.bill_total_cents == 101_545 + 51_500 + 30_000
    assert dict(s.bills_by_method) == {"CASH": [1, 101_545], "GCASH": [1, 51_500], "SHOP FUNDS": [1, 30_000]}
    assert s.bill_cash_cents == 101_500 and s.drawer_cents == 101_500 - 100_045
    assert s.wallet_deltas["GCASH"] == 51_500
    assert s.total_income_cents == s.income_cents + 3_000 and s.personal_shop_count == 1

    page = client.get("/pos/summary").text
    assert "Bills payment" in page and "Bills by biller" in page and "PLDT" in page and "Paid to billers" in page
