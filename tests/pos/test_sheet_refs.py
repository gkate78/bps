"""Payment references typed in the Google Sheet's PAYMENT REFERENCES tab, with Google replaced by a fake."""
from datetime import date, datetime

from sqlmodel import Session, select

from app.models import BillRecord, RecordAuditLog
from pos.controllers import gsheets_controller as gsheets

URL = "https://script.google.com/macros/s/TEST-DEPLOYMENT/exec"
TODAY = date.today()


def add(shop, ref, paid_ref=None, account="1980595543"):
    shop.add(BillRecord(txn_datetime=datetime.now(), txn_date=TODAY, account=account, biller="MERALCO",
                        customer_name="SAMPLE CUSTOMER", cp_number="", bill_amt=500, charge=15, total=515, cash=515,
                        due_date=TODAY, reference=ref, payment_reference=paid_ref))


def fake_sheet(monkeypatch, rows, old_script=False):
    calls = []

    def post_table(url, payload):
        calls.append(payload)
        if old_script and payload.get("action"):
            raise gsheets.BackupError("The link didn't answer like the BPS script. Check it's deployed as a Web app with access 'Anyone'.")
        if payload.get("action") == "read_references":
            return {"ok": True, "references": rows}
        if payload.get("action") == "mark_references":
            return {"ok": True, "marked": len(payload["marks"])}
        return {"ok": True, "rows": len(payload["rows"])}

    monkeypatch.setattr(gsheets, "post_table", post_table)
    return calls


def connect(shop):
    shop.client.get("/pos/settings")  # makes the backup password
    shop.client.post("/pos/settings/gsheets", data={"url": URL})


def row(n, bps, ref, channel=""):
    return {"row": n, "bps_reference": bps, "payment_reference": ref, "channel": channel, "status": ""}


