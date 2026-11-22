"""Materials stock (DEC-077): sales take materials off, voids put them back, restocks, counts, cost and profit."""
from sqlmodel import Session, select

from pos.controllers.stock_controller import suggested_material, suggested_use
from pos.routes.stock_routes import per_unit
from pos.models import PosItemMaterial, PosMaterial, PosServiceItem, PosStockMove
from tests.conftest import ADMIN_PIN
from tests.pos.test_register import ids

XEROX = 2
LAMINATION = 5
SUPPLIES = 8  # seed order: ... TARPAULIN 6, INVITATIONS 7, SUPPLIES 8


def item(shop, service_id, name, price):
    shop.client.post("/pos/settings/service-items/add", data={"service_id": service_id, "name": name, "price": price})


def materials(shop):
    with Session(shop.engine) as s:
        return {m.name: m for m in s.exec(select(PosMaterial)).all()}


def sell(shop, service_id, desc, qty, price="3", cash="1000"):
    r = shop.client.post("/pos/api/sales", json={"lines": [{"kind": "service", "service_id": service_id, "description": desc,
                         "qty": qty, "unit_price": price}], "cash": cash})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def set_up(shop):
    item(shop, XEROX, "SHORT BACK TO BACK", "6")
    item(shop, XEROX, "LONG", "4")
    item(shop, LAMINATION, "ID SMALL", "50")
    item(shop, SUPPLIES, "SHORT BOND PAPER", "2")
    item(shop, ids()["PRINTING"], "A4 PHOTO PRINT", "60")
    r = shop.client.post("/pos/stock/set-up")
    assert "13 materials added, 5 items linked" in r.text


def test_suggested_materials():
    assert suggested_material("XEROX", "SHORT BACK TO BACK") == "SHORT BOND PAPER"
    assert suggested_material("PRINTING", "LONG B & W WITH EDIT") == "LONG BOND PAPER"
    assert suggested_material("PRINTING", "A4 PHOTO PRINT") == "A4 PHOTO PAPER" and suggested_material("PRINTING", "A4 VELLUM 300 GSM") is None
    assert suggested_use("ID PICTURE", "PACKAGE 2 - 4 PCS 2X2 4 PCS 1X1") == ("A4 PHOTO PAPER", 1 / 3)
    assert suggested_use("ID PICTURE", "PDS") == ("A4 PHOTO PAPER", 1 / 3)
    assert suggested_use("PRINTING", "WALLET SIZE PHOTO") == ("3R PHOTO PAPER", 1 / 2)
    assert suggested_use("PRINTING", "3R PHOTO") == ("3R PHOTO PAPER", 1) and suggested_use("PRINTING", "4R PHOTO") == ("4R PHOTO PAPER", 1)
    assert suggested_use("PRINTING", "5R PHOTO") == ("A4 PHOTO PAPER", 1 / 2)
    assert suggested_material("LAMINATION", "ID MEDIUM") == "LAMINATION FILM ID MEDIUM"
    assert suggested_material("SUPPLIES", "SHORT BOND PAPER") == "SHORT BOND PAPER"
    assert suggested_material("SCAN", "SHORT") is None and suggested_material("OTHER", "SOFT COPY") is None


