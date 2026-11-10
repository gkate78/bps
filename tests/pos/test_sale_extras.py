"""
A shop sale can carry what the customer pays (or gets) together with it: GCash/Maya cash-ins and
cash-outs and bills. One total, one payment, one receipt; each is still saved in its own records.
"""
from datetime import date, timedelta

from sqlmodel import Session, select

from app.models import BillerRule, BillRecord
from pos.models import PosSale, PosWalletTxn
from tests.conftest import ADMIN_PIN

ID_PICTURE, GCASH, MAYA = 4, 1, 2
DUE = (date.today() + timedelta(days=5)).isoformat()


def cash_in(amount="2500", reference="GC 123", mobile="09181112222", wallet=GCASH) -> dict:
    return {"kind": "cash_in", "wallet_id": wallet, "mobile_no": mobile, "amount": amount, "reference": reference}


def cash_out(amount="3000", reference="GC 900", mobile="09181112222", fee_mode="deducted", wallet=GCASH) -> dict:
    return {"kind": "cash_out", "wallet_id": wallet, "mobile_no": mobile, "amount": amount, "reference": reference, "fee_mode": fee_mode}


def bill(account="1234567890", biller="MERALCO", amount="1200") -> dict:
    return {"kind": "bill", "bill": {"account": account, "biller": biller, "customer_name": "ana", "cp_number": "09171234567",
                                     "due_date": DUE, "bill_amt": amount}}


def services() -> list[dict]:
    return [
        {"kind": "service", "service_id": ID_PICTURE, "description": "1x1", "qty": 1, "unit_price": "80"},
        {"kind": "service", "service_id": ID_PICTURE, "description": "lamination", "qty": 1, "unit_price": "30"},
    ]


def fee(client, kind, amount) -> int:
    return client.get(f"/pos/api/quote/wallet?kind={kind}&amount={amount}&fee_mode=deducted&personal=").json()["fee_cents"]


def rules(shop):
    shop.add(BillerRule(biller="MERALCO", service_charge=15), BillerRule(biller="PLDT", service_charge=15))


def test_cash_in_with_id_picture_and_lamination(shop):
    client = shop.client
    total = 11_000 + 250_000 + fee(client, "cash_in", 2500)  # services ₱110 + cash-in ₱2,500 + its fee

    r = client.post("/pos/api/sales", json={"lines": [*services(), cash_in()], "cash": "2700", "customer_name": "ana"})
    assert r.status_code == 200, r.text
    sale = r.json()
    assert sale["change_cents"] == 270_000 - total
    assert [(t["kind"], t["amount_cents"], t["customer_mobile"]) for t in sale["wallet_txns"]] == [("cash_in", 250_000, "09181112222")]

    receipt = client.get(f"/pos/receipt/sale/{sale['id']}").text
    assert "GCASH CASH-IN" in receipt and "REF GC 123" in receipt and f"{total / 100:,.2f}" in receipt

    rows = client.get("/pos/sales").text
    assert f"sent with sale {sale['sale_no']}" in rows and "CASH-IN 09181112222" in rows
    assert client.get("/pos/api/wallet-txns/claimed?reference=GC123").json()["claimed"]

    # Voiding the sale voids the cash-in with it.
    assert client.post(f"/pos/api/sales/{sale['id']}/void", json={"reason": "wrong", "admin_pin": ADMIN_PIN}).status_code == 200
    assert client.get(f"/pos/receipt/sale/{sale['id']}").status_code == 409
    assert client.get("/pos/sales").text.count("badge-void") == 2  # the sale and its cash-in
    assert not client.get("/pos/api/wallet-txns/claimed?reference=GC123").json()["claimed"]


