"""Unsaved register work kept on the server, so a brownout or a closed browser doesn't lose it."""
from tests.conftest import ADMIN_PHONE, ADMIN_PIN, ENCODER_PHONE, ENCODER_PIN

LINE = {"kind": "service", "service_id": 1, "qty": 2, "unit_price": "5"}


def draft(kind="sale", label="ana") -> dict:
    return {"kind": kind, "label": label, "summary": "PRINTING ×2", "total_cents": 1000,
            "data": {"cart": [{"name": "PRINTING", "qty": 2}], "fields": {"custName": "ANA"}}}


def test_unsaved_sale_is_kept_until_it_is_saved(shop):
    client = shop.client
    assert client.get("/pos/api/drafts").json() == []
    assert client.put("/pos/api/drafts", json=draft()).status_code == 200
    assert client.put("/pos/api/drafts", json={**draft(), "total_cents": 1500}).status_code == 200  # replaced, not added
    rows = client.get("/pos/api/drafts").json()
    assert len(rows) == 1 and rows[0]["kind"] == "sale" and rows[0]["label"] == "ANA" and rows[0]["total_cents"] == 1500
    assert rows[0]["data"]["fields"]["custName"] == "ANA"

    # Saving the sale removes its copy, even if the page never gets to.
    client.put("/pos/api/drafts", json=draft("wallet"))
    assert client.post("/pos/api/sales", json={"lines": [LINE], "cash": "10"}).status_code == 200
    assert [r["kind"] for r in client.get("/pos/api/drafts").json()] == ["wallet"]
    # Clearing the screen removes it too.
    assert client.delete("/pos/api/drafts/wallet").status_code == 200
    assert client.get("/pos/api/drafts").json() == []


def test_parking_removes_the_unsaved_copy(shop):
    client = shop.client
    client.put("/pos/api/drafts", json=draft("bills"))
    assert client.post("/pos/api/parked", json=draft("bills")).status_code == 200
    assert client.get("/pos/api/drafts").json() == []


def test_each_cashier_has_their_own(shop):
    client = shop.client
    client.put("/pos/api/drafts", json=draft(label="admin's"))
    shop.add_user(ENCODER_PHONE, ENCODER_PIN, "encoder", "ANA")
    shop.sign_in(ENCODER_PHONE, ENCODER_PIN)
    assert client.get("/pos/api/drafts").json() == []
    client.put("/pos/api/drafts", json=draft(label="ana's"))
    shop.sign_in(ADMIN_PHONE, ADMIN_PIN)
    assert [r["label"] for r in client.get("/pos/api/drafts").json()] == ["ADMIN'S"]


def test_drafts_need_a_signed_in_cashier(shop):
    shop.client.post("/auth/logout")
    assert shop.client.get("/pos/api/drafts").status_code == 401
    assert shop.client.put("/pos/api/drafts", json=draft()).status_code == 401