def test_sales_use_stock_voids_put_it_back_and_restock_averages_cost(shop):
    set_up(shop)
    m = materials(shop)
    short, film = m["SHORT BOND PAPER"], m["LAMINATION FILM ID SMALL"]

    # Restock: 500 sheets for ₱250 → ₱0.50 each; then 500 for ₱300 → average ₱0.55.
    shop.client.post("/pos/stock/restock", data={"material_id": short.id, "qty": "500", "total_cost": "250", "supplier": "sm"})
    shop.client.post("/pos/stock/restock", data={"material_id": short.id, "qty": "500", "total_cost": "300"})
    assert materials(shop)["SHORT BOND PAPER"].avg_cost == 0.55

    sale = sell(shop, XEROX, "short back to back", 10, "6")   # 10 sheets
    sell(shop, SUPPLIES, "SHORT BOND PAPER", 5, "2")          # sold as supplies: same stock
    sell(shop, XEROX, "SHORT", 3)                             # not a pick list item: no stock change
    sell(shop, LAMINATION, "ID SMALL", 2, "50")               # film not counted yet: goes below 0
    m = materials(shop)
    assert m["SHORT BOND PAPER"].stock_qty == 985 and m["LAMINATION FILM ID SMALL"].stock_qty == -2
    with Session(shop.engine) as s:
        move = s.exec(select(PosStockMove).where(PosStockMove.sale_id == sale)).one()
    assert (move.kind, move.qty, move.cost_cents, move.service_id) == ("sale", -10, 550, XEROX)

    r = shop.client.post(f"/pos/api/sales/{sale}/void", json={"reason": "wrong item", "admin_pin": ADMIN_PIN})
    assert r.status_code == 200, r.text
    assert materials(shop)["SHORT BOND PAPER"].stock_qty == 995
    shop.client.post(f"/pos/api/sales/{sale}/void", json={"reason": "again", "admin_pin": ADMIN_PIN})
    assert materials(shop)["SHORT BOND PAPER"].stock_qty == 995  # not put back twice

    # Count: 990 on the shelf → -5 recorded, and the count is the stock from now on.
    r = shop.client.post("/pos/stock/count", data={"material_id": short.id, "counted": "990", "note": "misprints"})
    assert "-5 from what BPS expected" in r.text
    assert materials(shop)["SHORT BOND PAPER"].stock_qty == 990
    assert film.counted_at is None  # uncounted film gives no warning


def test_low_stock_warning_on_register_and_stock_page(shop):
    set_up(shop)
    film = materials(shop)["LAMINATION FILM ID SMALL"]
    shop.client.post(f"/pos/stock/materials/{film.id}/save", data={"name": film.name, "unit": "PC", "low_stock_at": "10"})
    sell(shop, LAMINATION, "ID SMALL", 5, "50")
    assert "Running low" not in shop.client.get("/pos").text  # not counted yet
    shop.client.post("/pos/stock/count", data={"material_id": film.id, "counted": "12"})
    sell(shop, LAMINATION, "ID SMALL", 3, "50")
    assert "LAMINATION FILM ID SMALL</strong> (9 left)" in shop.client.get("/pos").text
    assert "Running low:" in shop.client.get("/pos/stock").text


def test_cost_and_profit_per_service(shop):
    set_up(shop)
    short = materials(shop)["SHORT BOND PAPER"]
    shop.client.post("/pos/stock/restock", data={"material_id": short.id, "qty": "100", "total_cost": "50"})
    sell(shop, XEROX, "SHORT BACK TO BACK", 10, "6")  # ₱60 sales, ₱5 paper
    voided = sell(shop, XEROX, "SHORT BACK TO BACK", 4, "6")
    shop.client.post(f"/pos/api/sales/{voided}/void", json={"reason": "test", "admin_pin": ADMIN_PIN})
    page = shop.client.get("/pos/stock").text
    assert "<td>XEROX</td><td class=\"num\">₱60.00</td><td class=\"num\">₱5.00</td><td class=\"num\">₱55.00</td>" in page
    assert "Spent on restocks in these dates: <strong>₱50.00</strong>" in page


def test_item_uses_can_be_changed_and_materials_edited(shop):
    set_up(shop)
    m = materials(shop)
    with Session(shop.engine) as s:
        photo = s.exec(select(PosServiceItem).where(PosServiceItem.name == "A4 PHOTO PRINT")).one()
    shop.client.post("/pos/stock/materials", data={"name": "photo paper a4", "unit": "sheet", "low_stock_at": "5"})
    paper = materials(shop)["PHOTO PAPER A4"]  # another material, so the item is moved to it
    shop.client.post(f"/pos/stock/uses/{photo.id}", data={"material_id": str(paper.id), "qty_per_unit": "1"})
    shop.client.post("/pos/stock/count", data={"material_id": paper.id, "counted": "20"})
    sell(shop, ids()["PRINTING"], "A4 PHOTO PRINT", 2, "60")
    assert materials(shop)["PHOTO PAPER A4"].stock_qty == 18
    shop.client.post(f"/pos/stock/uses/{photo.id}", data={"material_id": ""})
    with Session(shop.engine) as s:
        assert s.exec(select(PosItemMaterial).where(PosItemMaterial.service_item_id == photo.id)).all() == []
    assert "already exists" in shop.client.post("/pos/stock/materials", data={"name": "PHOTO PAPER A4"}).text
    assert "must be" in shop.client.post("/pos/stock/restock", data={"material_id": m["LONG BOND PAPER"].id, "qty": "-3"}).text
    page = shop.client.get("/pos/stock").text
    assert "Set up paper and lamination film" not in page and "Add any missing suggested materials" in page