def test_cash_out_pays_toward_a_bill(shop):
    """The customer sends ₱3,000 to the shop's GCash and owes a ₱1,215 bill: the shop gives back the rest."""
    rules(shop)
    client = shop.client
    give = 300_000 - fee(client, "cash_out", 3000)
    r = client.post("/pos/api/sales", json={"lines": [bill(), cash_out()]})  # no cash: nothing to collect
    assert r.status_code == 200, r.text
    sale = r.json()
    assert sale["change_cents"] == give - 121_500 and len(sale["bill_ids"]) == 1

    with Session(shop.engine) as session:
        record = session.exec(select(BillRecord)).one()
        txn = session.exec(select(PosWalletTxn)).one()
        assert (record.payment_method, record.cash, record.total) == ("CASH", 1215, 1215)
        assert (txn.kind, txn.amount_cents, txn.give_cents, txn.sale_id) == ("cash_out", 300_000, give, sale["id"])
        assert session.exec(select(PosSale)).one().total_cents == 0

    receipt = client.get(f"/pos/receipt/sale/{sale['id']}").text
    assert "BILL MERALCO" in receipt and "GCASH CASH-OUT" in receipt and "CASH GIVEN" in receipt
    assert receipt.count('class="receipt"') == 3  # the sale's, then the bill's 2 copies
    assert record.reference in receipt

    # A sale of only a bill and a cash-out isn't a shop sale in the summary; each counts in its own records.
    s = client.get("/pos/summary").text
    assert "Bills paid" in s and "MERALCO" in s

    # The bill is linked: the sale can't be voided until the bill is dealt with in Bills records.
    r = client.post(f"/pos/api/sales/{sale['id']}/void", json={"reason": "wrong", "admin_pin": ADMIN_PIN})
    assert r.status_code == 400 and "Bills records first" in r.json()["detail"]


def test_bills_services_and_cash_in_paid_in_cash(shop):
    rules(shop)
    client = shop.client
    ci_fee = fee(client, "cash_in", 500)
    lines = [*services(), bill(amount="1000.45"), bill(account="0012345678", biller="PLDT", amount="500"), cash_in(amount="500")]
    # ₱110 + ₱1,015 (₱1,015.45 to the whole peso) + ₱515 + ₱500 and its fee
    need = 11_000 + 101_500 + 51_500 + 50_000 + ci_fee
    assert client.post("/pos/api/sales", json={"lines": lines, "cash": f"{need / 100 - 1:.2f}"}).status_code == 400
    r = client.post("/pos/api/sales", json={"lines": lines, "cash": "3000"})
    assert r.status_code == 200, r.text
    assert r.json()["change_cents"] == 300_000 - need
    assert len(r.json()["bill_ids"]) == 2

    page = client.get(f"/pos/receipt/sale/{r.json()['id']}").text
    assert page.count('class="receipt"') == 5 and "BILL PLDT" in page

    s = client.get("/pos/summary").text
    assert "Bills paid" in s


def test_paid_by_gcash_or_bank(shop):
    rules(shop)
    client = shop.client
    r = client.post("/pos/api/sales", json={"lines": [*services(), bill()], "payment_method": "wallet",
                                            "pay_wallet_id": GCASH, "payment_reference": "GC 55"})
    assert r.status_code == 200, r.text
    with Session(shop.engine) as session:
        record = session.exec(select(BillRecord)).one()
        assert (record.payment_method, record.confirmation_reference, record.cash) == ("GCASH", "GC 55", record.total)
    receipt = client.get(f"/pos/receipt/sale/{r.json()['id']}").text
    assert "PAID VIA GCASH" in receipt and "1,325.00" in receipt  # ₱110 + ₱1,215
    # The transfer can't be claimed again.
    assert client.get("/pos/api/wallet-txns/claimed?reference=GC55").json()["claimed"]

    r = client.post("/pos/api/sales", json={"lines": [*services(), bill(account="0012345678", biller="PLDT")],
                                            "payment_method": "bank", "bank": "BDO", "payment_reference": "bdo 1"})
    assert r.status_code == 200, r.text
    with Session(shop.engine) as session:
        pldt = session.exec(select(BillRecord).where(BillRecord.biller == "PLDT")).one()
        assert pldt.payment_method == "BDO"
    assert "PAID VIA BDO" in client.get(f"/pos/receipt/sale/{r.json()['id']}").text
    s = client.get("/pos/summary").text
    assert "Shop payments received via BDO: 1, ₱110.00" in s

    r = client.post("/pos/api/sales", json={"lines": services(), "payment_method": "bank"})
    assert r.status_code == 400 and "bank" in r.json()["detail"]


