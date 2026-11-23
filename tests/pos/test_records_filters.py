"""Bills records (admin) Data Controls: due date range and pending/processed status."""
from datetime import date, datetime, timedelta

from app.models import BillRecord

TODAY = date.today()


def add(shop, ref, due, paid_ref=None):
    shop.add(BillRecord(txn_datetime=datetime.now(), txn_date=TODAY, account=ref[-4:], biller="MERALCO", customer_name="X",
                        cp_number="", bill_amt=100, total=115, cash=115, due_date=due, reference=ref,
                        payment_reference=paid_ref))


def refs(client, **params):
    r = client.get("/api/records/datatable", params={"draw": 1, "start": 0, "length": 50, **params})
    assert r.status_code == 200, r.text
    return sorted(row["reference"] for row in r.json()["data"])


def test_due_date_range_and_status(shop):
    add(shop, "REF-A001", TODAY - timedelta(days=5))
    add(shop, "REF-B002", TODAY + timedelta(days=2), paid_ref="PAID-1")
    add(shop, "REF-C003", TODAY + timedelta(days=10))
    add(shop, "REF-D004", None, paid_ref="  ")  # blank reference: still pending
    client = shop.client

    assert refs(client, status="pending") == ["REF-A001", "REF-C003", "REF-D004"]
    assert refs(client, status="processed") == ["REF-B002"]
    assert refs(client, due_from=TODAY.isoformat(), due_to=(TODAY + timedelta(days=7)).isoformat()) == ["REF-B002"]
    assert refs(client, due_from=TODAY.isoformat(), status="pending") == ["REF-C003"]
    assert refs(client, due_to=TODAY.isoformat()) == ["REF-A001"]
    assert client.get("/api/records/datatable", params={"status": "nope"}).status_code == 422

    kpis = client.get("/api/admin/records/kpis", params={"status": "pending"}).json()
    assert kpis["visible_records"] == 3 and kpis["pending_records"] == 3 and kpis["processed_records"] == 0
    assert kpis["default_scope"] is False


def test_totals_and_print(shop):
    add(shop, "REF-A001", TODAY - timedelta(days=5))
    add(shop, "REF-B002", TODAY + timedelta(days=2), paid_ref="PAID-1")
    add(shop, "REF-C003", TODAY + timedelta(days=10))
    client = shop.client
    r = client.get("/api/records/datatable", params={"draw": 1, "start": 0, "length": 1, "status": "pending"}).json()
    # Totals cover every page, not just the one row shown.
    assert len(r["data"]) == 1 and r["totals"] == {"count": 2, "bill_amt": 200.0, "late_charge": 0.0, "charge": 0.0, "total": 230.0}
    r = client.get("/api/records/datatable", params={"draw": 1, "start": 0, "length": 10, "search[value]": "C003"}).json()
    assert r["totals"]["count"] == 1 and r["recordsFiltered"] == 1

    page = client.get("/admin/records/print", params={"status": "pending"})
    assert page.status_code == 200
    assert "REF-A001" in page.text and "REF-C003" in page.text and "REF-B002" not in page.text
    assert "Status: Pending" in page.text and "Total (2)" in page.text and "230.00" in page.text
    assert "REF-C003" in client.get("/admin/records/print", params={"search": "C003"}).text
    assert "REF-A001" not in client.get("/admin/records/print", params={"search": "C003"}).text

    client.post("/auth/logout")
    assert client.get("/admin/records/print", follow_redirects=False).status_code == 303


def test_payment_sheet_for_one_biller(shop):
    from app.models import BusinessProfile
    from sqlmodel import Session, select
    with Session(shop.engine) as session:
        profile = session.exec(select(BusinessProfile)).first()
        profile.business_name, profile.business_phone = "Ditto Digital Print Shop", "09089189558"
        session.add(profile)
        session.commit()
    for i, (account, name, amount, late) in enumerate([("20190535944", "TANDANG, MARINA", 1298.35, 0),
                                                       ("20070508238", "RAMOS, ALBERTO", 600.00, 23.45)]):
        shop.add(BillRecord(txn_datetime=datetime(2026, 11, 14, 9, i), txn_date=TODAY, account=account, biller="STA MARIA WATER",
                            customer_name=name, cp_number="", bill_amt=amount, late_charge=late, charge=15,
                            total=amount + late + 15, cash=0, due_date=TODAY, reference=f"REF-W{i}"))
    add(shop, "REF-M001", TODAY)  # MERALCO: not on the water sheet
    client = shop.client
    assert client.get("/admin/records/payment-sheet").status_code == 400  # needs a biller
    page = client.get("/admin/records/payment-sheet", params={"biller": "STA MARIA WATER", "status": "pending"}).text
    assert "DITTO DIGITAL PRINT SHOP BILLS PAYMENT" in page and "0908-918-9558" in page
    assert "201905-35944" in page and "200705-08238" in page and "REF-M001" not in page
    # The bills' original amounts (no late or service charge): 1,298.35 + 600.00 = 1,898.35; cash 1,899.00, change 0.65.
    assert "1,898.35" in page and "1,899.00" in page and "0.65" in page and "623.45" not in page
    assert "600.65" in page  # balance after the first: 1,899 - 1,298.35, then 0.65


def test_print_and_payment_sheet_follow_the_table_sort(shop):
    add(shop, "REF-A001", TODAY + timedelta(days=9))
    add(shop, "REF-B002", None)
    add(shop, "REF-C003", TODAY - timedelta(days=3))
    add(shop, "REF-D004", TODAY + timedelta(days=1))
    client = shop.client

    def order(page, refs=("REF-A001", "REF-B002", "REF-C003", "REF-D004")):
        return [r for _, r in sorted((page.index(r), r) for r in refs)]

    page = client.get("/admin/records/print", params={"sort": "due_date", "sort_dir": "asc"}).text
    assert order(page) == ["REF-C003", "REF-D004", "REF-A001", "REF-B002"]  # no due date last
    assert "Sorted by due date, soonest first" in page
    page = client.get("/admin/records/print", params={"sort": "due_date", "sort_dir": "desc"}).text
    assert order(page) == ["REF-A001", "REF-D004", "REF-C003", "REF-B002"]
    page = client.get("/admin/records/print").text  # no sort: oldest first, as before
    assert order(page) == ["REF-A001", "REF-B002", "REF-C003", "REF-D004"] and "Sorted by" not in page
    assert client.get("/admin/records/print", params={"sort": "nope"}).status_code == 200
    assert client.get("/admin/records/print", params={"sort_dir": "sideways"}).status_code == 422

    sheet = client.get("/admin/records/payment-sheet", params={"biller": "MERALCO", "sort": "due_date", "sort_dir": "asc"}).text
    accounts = ["C003", "D004", "A001", "B002"]
    assert [a for _, a in sorted((sheet.index(f"<td>{a}</td>"), a) for a in accounts)] == accounts

    # The table itself, sorted by due date, also puts bills without one last.
    r = client.get("/api/records/datatable", params={
        "draw": 1, "start": 0, "length": 50, "order[0][column]": "6", "order[0][dir]": "asc", "columns[6][data]": "due_date"})
    assert [row["reference"] for row in r.json()["data"]] == ["REF-C003", "REF-D004", "REF-A001", "REF-B002"]
