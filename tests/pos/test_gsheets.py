"""Backup to Google Sheets, with the Apps Script call replaced by a fake (nothing is sent)."""
import json
from datetime import date

from pos.controllers import gsheets_controller as gsheets
from tests.pos.test_end_of_day import bill

URL = "https://script.google.com/macros/s/TEST-DEPLOYMENT/exec"


def fake_google(monkeypatch, fail_on: str = ""):
    sent = []

    def post_table(url, payload):
        if payload["tab"] == fail_on:
            raise gsheets.BackupError("Google Sheet said: Wrong password")
        sent.append((url, payload))
        return {"ok": True, "rows": len(payload["rows"])}

    monkeypatch.setattr(gsheets, "post_table", post_table)
    return sent


def test_settings_show_the_script_with_a_password_and_check_the_link(shop):
    page = shop.client.get("/pos/settings").text
    assert "Backup to Google Sheets" in page and "function doPost" in page and "__PASSWORD__" not in page
    r = shop.client.post("/pos/settings/gsheets", data={"url": "https://example.com/steal"})
    assert "should start with https://script.google.com/macros/s/" in r.text
    assert 'action="/pos/settings/gsheets/backup"' not in r.text


def test_backup_sends_every_tab_without_secrets(shop, monkeypatch):
    sent = fake_google(monkeypatch)
    client = shop.client
    shop.add(bill(1015, 15, cp_number="09181112222"))
    client.post("/pos/api/sales", json={"lines": [{"kind": "service", "service_id": 1, "qty": 2, "unit_price": "7.50"}], "cash": "20"})
    r = client.post("/pos/settings/gsheets", data={"url": URL, "after_eod": "1"})
    assert 'action="/pos/settings/gsheets/backup"' in r.text

    page = client.post("/pos/settings/gsheets/backup").text
    assert "Backed up 13 tabs" in page
    tabs = {p["tab"]: p for _, p in sent}
    assert len(tabs) == 13 and all(url == URL for url, _ in sent)
    everything = json.dumps([p for _, p in sent])
    assert "pin_hash" not in everything and "pin_salt" not in everything and "otp" not in everything
    assert "gsheets_password" not in everything and "TEST-DEPLOYMENT" not in everything

    bills = tabs["BILLS"]
    row = dict(zip(bills["columns"], bills["rows"][0]))
    assert row["cp_number"] == "09181112222" and bills["formats"][bills["columns"].index("cp_number")] == "@"
    assert row["total"] == 1015 and "amt2" not in bills["columns"]
    sale = dict(zip(tabs["SHOP SALES"]["columns"], tabs["SHOP SALES"]["rows"][0]))
    assert sale["total"] == 15.0 and "total_cents" not in tabs["SHOP SALES"]["columns"]
    assert tabs["STAFF"]["columns"] == ["id", "first_name", "last_name", "role"]
    with shop.engine.connect() as conn:
        password = conn.exec_driver_sql("SELECT gsheets_password FROM pos_settings").scalar()
    assert len(password) >= 20 and {p["password"] for _, p in sent} == {password}
    assert f"const PASSWORD = &#34;{password}&#34;" in client.get("/pos/settings").text


def test_backup_after_end_of_day_and_failures_show_in_settings(shop, monkeypatch):
    sent = fake_google(monkeypatch, fail_on="SHOP SALES")
    client = shop.client
    client.get("/pos/settings")
    client.post("/pos/settings/gsheets", data={"url": URL, "after_eod": "1"})
    r = client.post(f"/pos/api/eod/{date.today().isoformat()}", json={"opening_cash": "0", "counted_cash": "0", "wallets": []})
    assert r.status_code == 200, r.text
    assert sent  # ran in the background after the save
    page = client.get("/pos/settings").text
    assert "FAILED: Google Sheet said: Wrong password (after End of day)" in page

    # Turned off: saving End of day doesn't send.
    client.post("/pos/settings/gsheets", data={"url": URL})
    sent.clear()
    client.post(f"/pos/api/eod/{date.today().isoformat()}", json={"opening_cash": "0", "counted_cash": "0", "wallets": []})
    assert sent == []


def test_backup_is_admin_only(shop):
    from tests.conftest import ENCODER_PHONE, ENCODER_PIN

    shop.add_user(ENCODER_PHONE, ENCODER_PIN, "encoder", "ENCODER")
    shop.sign_in(ENCODER_PHONE, ENCODER_PIN)
    r = shop.client.post("/pos/settings/gsheets/backup", follow_redirects=False)
    assert r.status_code in (303, 403)