def test_rules_for_what_a_sale_can_carry(shop):
    rules(shop)
    client = shop.client

    def post(lines=None, **body):
        return client.post("/pos/api/sales", json={"lines": lines or [*services(), cash_in()], "cash": "5000", **body})

    r = post([*services(), cash_in()], cash="2000")
    assert r.status_code == 400 and "less than the amount due" in r.json()["detail"]
    r = post([*services(), cash_in(reference="")])
    assert r.status_code == 400 and "reference no. of the GCASH cash-in to 09181112222" in r.json()["detail"]
    r = post([*services(), cash_out(reference="")])
    assert r.status_code == 400 and "reference no. of the GCASH cash-out from 09181112222" in r.json()["detail"]
    r = post([*services(), cash_in(), cash_out(reference="gc123")])
    assert r.status_code == 400 and "entered twice" in r.json()["detail"]
    r = post([*services(), cash_in(amount="100.50")])
    assert r.status_code == 400 and "whole pesos" in r.json()["detail"]
    r = post(payment_method="wallet", pay_wallet_id=MAYA, payment_reference="MY1", cash=None)
    assert r.status_code == 400 and "paid in cash" in r.json()["detail"]
    r = post(is_job_order=True, customer_name="ana", down_payment="50")
    assert r.status_code == 400 and "job order can't include a cash-in" in r.json()["detail"]
    r = post(personal="paid")
    assert r.status_code == 400 and "personal sale can't include a cash-in" in r.json()["detail"]
    r = post([*services(), bill(biller="NEW BILLER")])
    assert r.status_code == 400 and "no biller rule" in r.json()["detail"]
    r = post([*services(), bill(), bill(biller="PLDT")])
    assert r.status_code == 400 and "Bill 2 (PLDT" in r.json()["detail"]

    # A reference no. already used (here by a cash-out) is refused, and nothing is saved.
    used = client.post("/pos/api/wallet-txns", json={"kind": "cash_out", "wallet_id": GCASH, "amount": "1000",
                                                       "customer_mobile": "09181112222", "reference": "GC 123"})
    assert used.status_code == 200
    r = post()
    assert r.status_code == 400 and "already used" in r.json()["detail"]
    with Session(shop.engine) as session:
        assert session.exec(select(PosSale)).all() == [] and session.exec(select(BillRecord)).all() == []
    ok = post([*services(), cash_in(reference="GC 124"), bill()])
    assert ok.status_code == 200 and ok.json()["sale_no"] == "S-000001"

    # A cash-in on its own works too (the GCash / Maya tab still does the same).
    assert post([cash_in(reference="GC 125")]).status_code == 200


def test_personal_sale_with_bills(shop):
    rules(shop)
    r = shop.client.post("/pos/api/sales", json={"lines": [*services(), bill()], "personal": "shop"})
    assert r.status_code == 200, r.text
    with Session(shop.engine) as session:
        record = session.exec(select(BillRecord)).one()
        assert (record.personal, record.payment_method, record.charge, record.cash) == ("shop", None, 0, 0)