def test_stock_is_admin_only(shop):
    from tests.conftest import ENCODER_PHONE, ENCODER_PIN

    shop.add_user(ENCODER_PHONE, ENCODER_PIN, "encoder", "ENCODER")
    shop.sign_in(ENCODER_PHONE, ENCODER_PIN)
    assert shop.client.get("/pos/stock", follow_redirects=False).status_code in (303, 403)
    assert shop.client.post("/pos/stock/set-up", follow_redirects=False).status_code in (303, 403)


def test_id_picture_packages_use_a_third_of_a_photo_paper(shop):
    item(shop, ids()["ID PICTURE"], "PACKAGE 1 - 12 PCS 1X1", "80")
    item(shop, ids()["ID PICTURE"], "PDS", "100")
    shop.client.post("/pos/stock/set-up")
    paper = materials(shop)["A4 PHOTO PAPER"]
    shop.client.post("/pos/stock/restock", data={"material_id": paper.id, "qty": "100", "total_cost": "900"})  # ₱9 a sheet
    sell(shop, ids()["ID PICTURE"], "PACKAGE 1 - 12 PCS 1X1", 2, "80")
    sell(shop, ids()["ID PICTURE"], "PDS", 1, "100")
    assert round(materials(shop)["A4 PHOTO PAPER"].stock_qty, 4) == 99  # 3 packages = 1 sheet
    page = shop.client.get("/pos/stock").text
    assert 'value="1/3"' in page and "<strong>99</strong>" in page
    assert "<td>ID PICTURE</td><td class=\"num\">₱260.00</td><td class=\"num\">₱9.00</td>" in page

    # A fraction can be typed for any item.
    with Session(shop.engine) as s:
        pds = s.exec(select(PosServiceItem).where(PosServiceItem.name == "PDS")).one()
    shop.client.post(f"/pos/stock/uses/{pds.id}", data={"material_id": str(paper.id), "qty_per_unit": "1/2"})
    with Session(shop.engine) as s:
        assert s.exec(select(PosItemMaterial).where(PosItemMaterial.service_item_id == pds.id)).one().qty_per_unit == 0.5
    assert "fraction like 1/3" in shop.client.post(f"/pos/stock/uses/{pds.id}", data={"material_id": str(paper.id), "qty_per_unit": "1/0"}).text
    assert per_unit(1 / 3) == "1/3" and per_unit(0.5) == "1/2" and per_unit(2) == "2" and per_unit(0.3) == "0.3"


def test_wallet_size_photos_use_half_a_3r_photo_paper(shop):
    item(shop, ids()["PRINTING"], "WALLET SIZE PHOTO", "10")
    item(shop, ids()["PRINTING"], "3R PHOTO", "15")
    shop.client.post("/pos/stock/set-up")
    paper = materials(shop)["3R PHOTO PAPER"]
    shop.client.post("/pos/stock/count", data={"material_id": paper.id, "counted": "50"})
    sell(shop, ids()["PRINTING"], "WALLET SIZE PHOTO", 4, "10")  # 2 wallets per sheet = 2 sheets
    sell(shop, ids()["PRINTING"], "3R PHOTO", 1, "15")
    assert round(materials(shop)["3R PHOTO PAPER"].stock_qty, 4) == 47
    assert 'value="1/2"' in shop.client.get("/pos/stock").text


