"""Parking: put an unpaid transaction on hold, serve the next customer, then resume it."""
from datetime import date


def test_park_resume_and_discard(shop):
    client = shop.client
    sale = {
        "kind": "sale",
        "label": "juan cruz",
        "summary": "PRINTING ×3",
        "total_cents": 1500,
        "data": {"cart": [{"kind": "service", "service_id": 1, "qty": 3, "unit_price": "5"}], "fields": {"custName": "JUAN CRUZ"}},
    }
    first = client.post("/pos/api/parked", json=sale)
    assert first.status_code == 200, first.text
    assert first.json()["label"] == "JUAN CRUZ"
    walk_in = client.post(
        "/pos/api/parked", json={"kind": "wallet", "label": " ", "total_cents": 100000, "data": {"fields": {"wAmount": "1000"}}}
    ).json()
    assert walk_in["label"] == "WALK-IN"

    listed = client.get("/pos/api/parked").json()
    assert [p["label"] for p in listed] == ["JUAN CRUZ", "WALK-IN"]
    assert listed[0]["parked_by"] == "KATE TEST" and listed[0]["total_cents"] == 1500

    # Parked money isn't in the day: End of day warns instead.
    assert "2 parked transactions (₱1,015.00)" in client.get("/pos/eod").text
    assert client.get("/pos/summary").status_code == 200

    # Resume gives back the screen as it was and removes it from the list; a second resume finds nothing.
    resumed = client.post(f"/pos/api/parked/{first.json()['id']}/resume")
    assert resumed.json()["data"] == sale["data"] and resumed.json()["kind"] == "sale"
    assert client.post(f"/pos/api/parked/{first.json()['id']}/resume").status_code == 404

    assert client.post(f"/pos/api/parked/{walk_in['id']}/discard").status_code == 200
    assert client.get("/pos/api/parked").json() == []
    assert "parked transaction" not in client.get(f"/pos/eod?day={date.today().isoformat()}").text


def test_park_needs_a_signed_in_staff_member(shop):
    shop.client.post("/auth/logout")
    assert shop.client.get("/pos/api/parked").status_code == 401
    assert shop.client.post("/pos/api/parked", json={"kind": "sale", "data": {}}).status_code == 401