def test_part_cash_part_gcash(shop):
    rules(shop)
    client = shop.client
    lines = [*services(), bill(amount="1000.45")]  # ₱110 + ₱1,015 (₱1,015.45 to the whole peso) = ₱1,125

    def post(**body):
        return client.post("/pos/api/sales", json={"lines": lines, "split_wallet_id": GCASH, "split_reference": "GC 700", **body})

    assert post(split_amount="500.50", cash="1000").json()["detail"].endswith("(the rest is collected in cash)")
    r = post(split_amount="2000", cash="0")
    assert r.status_code == 400 and "more than the total (₱1,125.00)" in r.json()["detail"]
    r = post(split_amount="500", cash="600")
    assert r.status_code == 400 and "less than the amount due (₱625.00)" in r.json()["detail"]
    r = post(split_amount="500", cash="1000", split_reference="")
    assert r.status_code == 400 and "GCASH reference no." in r.json()["detail"]
    r = client.post("/pos/api/sales", json={"lines": [*services(), cash_in()], "cash": "3000", "split_wallet_id": GCASH,
                                            "split_amount": "100", "split_reference": "GC 701"})
    assert r.status_code == 400 and "cash only" in r.json()["detail"]

    r = post(split_amount="500", cash="1000")
    assert r.status_code == 200, r.text
    assert r.json()["change_cents"] == 37_500  # ₱625 in cash
    with Session(shop.engine) as session:
        sale = session.exec(select(PosSale)).one()
        assert (sale.payment_method, sale.split_wallet_name, sale.split_cents, sale.cash_cents) == ("cash", "GCASH", 50_000, 100_000)
        assert session.exec(select(BillRecord)).one().payment_method == "CASH"

    receipt = client.get(f"/pos/receipt/sale/{sale.id}").text
    assert "PAID VIA GCASH" in receipt and "REF GC 700" in receipt and "CHANGE" in receipt
    assert client.get("/pos/api/wallet-txns/claimed?reference=gc700").json()["claimed"]
    assert "₱500.00 via GCASH ref GC 700, rest in cash" in client.get("/pos/sales").text

    # The drawer gets only the cash part; GCash gets the rest.
    from pos.controllers import sale_controller as sales
    import asyncio
    from datetime import date as day
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from pos.controllers.settings_controller import list_wallets

    async def summary():
        engine = create_async_engine(str(shop.engine.url).replace("sqlite://", "sqlite+aiosqlite://"))
        async with AsyncSession(engine) as db:
            out = await sales.day_summary(db, day.today(), day.today())
            return await sales.add_bills(db, out, day.today(), day.today(), await list_wallets(db, active_only=True))

    s = asyncio.run(summary())
    assert s.drawer_cents == 62_500 and s.wallet_deltas["GCASH"] == 50_000

    # End of day expects ₱625 in the drawer (₱110 + ₱1,015 − ₱500 sent by GCash).
    r = client.post(f"/pos/api/eod/{day.today().isoformat()}", json={"opening_cash": "0", "counted_cash": "625",
                                                                     "wallets": [{"wallet_id": GCASH, "opening": "0"}]})
    assert r.json() == {"expected_cash_cents": 62_500, "difference_cents": 0}
    assert "₱500.00" in client.get("/pos/eod").text


def test_bills_only_sale_prints_just_the_bill_receipts(shop):
    rules(shop)
    client = shop.client
    r = client.post("/pos/api/sales", json={"lines": [bill()], "cash": "1300"})
    assert r.status_code == 200, r.text
    page = client.get(f"/pos/receipt/sale/{r.json()['id']}").text
    assert page.count('class="receipt"') == 2  # the bill's 2 copies, no sale receipt
    assert r.json()["bill_references"][0] in page
    # One bill: what was handed over and the change (₱1,215 → ₱85), no "paid together".
    assert page.count("1,300.00") == 2 and page.count("85.00") == 2 and "PAID TOGETHER" not in page

    # Two bills: 2 copies each.
    r = client.post("/pos/api/sales", json={"lines": [bill(account="0012345678", biller="PLDT"), bill(amount="500")], "cash": "2000"})
    assert r.status_code == 200, r.text
    assert client.get(f"/pos/receipt/sale/{r.json()['id']}").text.count('class="receipt"') == 4

    # Part by GCash: shown with its reference, then the cash and change.
    r = client.post("/pos/api/sales", json={"lines": [bill(account="0099887766", biller="PLDT")], "cash": "300",
                                            "split_wallet_id": GCASH, "split_amount": "1000", "split_reference": "GC 4242"})
    assert r.status_code == 200, r.text
    page = client.get(f"/pos/receipt/sale/{r.json()['id']}").text
    assert page.count("PAID VIA GCASH") == 2 and page.count("REF GC 4242") == 2 and page.count("85.00") == 2


def test_bill_rung_up_with_services_points_to_the_sale_receipt(shop):
    rules(shop)
    r = shop.client.post("/pos/api/sales", json={"lines": [*services(), bill()], "cash": "1400"})
    assert r.status_code == 200, r.text
    page = shop.client.get(f"/pos/receipt/sale/{r.json()['id']}").text
    assert page.count(f"PAID WITH SALE {r.json()['sale_no']}") == 2