def test_preview_checks_each_row_and_apply_fills_pending_bills_and_marks_the_sheet(shop, monkeypatch):
    add(shop, "REF-A")
    add(shop, "REF-B")
    add(shop, "REF-C", paid_ref="ALREADY1")
    add(shop, "REF-D", paid_ref="SAME9")
    add(shop, "REF-E")
    add(shop, "REF-F")
    calls = fake_sheet(monkeypatch, [
        row(2, " ref-a ", "04961602", "cash"),     # ready, channel typed in lower case
        row(3, "REF-B", "GC123", ""),              # ready, channel from the dialog
        row(4, "REF-C", "OTHER"),                  # bill already has a different reference
        row(5, "REF-D", "same9"),                  # already in BPS (same reference)
        row(6, "REF-NOPE", "X1"),                  # no such bill
        row(7, "REF-E", "ALREADY1"),               # reference used on another bill: warn
        row(8, "REF-F", "R8", "PALAWAN"),          # unknown channel
        row(9, "", "R9"),                          # no BPS reference
    ])
    connect(shop)
    r = shop.client.post("/api/records/sheet-references/preview")
    assert r.status_code == 200, r.text
    items = {i["row"]: i for i in r.json()["items"]}
    assert items[2]["state"] == "ready" and items[2]["channel"] == "CASH" and items[2]["bps_reference"] == "REF-A"
    assert items[3]["state"] == "ready" and items[3]["channel"] == ""
    assert items[4]["state"] == "error" and "already has reference ALREADY1" in items[4]["reason"]
    assert items[5]["state"] == "done"
    assert items[6]["state"] == "error" and "No bill" in items[6]["reason"]
    assert items[7]["state"] == "warn" and "REF-C" in items[7]["reason"]
    assert items[8]["state"] == "error" and "Channel should be" in items[8]["reason"]
    assert items[9]["state"] == "error"
    password = calls[0]["password"]
    assert calls[0] == {"action": "read_references", "password": password} and len(password) >= 20

    calls.clear()
    r = shop.client.post("/api/records/sheet-references/apply", json={
        "items": [{"row": 2, "bps_reference": "REF-A", "payment_reference": "04961602", "channel": "CASH"},
                  {"row": 3, "bps_reference": "REF-B", "payment_reference": "GC123", "channel": ""},
                  {"row": 4, "bps_reference": "REF-C", "payment_reference": "OTHER", "channel": ""}],
        "done_rows": [{"row": 5, "bps_reference": "REF-D"}],
        "channel": "GCASH",
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"applied": 2, "skipped": 1, "marked": 3, "sheet_error": ""}
    with Session(shop.engine) as s:
        bills = {b.reference: b for b in s.exec(select(BillRecord)).all()}
        logs = s.exec(select(RecordAuditLog).where(RecordAuditLog.action == "sheet_reference")).all()
    assert (bills["REF-A"].payment_reference, bills["REF-A"].payment_channel) == ("04961602", "CASH")
    assert (bills["REF-B"].payment_reference, bills["REF-B"].payment_channel) == ("GC123", "GCASH")
    assert bills["REF-A"].settled_at and bills["REF-C"].payment_reference == "ALREADY1"
    assert len(logs) == 2
    marks = {m["row"]: m["status"] for m in calls[0]["marks"]}
    assert marks == {2: f"DONE {TODAY:%m/%d/%Y}", 3: f"DONE {TODAY:%m/%d/%Y}", 5: "ALREADY IN BPS"}
    assert calls[0]["marks"][0]["bps_reference"] == "REF-A"


def test_duplicate_rows_and_an_old_script(shop, monkeypatch):
    add(shop, "REF-A")
    add(shop, "REF-B")
    add(shop, "REF-C")
    fake_sheet(monkeypatch, [row(2, "REF-A", "R1"), row(3, "REF-A", "R2"), row(4, "REF-B", "R5"), row(5, "REF-C", "R5")])
    connect(shop)
    items = {i["row"]: i for i in shop.client.post("/api/records/sheet-references/preview").json()["items"]}
    assert items[2]["state"] == items[3]["state"] == "error" and "more than one row" in items[2]["reason"]
    assert items[4]["state"] == items[5]["state"] == "warn" and "another row" in items[4]["reason"]

    fake_sheet(monkeypatch, [], old_script=True)
    r = shop.client.post("/api/records/sheet-references/preview")
    assert r.status_code == 400 and "Update the script" in r.json()["detail"]


def test_needs_the_sheet_link_and_a_marking_failure_keeps_the_references(shop, monkeypatch):
    add(shop, "REF-A")
    r = shop.client.post("/api/records/sheet-references/preview")
    assert r.status_code == 400 and "Set up the Google Sheet backup first" in r.json()["detail"]

    connect(shop)

    def broken(url, payload):
        raise gsheets.BackupError("Couldn't reach Google (offline). Check the internet connection.")

    monkeypatch.setattr(gsheets, "post_table", broken)
    r = shop.client.post("/api/records/sheet-references/apply", json={
        "items": [{"row": 2, "bps_reference": "REF-A", "payment_reference": "R1"}], "channel": "CASH"})
    assert r.json()["applied"] == 1 and "Couldn't reach Google" in r.json()["sheet_error"]
    with Session(shop.engine) as s:
        assert s.exec(select(BillRecord)).one().payment_reference == "R1"


def test_records_page_has_the_button_and_the_script_keeps_the_tab(shop):
    assert 'id="sheetRefsBtn"' in shop.client.get("/admin/records").text
    script = gsheets.script_text("pw")
    assert 'const REFS_TAB = "PAYMENT REFERENCES"' in script and "read_references" in script and "mark_references" in script


def test_encoders_cant_use_it(shop):
    from tests.conftest import ENCODER_PHONE, ENCODER_PIN

    shop.add_user(ENCODER_PHONE, ENCODER_PIN, "encoder", "ENCODER")
    shop.sign_in(ENCODER_PHONE, ENCODER_PIN)
    assert shop.client.post("/api/records/sheet-references/preview").status_code in (401, 403)
