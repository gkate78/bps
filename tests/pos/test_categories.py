"""Biller categories (DEC-074), service pick lists and the description tidy-up (DEC-075)."""
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from sqlmodel import Session, select

from app.biller_categories import guess_category, normalize_category
from app.models import BillerRule, BillRecord
from pos.models import PosServiceItem
from tests.pos.test_register import ids

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from standardize_service_items import tidy  # noqa: E402


def test_guess_and_normalize():
    assert guess_category("MERALCO") == "ELECTRICITY"
    assert guess_category("sta maria water") == "WATER"
    assert guess_category("NORZAGARAY WATER DISTRICT") == "WATER"
    assert guess_category("PLDT FIBER") == "INTERNET" and guess_category("CONVERGE") == "INTERNET"
    assert guess_category("GLOBE AT HOME") == "INTERNET" and guess_category("SMART POSTPAID") == "MOBILE POSTPAID"
    assert guess_category("SSS") == "GOVERNMENT" and guess_category("PHILHEALTH") == "GOVERNMENT"
    assert guess_category("BPICC") == "CREDIT CARD" and guess_category("EASY TRIP") == "TOLL"
    assert guess_category("SOMETHING NEW") == "OTHER"
    assert normalize_category(" water ") == "WATER" and normalize_category("FOOD") == ""


def test_rule_form_saves_a_category_and_guesses_when_blank(shop):
    client = shop.client
    client.post("/admin/settings/biller-rules", data={"biller": "prime water", "service_charge": "25"})
    client.post("/admin/settings/biller-rules", data={"biller": "acme coop", "service_charge": "15", "category": "electricity"})
    with Session(shop.engine) as s:
        rules = {r.biller: r.category for r in s.exec(select(BillerRule)).all()}
    assert rules["PRIME WATER"] == "WATER" and rules["ACME COOP"] == "ELECTRICITY"
    page = client.get("/admin/settings").text
    assert 'name="category"' in page and 'data-category="WATER"' in page


def test_insights_total_by_category(shop):
    client = shop.client
    client.post("/admin/settings/biller-rules", data={"biller": "MERALCO", "service_charge": "15", "category": "ELECTRICITY"})
    client.post("/admin/settings/biller-rules", data={"biller": "STA MARIA WATER", "service_charge": "15", "category": "WATER"})
    client.post("/admin/settings/biller-rules", data={"biller": "PRIME WATER", "service_charge": "25"})
    today = date.today()
    for biller, amount in (("MERALCO", 1000), ("STA MARIA WATER", 300), ("PRIME WATER", 200), ("NEW BILLER", 50)):
        shop.add(BillRecord(txn_datetime=datetime.now(), txn_date=today, account="1234567890", biller=biller,
                            customer_name="SAMPLE", cp_number="", bill_amt=amount, charge=15, total=amount + 15,
                            cash=amount + 15, due_date=today, reference=f"REF-{biller[:3]}"))
    r = client.get("/api/admin/insights", params={"from_date": today.isoformat(), "to_date": today.isoformat()})
    assert r.status_code == 200, r.text
    cats = {c["category"]: c for c in r.json()["categories"]}
    assert cats["WATER"]["transactions"] == 2 and cats["WATER"]["bill_total"] == 500.0
    assert cats["WATER"]["billers"] == ["PRIME WATER", "STA MARIA WATER"]
    assert cats["ELECTRICITY"]["service_income"] == 15.0 and cats["OTHER"]["billers"] == ["NEW BILLER"]


def test_pick_list_in_settings_and_suggestions(shop):
    client = shop.client
    i = ids()
    r = client.post("/pos/settings/service-items/add", data={"service_id": i["PRINTING"], "name": " short  b & w ", "price": "5"})
    assert "SHORT B &amp; W added" in r.text
    client.post("/pos/settings/service-items/add", data={"service_id": i["PRINTING"], "name": "long b & w", "price": "6"})
    assert "already has SHORT B &amp; W" in client.post(
        "/pos/settings/service-items/add", data={"service_id": i["PRINTING"], "name": "SHORT B & W", "price": "9"}).text
    with Session(shop.engine) as s:
        items = {it.name: it for it in s.exec(select(PosServiceItem)).all()}
    assert items["SHORT B & W"].price_cents == 500

    # A past sale with another description shows under the pick list, marked as a past sale.
    client.post("/pos/api/sales", json={"lines": [{"kind": "service", "service_id": i["PRINTING"],
                "description": "short b&w", "qty": 1, "unit_price": "5"}], "cash": "5"})
    found = client.get(f"/pos/api/suggest/service?service_id={i['PRINTING']}&q=").json()
    assert [f["description"] for f in found] == ["SHORT B & W", "LONG B & W", "SHORT B&W"]
    assert found[0]["preset"] is True and "preset" not in found[2]
    assert [f["description"] for f in client.get(f"/pos/api/suggest/service?service_id={i['PRINTING']}&q=long").json()] == ["LONG B & W"]

    item_id = items["LONG B & W"].id
    client.post(f"/pos/settings/service-items/{item_id}/save", data={"name": "LONG B & W", "price": "7"})
    client.post(f"/pos/settings/service-items/{item_id}/toggle")
    found = client.get(f"/pos/api/suggest/service?service_id={i['PRINTING']}&q=").json()
    assert "LONG B & W" not in [f["description"] for f in found]
    page = client.get("/pos/settings").text
    assert "Service items (pick list)" in page and 'value="7"' in page

    # Names "service-items" don't fall into the generic /{list_name} routes.
    assert client.post("/pos/settings/services", data={"name": "BINDING"}).status_code == 200