def test_cashier_records_rejects_by_print_or_material_with_the_sale(shop):
    from tests.conftest import ENCODER_PHONE, ENCODER_PIN

    item(shop, ids()["PRINTING"], "WALLET SIZE PHOTO", "10")
    item(shop, XEROX, "LONG", "4")
    shop.client.post("/pos/stock/set-up")
    m = materials(shop)
    photo, long_paper = m["3R PHOTO PAPER"], m["LONG BOND PAPER"]
    shop.client.post("/pos/stock/restock", data={"material_id": photo.id, "qty": "50", "total_cost": "250"})  # ₱5 a sheet
    shop.client.post("/pos/stock/count", data={"material_id": long_paper.id, "counted": "100"})
    with Session(shop.engine) as s:
        wallet = s.exec(select(PosServiceItem).where(PosServiceItem.name == "WALLET SIZE PHOTO")).one()
    sale = sell(shop, ids()["PRINTING"], "WALLET SIZE PHOTO", 2, "10")  # 1 sheet

    shop.add_user(ENCODER_PHONE, ENCODER_PIN, "encoder", "ENCODER")
    shop.sign_in(ENCODER_PHONE, ENCODER_PIN)
    page = shop.client.get(f"/pos/rejects?sale=S-{sale:06d}").text
    assert "WALLET SIZE PHOTO — 1/2 3r photo paper each" in page and f'value="S-{sale:06d}"' in page

    # A customer reprint needs the sale no.
    r = shop.client.post("/pos/rejects", data={"what": f"item:{wallet.id}", "qty": "2", "reason": "CUSTOMER REPRINT"})
    assert "type the sale no." in r.text
    assert "not found" in shop.client.post("/pos/rejects", data={"what": f"item:{wallet.id}", "qty": "2",
                                                                  "reason": "CUSTOMER REPRINT", "sale": "S-999999"}).text
    r = shop.client.post("/pos/rejects", data={"what": f"item:{wallet.id}", "qty": "2", "reason": "CUSTOMER REPRINT",
                                               "sale": f"s{sale}", "note": "faded"})
    assert "Reject saved: 1 3R PHOTO PAPER taken off the stock" in r.text
    r = shop.client.post("/pos/rejects", data={"what": f"material:{long_paper.id}", "qty": "3", "reason": "PAPER JAM"})
    assert "Reject saved: 3 LONG BOND PAPER" in r.text
    assert f"S-{sale:06d}</a>" in r.text and "faded" in r.text
    assert "Choose why" in shop.client.post("/pos/rejects", data={"what": f"material:{long_paper.id}", "qty": "1"}).text
    assert shop.client.get("/pos/stock", follow_redirects=False).status_code in (303, 403)  # Stock stays admin-only

    m = materials(shop)
    assert m["3R PHOTO PAPER"].stock_qty == 48 and m["LONG BOND PAPER"].stock_qty == 97
    with Session(shop.engine) as s:
        move = s.exec(select(PosStockMove).where(PosStockMove.kind == "reject", PosStockMove.sale_id == sale)).one()
    assert (move.qty, move.cost_cents, move.reason, move.note) == (-1, 500, "CUSTOMER REPRINT", "2 × PRINTING WALLET SIZE PHOTO · FADED")

    # Voiding the sale puts back what it sold, not the reprint's wasted sheet.
    from tests.conftest import ADMIN_PHONE
    shop.sign_in(ADMIN_PHONE, ADMIN_PIN)
    shop.client.post(f"/pos/api/sales/{sale}/void", json={"reason": "test", "admin_pin": ADMIN_PIN})
    assert materials(shop)["3R PHOTO PAPER"].stock_qty == 49
    page = shop.client.get("/pos/stock").text
    assert "Rejects: <strong>₱5.00</strong> at cost (customer reprint ₱5.00, paper jam ₱0.00" in page
    assert "ENCODER" in shop.client.get("/pos/rejects").text  # admins see who recorded it


def test_tarpaulin_sizes(shop):
    """Tarp sizes are read as W X H in feet (the shop's prices and costs are set in Settings)."""
    from pos.controllers.stock_controller import tarp_size

    assert tarp_size("2x3") == (2, 3) and tarp_size("TARP 2X3") is None
