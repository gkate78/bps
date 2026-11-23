"""Tarpaulin jobs: each sale with a tarpaulin goes to the designer's list; they move it through the steps."""
from sqlmodel import Session, select

from pos.models import PosTarpJob
from tests.conftest import ADMIN_PIN, ENCODER_PHONE, ENCODER_PIN
from tests.pos.test_register import ids

DESIGNER_PHONE, DESIGNER_PIN = "09170000002", "2468"


def tarp_sale(shop, size="3X4", price="450", **extra):
    payload = {"lines": [{"kind": "service", "service_id": ids()["TARPAULIN"], "description": size, "qty": 1, "unit_price": price}],
               "cash": "1000", **extra}
    r = shop.client.post("/pos/api/sales", json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


def jobs(shop):
    with Session(shop.engine) as s:
        return s.exec(select(PosTarpJob).order_by(PosTarpJob.id)).all()


def set_designer(shop, user_id):
    r = shop.client.post("/pos/settings/tarpaulin", data={"designer": str(user_id) if user_id else ""})
    assert "Tarpaulin saved" in r.text


def test_tarp_sales_become_jobs_for_the_designer(shop):
    designer = shop.add_user(DESIGNER_PHONE, DESIGNER_PIN, "encoder", "DINO")
    shop.add_user(ENCODER_PHONE, ENCODER_PIN, "encoder", "ANA")
    tarp_sale(shop, "2X3", "300")  # before a designer is set: not assigned
    assert jobs(shop)[0].designer_user_id is None
    set_designer(shop, designer.id)  # ...until one is set
    assert jobs(shop)[0].designer_user_id == designer.id
    sale = tarp_sale(shop, customer_name="JUAN DELA CRUZ")
    shop.client.post("/pos/api/sales", json={"lines": [{"kind": "service", "service_id": ids()["PRINTING"], "qty": 1, "unit_price": "3"}],
                                             "cash": "3"})  # no tarp: no job
    first, second = jobs(shop)
    shop.client.post(f"/pos/tarp-jobs/{first.id}/assign", data={"designer": ""})  # the admin takes it off them
    first = jobs(shop)[0]
    assert first.designer_user_id is None and second.designer_user_id == designer.id
    assert (second.sale_id, second.status) == (sale["id"], "layout")

    page = shop.client.get("/pos/tarp-jobs").text  # the admin sees both, with a designer column
    assert "2 tarp jobs" in page and "JUAN DELA CRUZ" in page and "Not assigned" in page

    shop.sign_in(DESIGNER_PHONE, DESIGNER_PIN)
    page = shop.client.get("/pos/tarp-jobs").text
    assert "1 tarp job" in page and "3X4" in page and "2X3" not in page
    r = shop.client.post(f"/pos/tarp-jobs/{second.id}/status", data={"status": "approved"})
    assert "Marked approved by customer" in r.text
    shop.client.post(f"/pos/tarp-jobs/{second.id}/notes", data={"notes": "  blue   background "})
    shop.client.post(f"/pos/tarp-jobs/{second.id}/status", data={"status": "claimed"})
    job = jobs(shop)[1]
    assert (job.status, job.notes.upper()) == ("claimed", "BLUE BACKGROUND")
    assert job.claimed_at is not None
    assert "0 tarp jobs" in shop.client.get("/pos/tarp-jobs").text  # claimed ones leave the open list
    assert "1 tarp job" in shop.client.get("/pos/tarp-jobs?show=claimed").text

    # Another cashier sees none and can't change the designer's job.
    shop.sign_in(ENCODER_PHONE, ENCODER_PIN)
    assert "0 tarp jobs" in shop.client.get("/pos/tarp-jobs?show=all").text
    r = shop.client.post(f"/pos/tarp-jobs/{second.id}/status", data={"status": "layout"})
    assert "assigned to someone else" in r.text
    assert "Only an admin" in shop.client.post(f"/pos/tarp-jobs/{first.id}/assign", data={"designer": str(designer.id)}).text


def test_admin_reassigns_and_balance_blocks_claimed(shop):
    designer = shop.add_user(DESIGNER_PHONE, DESIGNER_PIN, "encoder", "DINO")
    sale = tarp_sale(shop, "4X6", "650", is_job_order=True, down_payment="300", customer_name="MARIA SANTOS", cash="300")
    (job,) = jobs(shop)
    assert job.designer_user_id is None
    r = shop.client.post(f"/pos/tarp-jobs/{job.id}/assign", data={"designer": str(designer.id)})
    assert "Job reassigned" in r.text
    assert jobs(shop)[0].designer_user_id == designer.id
    assert "Balance <strong>₱350.00" in shop.client.get(f"/pos/tarp-jobs?designer={designer.id}").text

    r = shop.client.post(f"/pos/tarp-jobs/{job.id}/status", data={"status": "claimed"})
    assert "still has a balance of ₱350.00" in r.text
    shop.client.post(f"/pos/api/sales/{sale['id']}/payments", json={"cash": "350"})
    r = shop.client.post(f"/pos/tarp-jobs/{job.id}/status", data={"status": "claimed"})
    assert "Marked claimed" in r.text

    assert "Choose a step" in shop.client.post(f"/pos/tarp-jobs/{job.id}/status", data={"status": "lost"}).text
    assert "Choose a staff member" in shop.client.post("/pos/settings/tarpaulin", data={"designer": "999"}).text


def test_specs_typed_at_the_register_reach_the_designer(shop):
    specs = "  Happy 7th Birthday,   Ana!  \n\n pink and gold \n photo on Messenger "
    tarp_sale(shop, tarp_specs=specs)
    (job,) = jobs(shop)
    assert job.specs == "Happy 7th Birthday, Ana!\npink and gold\nphoto on Messenger"  # as typed, not uppercased
    page = shop.client.get("/pos/tarp-jobs").text
    assert "Happy 7th Birthday, Ana!" in page
    r = shop.client.post(f"/pos/tarp-jobs/{job.id}/specs", data={"specs": "Happy 8th Birthday, Ana!"})
    assert "Customer specs saved" in r.text and jobs(shop)[0].specs == "Happy 8th Birthday, Ana!"
    # Specs on a sale without a tarpaulin are ignored (no job).
    shop.client.post("/pos/api/sales", json={"lines": [{"kind": "service", "service_id": ids()["PRINTING"], "qty": 1, "unit_price": "3"}],
                                             "cash": "3", "tarp_specs": "x"})
    assert len(jobs(shop)) == 1


def test_setting_the_designer_gives_them_the_unassigned_open_jobs(shop):
    designer = shop.add_user(DESIGNER_PHONE, DESIGNER_PIN, "encoder", "DINO")
    other = shop.add_user(ENCODER_PHONE, ENCODER_PIN, "encoder", "ANA")
    for _ in range(4):
        tarp_sale(shop)
    a, b, c, d = jobs(shop)
    shop.client.post(f"/pos/tarp-jobs/{b.id}/assign", data={"designer": str(other.id)})  # already someone's: kept
    shop.client.post(f"/pos/tarp-jobs/{c.id}/status", data={"status": "claimed"})      # claimed: left alone
    shop.client.post(f"/pos/api/sales/{d.sale_id}/void", json={"reason": "WRONG SIZE", "admin_pin": ADMIN_PIN})  # voided: left alone
    r = shop.client.post("/pos/settings/tarpaulin", data={"designer": str(designer.id)})
    assert "1 unassigned tarp job given to the designer" in r.text
    assert [j.designer_user_id for j in jobs(shop)] == [designer.id, other.id, None, None]
    assert "Tarpaulin saved<" in shop.client.post("/pos/settings/tarpaulin", data={"designer": str(designer.id)}).text  # nothing left


def test_voided_sale_leaves_the_list(shop):
    tarp_sale(shop)
    (job,) = jobs(shop)
    assert "1 tarp job" in shop.client.get("/pos/tarp-jobs").text
    r = shop.client.post(f"/pos/api/sales/{job.sale_id}/void", json={"reason": "WRONG SIZE", "admin_pin": ADMIN_PIN})
    assert r.status_code == 200, r.text
    assert "0 tarp jobs" in shop.client.get("/pos/tarp-jobs?show=all").text
