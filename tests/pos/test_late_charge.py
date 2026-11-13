"""Late charge as a percent of the bill (a water district's 10%), and the penalty printed on the bill typed instead."""
from datetime import date, timedelta

from sqlmodel import Session, select

from app.models import BillerRule, BillRecord

TODAY = date.today()
OVERDUE = (TODAY - timedelta(days=3)).isoformat()
NOT_DUE = (TODAY + timedelta(days=3)).isoformat()


def water(shop):
    shop.add(BillerRule(biller="STA MARIA WATER", service_charge=15, late_charge_rate=10),
             BillerRule(biller="MERALCO", service_charge=15, late_charge=35))


def quote(client, amount="411.25", due=OVERDUE, **extra):
    params = {"biller": "STA MARIA WATER", "amount": amount, "due_date": due, **extra}
    r = client.get("/pos/api/quote/bill", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def bill(**extra) -> dict:
    return {"account": "1234567890", "biller": "STA MARIA WATER", "customer_name": "kate test", "cp_number": "09171234567",
            "due_date": OVERDUE, "bill_amt": "411.25", **extra}


def saved(shop) -> list[BillRecord]:
    with Session(shop.engine) as session:
        return list(session.exec(select(BillRecord).order_by(BillRecord.id)).all())


def test_ten_percent_of_the_bill_when_overdue(shop):
    water(shop)
    q = quote(shop.client)
    # 10% of ₱411.25 = ₱41.125 → ₱41.13
    assert q["late_charge_cents"] == 4_113 and q["rule_late_charge_cents"] == 4_113
    assert q["total_cents"] == 41_125 + 4_113 + 1_500
    assert quote(shop.client, due=NOT_DUE)["late_charge_cents"] == 0
    # Fixed late charges are unchanged.
    r = shop.client.get("/pos/api/quote/bill", params={"biller": "MERALCO", "amount": "1000", "due_date": OVERDUE}).json()
    assert r["late_charge_cents"] == 3_500


def test_penalty_printed_on_the_bill_is_used(shop):
    water(shop)
    q = quote(shop.client, late_charge="39.85")
    assert q["late_charge_cents"] == 3_985 and q["rule_late_charge_cents"] == 4_113
    assert q["total_cents"] == 41_125 + 3_985 + 1_500
    # Not overdue: no late charge, whatever is typed.
    assert quote(shop.client, due=NOT_DUE, late_charge="39.85")["late_charge_cents"] == 0
    assert shop.client.get("/pos/api/quote/bill", params={"biller": "STA MARIA WATER", "amount": "411.25",
                                                          "due_date": OVERDUE, "late_charge": "abc"}).status_code == 400

    r = shop.client.post("/pos/api/bills", json={"bills": [bill(late_charge="39.85")], "cash": "500"})
    assert r.status_code == 200, r.text
    (record,) = saved(shop)
    assert record.late_charge == 39.85 and record.total == 466.10 and record.change_amt == 34

    # Left empty: the rule's 10%.
    r = shop.client.post("/pos/api/bills", json={"bills": [bill(account="2222222222", late_charge="")], "cash": "500"})
    assert r.status_code == 200, r.text
    assert saved(shop)[-1].late_charge == 41.13


def test_penalty_typed_in_a_shop_sale(shop):
    water(shop)
    line = {"kind": "bill", "qty": 1, "bill": bill(late_charge="39.85")}
    r = shop.client.post("/pos/api/sales", json={"lines": [line], "cash": "500"})
    assert r.status_code == 200, r.text
    (record,) = saved(shop)
    assert record.late_charge == 39.85 and record.total == 466.10


def test_record_edit_keeps_a_late_charge_changed_by_hand(shop):
    water(shop)
    shop.client.post("/pos/api/bills", json={"bills": [bill()], "cash": "500"})
    (record,) = saved(shop)
    assert record.late_charge == 41.13
    r = shop.client.put(f"/api/records/{record.id}", json={"late_charge": 39.85})
    assert r.status_code == 200, r.text
    assert saved(shop)[0].late_charge == 39.85 and saved(shop)[0].total == 466.10
    # Changing only the amount recomputes with the rule's 10% unless the late charge was changed too.
    r = shop.client.put(f"/api/records/{record.id}", json={"bill_amt": 400, "late_charge": 39.85})
    assert r.status_code == 200, r.text
    assert saved(shop)[0].late_charge == 40.00


def test_rule_percent_set_in_settings(shop):
    water(shop)
    r = shop.client.post("/admin/settings/biller-rules", data={"biller": "prime water", "service_charge": "25",
                                                               "late_charge": "0", "late_charge_rate": "10", "is_active": "on"},
                         follow_redirects=False)
    assert r.status_code == 303 and "success" in r.headers["location"]
    with Session(shop.engine) as session:
        rule = session.exec(select(BillerRule).where(BillerRule.biller == "PRIME WATER")).one()
        assert rule.late_charge_rate == 10
    assert "10% of bill" in shop.client.get("/admin/settings").text
    r = shop.client.post("/admin/settings/biller-rules", data={"biller": "PRIME WATER", "late_charge_rate": "150"},
                         follow_redirects=False)
    assert "error" in r.headers["location"]