def test_pick_list_is_admin_only(shop):
    from tests.conftest import ENCODER_PHONE, ENCODER_PIN

    shop.add_user(ENCODER_PHONE, ENCODER_PIN, "encoder", "ENCODER")
    shop.sign_in(ENCODER_PHONE, ENCODER_PIN)
    r = shop.client.post("/pos/settings/service-items/add", data={"service_id": 1, "name": "X"}, follow_redirects=False)
    assert r.status_code in (303, 403)


def test_tidy_descriptions():
    assert tidy("long b &w") == "LONG B & W" and tidy("SHORT B&W") == "SHORT B & W"
    assert tidy("PACKAGE 2 - FORMAL ATIRE") == "PACKAGE 2 - FORMAL ATTIRE"
    assert tidy("PACKAGE 3 - FORMAL W/ SOFT COPY") == "PACKAGE 3 - FORMAL WITH SOFT COPY"
    assert tidy("ASA - 4 PCS 1.5 X3") == "ASA - 4 PCS 1.5X3" and tidy("6 PCS 1.5 X 1.5") == "6 PCS 1.5X1.5"
    assert tidy("3R PHOTO PRINT") == "3R PHOTO" and tidy("A4 PHOTO PRINT") == "A4 PHOTO PRINT"
    assert tidy("SHORT - BACK TO BACK") == "SHORT BACK TO BACK" and tidy("A4 - ID BACK TO BACK") == "A4 - ID BACK TO BACK"
    assert tidy("SHORT FULL COLOR WITH EDITS") == "SHORT FULL COLOR WITH EDIT"
    assert tidy("SHORT COLORED") == "SHORT COLORED" and tidy("A4 VELUM 300 GSM") == "A4 VELLUM 300 GSM"


def test_script_previews_then_applies_on_a_copy(shop, tmp_path):
    client = shop.client
    i = ids()
    for desc, price in (("long b &w", "6"), ("LONG B & W", "7"), ("pds", "100")):
        client.post("/pos/api/sales", json={"lines": [{"kind": "service", "service_id": i["ID PICTURE"] if desc == "pds" else i["PRINTING"],
                    "description": desc, "qty": 1, "unit_price": price}], "cash": "200"})
    db = Path(shop.engine.url.database)
    script = [sys.executable, str(ROOT / "scripts" / "standardize_service_items.py"), "--db", str(db)]

    preview = subprocess.run(script, capture_output=True, text=True, check=True).stdout
    assert "'LONG B &W' → 'LONG B & W'  (1)" in preview and "Preview only" in preview
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pos_sale_lines WHERE description = 'LONG B &W'").fetchone()[0] == 1

    done = subprocess.run(script + ["--apply"], capture_output=True, text=True, check=True).stdout
    assert "1 sale lines tidied, 2 pick list items added" in done
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pos_sale_lines WHERE description = 'LONG B &W'").fetchone()[0] == 0
        items = conn.execute("SELECT name, price_cents FROM pos_service_items ORDER BY name").fetchall()
        assert items == [("LONG B & W", 700), ("PDS", 10000)]  # the latest price
        assert conn.execute("SELECT COUNT(*) FROM pos_audit_log WHERE action = 'standardize'").fetchone()[0] == 1
    backups = list(db.parent.glob("*-before-service-items-*.db"))
    assert len(backups) == 1

    again = subprocess.run(script + ["--apply"], capture_output=True, text=True, check=True).stdout
    assert "0 sale lines tidied, 0 pick list items added" in again


def test_a_fixed_phone_on_an_old_bill_replaces_a_short_one_in_the_customer_list(shop):
    import asyncio

    from app import database as app_database
    from app.controllers.bill_controller import upsert_customer_from_record
    from app.models import Customer

    today = date.today()
    shop.add(BillRecord(txn_datetime=datetime.now(), txn_date=today, account="1863091489", biller="MERALCO",
                        customer_name="SAMPLE", cp_number="", bill_amt=100, charge=15, total=115, cash=115,
                        due_date=today, reference="REF-NEW"))
    shop.add(Customer(account="1863091489", biller="MERALCO", customer_name="SAMPLE", phone="0953172067"))
    old_day = date(today.year - 1, 1, 8)

    async def save(phone):
        async with app_database.AsyncSessionLocal() as db:
            return (await upsert_customer_from_record(db, account="1863091489", biller="MERALCO", customer_name="SAMPLE", phone=phone, txn_date=old_day)).phone

    assert asyncio.run(save("09531720667")) == "09531720667"  # short number counted as missing
    assert asyncio.run(save("09170000000")) == "09531720667"  # an older bill doesn't replace a good number
