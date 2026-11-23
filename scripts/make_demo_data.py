#!/usr/bin/env python3
"""
Build a demo database with synthetic data for presentations and videos. No real customer data is used.

    venv/bin/python scripts/make_demo_data.py                 # creates ~/bps-demo
    venv/bin/python scripts/make_demo_data.py --dir ~/bps-demo --days 120 --force
    PORT=8002 BPS_DATA_DIR=~/bps-demo ./scripts/run_local.sh  # run BPS on the demo data: http://localhost:8002
    python scripts/make_demo_data.py --dir /data --force --random-pins   # inside an online container (see README)

It writes:
  <dir>/bills_admin.db           users, biller rules, ~N days of bill payments, and two weeks of register data:
                                 a pick list, materials stock (restocks, counts), sales with bills, split and
                                 GCash/Maya payments and tarpaulins (with tarp jobs for BEN), rejects, and each
                                 day closed at End of day
  <dir>/demo-import-messy.csv    a small CSV with the messy patterns of real spreadsheets, for the import demo
  <dir>/.env                     a session secret, so run_local.sh can start straight away

Today is left empty so the live demo starts from a clean counter. Refuses to touch ~/bps-data
(the live data) or the project folder's dev database.
"""
import argparse
import asyncio
import csv
import os
import random
import secrets
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
LIVE_DIR = Path(os.path.expanduser("~/bps-data")).resolve()

DEMO_USERS = [
    # (first, last, phone, PIN, role)
    ("DEMO", "OWNER", "09170000100", "2580", "admin"),
    ("ANA", "DEMO", "09170000101", "1470", "encoder"),
    ("BEN", "DEMO", "09170000102", "3690", "encoder"),
]

FIRST_NAMES = [
    "MARIA", "JOSE", "ANGELO", "KRISTINE", "MARK", "JENNY", "PAOLO", "RHEA", "JOHN", "CARLA", "NIÑO", "LIZA",
    "RAMON", "GRACE", "ARVIN", "JOY", "DENNIS", "MICA", "ROLANDO", "TRISHA", "EDGAR", "BEA", "NOEL", "IVY",
]
LAST_NAMES = [
    "SANTOS", "REYES", "CRUZ", "BAUTISTA", "OCAMPO", "GARCIA", "MENDOZA", "TORRES", "VILLANUEVA", "RAMOS",
    "AQUINO", "CASTILLO", "FLORES", "DE LEON", "NAVARRO", "SALAZAR", "PASCUAL", "MERCADO", "AGUILAR", "LOPEZ",
]
# Biller -> (typical bill range in pesos, share of customers)
BILL_RANGES = {
    "MERALCO": ((600, 4500), 30),
    "STA MARIA WATER": ((250, 1200), 14),
    "PRIME WATER": ((300, 1400), 8),
    "CONVERGE": ((1299, 2499), 10),
    "PLDT FIBER": ((1299, 2899), 8),
    "GLOBE AT HOME": ((1299, 1999), 6),
    "SMART POSTPAID": ((599, 1999), 5),
    "GLOBE POSTPAID": ((599, 1799), 5),
    "SSS": ((570, 2400), 4),
    "EASY TRIP": ((500, 1000), 4),
    "AUTO SWEEP RFID": ((500, 1000), 3),
    "MAYNILAD": ((300, 1500), 3),
}
# Hour -> relative traffic: morning and after-work peaks, quiet at lunch.
HOUR_WEIGHTS = {8: 4, 9: 9, 10: 10, 11: 7, 12: 4, 13: 5, 14: 6, 15: 7, 16: 9, 17: 10, 18: 7, 19: 3}

# Register pick list: service -> [(item, made-up price in pesos, quantity range, how often)]. Not the shop's prices.
PICK_LIST = {
    "PRINTING": [("SHORT B&W", 5, (1, 20), 10), ("SHORT COLORED", 10, (1, 10), 6), ("A4 B&W", 5, (1, 20), 6),
                 ("A4 COLORED", 12, (1, 10), 4), ("LONG B&W", 6, (1, 15), 3), ("WALLET SIZE PHOTO", 15, (2, 8), 3),
                 ("4R PHOTO", 25, (1, 4), 2), ("A4 PHOTO PRINT", 40, (1, 3), 2)],
    "XEROX": [("SHORT", 3, (1, 40), 9), ("LONG", 4, (1, 30), 5), ("A4", 3, (1, 30), 4), ("SHORT BACK TO BACK", 5, (1, 20), 2)],
    "ID PICTURE": [("1X1 (8 PCS)", 60, (1, 2), 3), ("2X2 (4 PCS)", 60, (1, 2), 3), ("PASSPORT SIZE", 80, (1, 1), 1)],
    "LAMINATION": [("ID SMALL", 20, (1, 3), 3), ("SHORT", 30, (1, 2), 2), ("A4", 35, (1, 2), 1)],
    "SCAN": [("SCAN TO EMAIL", 10, (1, 5), 3)],
    "TARPAULIN": [("2X3", 280, (1, 1), 0), ("3X4", 450, (1, 1), 0), ("4X6", 650, (1, 1), 0)],
}
# What customers asked for on their tarpaulins (made up).
TARP_SPECS = [
    "Happy 7th Birthday, Ana!\nPink and gold, princess theme\nPhoto sent on Messenger",
    "Congratulations, Class of 2026!\nBlue and white, school logo (customer will email it)",
    "FOR RENT - 0917 000 0000\nBig red letters, white background",
    "Welcome Home, Tatay!\nFamily photo on Messenger; add the date at the bottom",
    "Sari-sari store sign: ALING NENA'S STORE\nGreen, with a basket drawing",
]
# Opening stock bought two weeks ago: material -> (quantity, made-up total cost in pesos, low-stock level).
# 4R paper is bought short so it shows as low; 5R paper isn't bought (out of stock, never counted).
OPENING_STOCK = {
    "SHORT BOND PAPER": (1500, 675, 300), "LONG BOND PAPER": (1000, 520, 100), "A4 BOND PAPER": (1000, 480, 200),
    "A4 PHOTO PAPER": (100, 650, 20), "3R PHOTO PAPER": (200, 300, 40), "4R PHOTO PAPER": (40, 120, 20),
    "LAMINATION FILM ID SMALL": (200, 240, 40), "LAMINATION FILM SHORT": (100, 350, 20), "LAMINATION FILM A4": (100, 400, 20),
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", default="~/bps-demo", help="demo data folder (default ~/bps-demo)")
    p.add_argument("--days", type=int, default=120, help="days of bill history before today (default 120)")
    p.add_argument("--seed", type=int, default=2026, help="random seed, for the same data every time")
    p.add_argument("--force", action="store_true", help="replace an existing demo database in --dir")
    p.add_argument(
        "--random-pins",
        action="store_true",
        help="give the demo accounts new random PINs (printed once) instead of the ones in this file; use it online",
    )
    return p.parse_args()


def safe_target(raw: str, force: bool) -> Path:
    target = Path(os.path.expanduser(raw)).resolve()
    if target == LIVE_DIR or LIVE_DIR in target.parents or target in LIVE_DIR.parents:
        sys.exit(f"Refusing: {target} is or contains the live data folder {LIVE_DIR}.")
    if target == PROJECT_DIR or PROJECT_DIR in target.parents:
        sys.exit("Refusing: pick a folder outside the project, so the dev database is never replaced.")
    db = target / "bills_admin.db"
    if db.exists():
        if not force:
            sys.exit(f"{db} already exists. Pass --force to replace it.")
        db.unlink()
    target.mkdir(parents=True, exist_ok=True)
    return target


def account_for(rule, rng: random.Random) -> str:
    digits = rule.account_digits or 10
    if rule.account_format == "ALPHANUMERIC":
        return "".join(rng.choice("0123456789") for _ in range(digits - 2)) + rng.choice("ABCDEFGH") + rng.choice("0123456789")
    return str(rng.randint(1, 9)) + "".join(rng.choice("0123456789") for _ in range(digits - 1))


def phone(rng: random.Random) -> str:
    return rng.choice(["0917", "0918", "0919", "0927", "0945", "0956", "0966", "0977"]) + f"{rng.randint(0, 9_999_999):07d}"


def round_cash(total: float, rng: random.Random) -> float:
    for step in (100, 500, 1000):
        if rng.random() < 0.5:
            return float(-(-total // step) * step)
    return round(total, 2)


async def build(target: Path, days: int, rng: random.Random) -> dict:
    os.environ["DATABASE_DIR"] = str(target)
    sys.path.insert(0, str(PROJECT_DIR))
    from sqlmodel import select

    from app import database as app_db
    from app.auth import hash_pin
    from app.models import BillerRule, BillRecord, BusinessProfile, Customer, UserAccount
    from pos import database as pos_db
    from pos.controllers import sale_controller as sales
    from pos.models import PosNetwork, PosSale, PosService, PosWallet, PosWalletTxn
    from pos.schemas import SaleIn, SaleLineIn, WalletTxnIn

    await app_db.init_db()
    await pos_db.init_db()
    counts = {}
    async with app_db.AsyncSessionLocal() as db:
        users = []
        for first, last, ph, pin, role in DEMO_USERS:
            pin_hash, pin_salt = hash_pin(pin)
            user = UserAccount(first_name=first, last_name=last, phone=ph, pin_hash=pin_hash, pin_salt=pin_salt, role=role)
            db.add(user)
            users.append(user)
        await db.flush()
        admin, ana, ben = users
        db.add(BusinessProfile(
            admin_user_id=admin.id, business_name="DEMO PRINT SHOP", business_address="123 SAMPLE ST., DEMO CITY",
            business_phone="09170000100", receipt_footer="DEMO DATA ONLY",
        ))

        with open(PROJECT_DIR / "sample_biller_rules.csv", newline="") as f:
            for row in csv.DictReader(f):
                db.add(BillerRule(
                    biller=row["BILLER"].strip().upper(),
                    service_charge=float(row["SERVICE_CHARGE"]), system_charge_cash=float(row["CASH"]),
                    system_charge_gcash=float(row["GCASH"]), system_charge_maya=float(row["MAYA"]),
                    system_charge_bayad=float(row["BAYAD"]), system_charge_bpi_cc=float(row["BPI CREDIT CARD"]),
                    system_charge_bpi=float(row["BPI"]), late_charge=float(row["LATE_CHARGE"]),
                    account_digits=int(row["ACCOUNT_DIGITS"]) if row["ACCOUNT_DIGITS"] else None,
                    is_active=row["IS_ACTIVE"].strip() == "1", account_format=row["ACCOUNT_FORMAT"].strip() or "NUMERIC",
                ))
        await db.flush()
        rules = {r.biller: r for r in (await db.execute(select(BillerRule))).scalars().all()}

        # Synthetic customers: each pays one biller, roughly monthly.
        billers = [b for b in BILL_RANGES if b in rules]
        weights = [BILL_RANGES[b][1] for b in billers]
        customers = []
        for _ in range(260):
            biller = rng.choices(billers, weights)[0]
            customers.append({
                "biller": biller, "account": account_for(rules[biller], rng),
                "name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}", "phone": phone(rng),
                "day": rng.randint(1, 28),
            })

        today = date.today()
        hours, hour_w = list(HOUR_WEIGHTS), list(HOUR_WEIGHTS.values())
        bills = 0
        latest = {}
        for offset in range(days, 0, -1):
            day = today - timedelta(days=offset)
            if day.weekday() == 6 and rng.random() < 0.7:
                continue  # mostly closed on Sundays
            due_soon = [c for c in customers if abs(c["day"] - day.day) <= 2]
            walk_ins = rng.sample(customers, k=min(len(customers), rng.randint(3, 8)))
            for c in due_soon + walk_ins:
                if rng.random() < 0.35:
                    continue
                rule = rules[c["biller"]]
                low, high = BILL_RANGES[c["biller"]][0]
                bill_amt = round(rng.uniform(low, high), 2)
                due = day + timedelta(days=rng.randint(-2, 14))
                late = rule.late_charge if due < day else 0.0
                total = round(bill_amt + late + rule.service_charge, 2)
                method = rng.choices(["CASH", "GCASH", "MAYA"], [85, 10, 5])[0]
                cash = round_cash(total, rng) if method == "CASH" else total
                at = datetime.combine(day, time(rng.choices(hours, hour_w)[0], rng.randint(0, 59), rng.randint(0, 59)))
                channel = rng.choices(["BAYAD", "CASH", "GCASH"], [55, 25, 20])[0]
                encoder = rng.choice([ana, ben])
                db.add(BillRecord(
                    txn_datetime=at, txn_date=day, account=c["account"], biller=c["biller"], customer_name=c["name"],
                    cp_number=c["phone"], bill_amt=bill_amt, late_charge=late, charge=rule.service_charge, total=total,
                    cash=cash, change_amt=round(cash - total, 2), due_date=due, payment_method=method,
                    payment_channel=channel, reference=f"DEMO-{day:%Y%m%d}-{rng.randint(0, 0xFFFFFF):06X}",
                    payment_reference=f"PAY-{rng.randint(10**9, 10**10 - 1)}", settled_at=at + timedelta(hours=1),
                    processed_by_user_id=encoder.id, created_by_user_id=encoder.id, created_at=at, updated_at=at,
                ))
                latest[c["account"]] = c
                bills += 1
        for c in latest.values():
            db.add(Customer(account=c["account"], biller=c["biller"], customer_name=c["name"], phone=c["phone"]))
        await db.commit()
        counts["bill payments"] = bills
        counts["customers"] = len(latest)

        counts.update(await build_register(db, today, customers, rules, admin, ana, ben, rng))
    await app_db.engine.dispose()
    return counts


async def build_register(db, today: date, customers: list, rules: dict, admin, ana, ben, rng: random.Random) -> dict:
    """Two weeks of register data, made through the register's own code, then dated back to the day it happened."""
    from sqlalchemy import update
    from sqlmodel import select

    from app.models import BillRecord
    from pos.controllers import eod_controller as eod
    from pos.controllers import sale_controller as sales
    from pos.controllers import stock_controller as stock
    from pos.controllers.settings_controller import get_settings
    from pos.models import PosMaterial, PosNetwork, PosSale, PosService, PosServiceItem, PosWallet, PosWalletTxn
    from pos.models.sale import PosSaleBill
    from pos.models.stock import PosStockMove
    from pos.models.tarp_job import PosTarpJob
    from pos.schemas import BillIn, SaleIn, SaleLineIn, WalletTxnIn

    hours, hour_w = list(HOUR_WEIGHTS), list(HOUR_WEIGHTS.values())
    counts = {"shop sales": 0, "bills paid in a sale": 0, "GCash/Maya transactions": 0, "rejects": 0, "days closed": 0}
    used_refs: set[str] = set()

    def ref(prefix: str) -> str:
        while True:
            value = f"{prefix}{rng.randint(10**9, 10**10 - 1)}"
            if value not in used_refs:
                used_refs.add(value)
                return value

    def at(day: date) -> datetime:
        return datetime.combine(day, time(rng.choices(hours, hour_w)[0], rng.randint(0, 59), rng.randint(0, 59)))

    async def date_sale(sale, when: datetime) -> None:
        """Everything the register saved for the sale gets the sale's time instead of now."""
        sale.created_at = when
        db.add(sale)
        await db.execute(update(PosStockMove).where(PosStockMove.sale_id == sale.id).values(created_at=when))
        await db.execute(update(PosWalletTxn).where(PosWalletTxn.sale_id == sale.id).values(created_at=when))
        await db.execute(update(PosTarpJob).where(PosTarpJob.sale_id == sale.id).values(created_at=when, updated_at=when))
        bill_ids = select(PosSaleBill.bill_record_id).where(PosSaleBill.sale_id == sale.id)
        for bill in (await db.execute(select(BillRecord).where(BillRecord.id.in_(bill_ids)))).scalars().all():
            bill.txn_datetime, bill.txn_date, bill.created_at, bill.updated_at = when, when.date(), when, when
            bill.settled_at = when + timedelta(hours=1)
            if bill.reference and bill.reference.startswith("REF-"):  # REF-<date>-…: the sale's date, not today's
                bill.reference = f"REF-{when:%Y%m%d}-" + bill.reference.split("-", 2)[-1]
            db.add(bill)

    # Example settings (made up): tarpaulin sent out to print, and a 2% load discount on the Maya account.
    settings = await get_settings(db)
    settings.tarp_cost_sqft_cents, settings.tarp_small_below_sqft = 1_200, 6
    settings.tarp_small_price_cents, settings.tarp_small_cost_cents = 30_000, 9_000
    settings.default_starting_cash_cents = 500_000
    settings.tarp_designer_user_id = ben.id  # BEN lays out the tarpaulins (Tarp jobs)
    db.add(settings)
    wallets = {w.name: w for w in (await db.execute(select(PosWallet))).scalars().all()}
    if "MAYA" in wallets:
        wallets["MAYA"].load_discount_bp = 200
        db.add(wallets["MAYA"])

    # Pick list, then Stock's own set-up adds the materials and links the items to them.
    services = {s.name: s.id for s in (await db.execute(select(PosService))).scalars().all()}
    menu = []
    for service, items in PICK_LIST.items():
        for order, (name, price, qty_range, weight) in enumerate(items):
            db.add(PosServiceItem(service_id=services[service], name=name, price_cents=price * 100, sort_order=order))
            if weight:
                menu.append((service, name, price, qty_range, weight))
    await db.commit()
    await stock.set_up_suggested(db, admin.id)
    items = {(i.service_id, i.name): i for i in (await db.execute(select(PosServiceItem))).scalars().all()}
    materials = {m.name: m for m in (await db.execute(select(PosMaterial))).scalars().all()}
    start = today - timedelta(days=14)
    for name, (qty, cost, low) in OPENING_STOCK.items():
        material = materials[name]
        material.low_stock_at = low
        db.add(material)
        move = await stock.restock(db, material.id, str(qty), str(cost), "DEMO SUPPLIER", "Opening stock", admin.id)
        move.created_at = datetime.combine(start, time(7, 30))
        material.counted_at = move.created_at
        db.add_all([move, material])
    await db.commit()

    networks = [n.id for n in (await db.execute(select(PosNetwork))).scalars().all()]
    wallet_ids = [w.id for w in wallets.values()]
    wallet_open = {w: 3_000_000 for w in wallet_ids}  # pesos in each GCash/Maya app, carried from day to day
    weights = [m[4] for m in menu]
    for offset in range(14, 0, -1):
        day = today - timedelta(days=offset)
        if day.weekday() == 6:
            continue
        reprint_candidates = []
        for _ in range(rng.randint(12, 24)):
            cashier = rng.choice([ana, ben])
            lines = []
            for _ in range(rng.choices([1, 2, 3], [70, 22, 8])[0]):
                service, name, price, qty_range, _w = rng.choices(menu, weights)[0]
                lines.append(SaleLineIn(kind="service", service_id=services[service], description=name,
                                        qty=rng.randint(*qty_range), unit_price=str(price)))
            if rng.random() < 0.25:
                lines.append(SaleLineIn(kind="load", network_id=rng.choice(networks), wallet_id=rng.choice(wallet_ids),
                                        mobile_no=phone(rng), amount=str(rng.choice([20, 50, 99, 100, 299]))))
            if rng.random() < 0.08:  # a bill paid together with the printing
                c = rng.choice(customers)
                low, high = BILL_RANGES[c["biller"]][0]
                lines.append(SaleLineIn(kind="bill", bill=BillIn(
                    account=c["account"], biller=c["biller"], customer_name=c["name"], cp_number=c["phone"],
                    due_date=day + timedelta(days=rng.randint(1, 10)), bill_amt=f"{rng.uniform(low, high):.2f}",
                    payment_reference=ref("PAY-"))))
            pay = rng.choices(["cash", "split", "wallet"], [86, 7, 7])[0]
            data = SaleIn(lines=lines, cash="20000")
            wallet = rng.choice(wallet_ids)
            if pay == "wallet":
                data = SaleIn(lines=lines, payment_method="wallet", pay_wallet_id=wallet, payment_reference=ref("W"))
            elif pay == "split":
                data = SaleIn(lines=lines, cash="20000", split_wallet_id=wallet, split_amount="20", split_reference=ref("W"))
            try:
                sale = await sales.create_sale(db, data, cashier)
            except sales.PosError:
                continue  # e.g. the split was more than a small total; skip it
            await date_sale(sale, at(day))
            await db.commit()
            counts["shop sales"] += 1
            counts["bills paid in a sale"] += sum(1 for line in lines if line.kind == "bill")
            if any(line.description in ("WALLET SIZE PHOTO", "4R PHOTO", "A4 PHOTO PRINT") for line in lines):
                reprint_candidates.append(sale)
        if rng.random() < 0.3:  # a tarpaulin: a pick list size, or a small one typed in
            size, price = rng.choice([("2X3", 280), ("3X4", 450), ("4X6", 650), ("1X2", 300)])
            sale = await sales.create_sale(db, SaleIn(lines=[SaleLineIn(
                kind="service", service_id=services["TARPAULIN"], description=size, unit_price=str(price))],
                cash="1000", customer_name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
                tarp_specs=rng.choice(TARP_SPECS)), admin)
            await date_sale(sale, at(day))
            await db.commit()
            counts["shop sales"] += 1
        for _ in range(rng.randint(2, 6)):
            txn = await sales.create_wallet_txn(db, WalletTxnIn(
                kind=rng.choices(["cash_in", "cash_out"], [45, 55])[0], wallet_id=rng.choice(wallet_ids),
                amount=str(rng.choice([500, 1000, 1500, 2000, 3000])), customer_mobile=phone(rng), reference=ref("W"),
                tendered="6000",
            ), rng.choice([ana, ben]))
            txn.created_at = at(day)
            db.add(txn)
            counts["GCash/Maya transactions"] += 1
        await db.commit()

        # Rejects: a misprint or paper jam most days, and now and then a customer reprint of that day's photo.
        rejects = []
        if rng.random() < 0.6:
            item = items[(services["PRINTING"], rng.choice(["SHORT COLORED", "A4 COLORED", "SHORT B&W"]))]
            rejects.append((f"item:{item.id}", str(rng.randint(1, 3)), "MISPRINT", "", rng.choice(["", "FADED", "WRONG FILE"])))
        if rng.random() < 0.3:
            rejects.append((f"material:{materials['SHORT BOND PAPER'].id}", str(rng.randint(1, 2)), "PAPER JAM", "", ""))
        if reprint_candidates and rng.random() < 0.3:
            sale = rng.choice(reprint_candidates)
            item = items[(services["PRINTING"], "WALLET SIZE PHOTO")]
            rejects.append((f"item:{item.id}", "2", "CUSTOMER REPRINT", sale.sale_no, "CUSTOMER WANTED IT LIGHTER"))
        for what, qty, reason, sale_ref, note in rejects:
            for move in await stock.record_reject(db, what, qty, reason, sale_ref, note, rng.choice([ana, ben]).id):
                move.created_at = at(day)
                db.add(move)
            counts["rejects"] += 1

        # Saturday stock count: a few sheets of bond paper are always missing.
        if day.weekday() == 5:
            for name in ("SHORT BOND PAPER", "A4 BOND PAPER"):
                material = materials[name]
                await db.refresh(material)
                move = await stock.count(db, material.id, str(max(0, int(material.stock_qty) - rng.randint(2, 8))),
                                         "Weekly count", admin.id)
                move.created_at = material.counted_at = datetime.combine(day, time(19, 15))
                db.add_all([move, material])
        await db.commit()

        # End of day: the admin counts the drawer (now and then a little over or short) and the GCash/Maya apps.
        # A GCash/Maya app that ran low is topped up from the bank before opening.
        topped = [w for w in wallet_ids if wallet_open[w] < 2_000_000]
        for w in topped:
            wallet_open[w] += 3_000_000
        form = {"opening_cash": "5000", "wallets": [{"wallet_id": w, "opening": f"{wallet_open[w] / 100:.2f}"} for w in wallet_ids]}
        report = await eod.save_close(db, day, form, admin)
        diff = rng.choices([0, 0, 0, -2_000, 1_000, -5_000], [50, 10, 10, 12, 10, 8])[0]
        form["counted_cash"] = f"{max(0, report.expected_cash_cents + diff) / 100:.2f}"
        notes = [] if not diff else ["SHORT, CHECKED THE RECEIPTS" if diff < 0 else "OVER, EXACT CHANGE NOT GIVEN"]
        names = {w.id: w.name for w in wallets.values()}
        notes += [f"{names[w]} TOPPED UP ₱30,000 FROM THE BANK" for w in topped]
        form["notes"] = "; ".join(notes)
        for item in form["wallets"]:
            expected = next(w.expected_cents for w in report.wallets if w.wallet.id == item["wallet_id"])
            item["counted"] = f"{max(0, expected) / 100:.2f}"
            wallet_open[item["wallet_id"]] = expected
        report = await eod.save_close(db, day, form, admin)
        report.close.closed_at = datetime.combine(day, time(20, rng.randint(0, 30)))
        db.add(report.close)
        await db.commit()
        counts["days closed"] += 1

    # Tarp jobs: older ones claimed, the last few days' still moving through the steps.
    tarp_jobs = (await db.execute(select(PosTarpJob).order_by(PosTarpJob.created_at))).scalars().all()
    for job in tarp_jobs:
        age = (today - job.created_at.date()).days
        job.status = "claimed" if age > 4 else rng.choice(["layout", "approved", "sent", "ready"])
        job.updated_at = job.created_at + timedelta(days=min(age, 2), hours=2)
        job.claimed_at = job.updated_at if job.status == "claimed" else None
        if job.status in ("approved", "sent"):
            job.notes = rng.choice(["CUSTOMER OK'D THE LAYOUT ON MESSENGER", "BLUE BACKGROUND, BIG NAME", "PICKUP AFTER 3 PM"])
        db.add(job)
    await db.commit()
    counts["tarp jobs"] = len(tarp_jobs)
    return counts


MESSY_ROWS = [
    # The patterns from real spreadsheets, on made-up people: placeholders, phones that lost their 0,
    # +63, a phone typed in a number cell, a date with a time, a charge that differs from the rule,
    # a biller with no rule (skipped) and a repeated row (duplicate).
    ["{d}", "8412057391", "MERALCO", "JUANA DELA PAZ", "9171234567", "1285.45", "0", "20", "1305.45", "1500", "194.55", ""],
    ["{d}", "5401983276", "MERALCO", "PEDRO PENDUKO", "NA", "965.20", "0", "20", "985.20", "1000", "14.80", ""],
    ["{us} 9:14:12", "30155792041", "STA MARIA WATER", "LOLA BASYANG", "+63 918 765 4321", "420.00", "0", "20", "440.00", "500", "60.00", ""],
    ["{d}", "3015579204", "PLDT FIBER", "TOTOY MOLA", "9,191,112,222.00", "1499.00", "0", "30", "1529.00", "1600", "71.00", ""],
    ["{d}", "0017348809123", "CONVERGE", "INDAY BADIDAY", "#N/A", "1720.00", "0", "30", "1750.00", "1800", "50.00", "#NAME?"],
    ["{d}", "9988776655", "MERALCO", "MANG KANOR", "09175550000", "800.00", "0", "25", "825.00", "1000", "175.00", "CHARGE DIFFERS FROM RULE"],
    ["{d}", "1234567", "UNKNOWN BILLER CO", "NO RULE YET", "09175550001", "500.00", "0", "20", "520.00", "600", "80.00", ""],
    ["{d}", "8412057391", "MERALCO", "JUANA DELA PAZ", "9171234567", "1285.45", "0", "20", "1305.45", "1500", "194.55", ""],
]


def write_messy_csv(target: Path) -> Path:
    path = target / "demo-import-messy.csv"
    d = date.today() - timedelta(days=1)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["DATE", "ACCOUNT", "BILLER", "NAME", "NUMBER", "AMT", "LATE_CHARGE", "CHARGE", "TOTAL", "CASH", "CHANGE", "NOTES"])
        for row in MESSY_ROWS:
            w.writerow([row[0].format(d=d.isoformat(), us=f"{d.month}/{d.day}/{d.year}")] + row[1:])
    return path


def write_env(target: Path) -> None:
    env = target / ".env"
    if not env.exists():
        env.write_text(f"SESSION_SECRET={secrets.token_hex(32)}\nOTP_PROVIDER=local\nCOMMS_PROVIDER=local\n")
        env.chmod(0o600)


def random_pin() -> str:
    """A 4-digit PIN with at least three different digits and no run like 1234 or 9876."""
    while True:
        pin = f"{secrets.randbelow(10_000):04d}"
        steps = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
        if len(set(pin)) >= 3 and steps not in ({1}, {-1}):
            return pin


def main() -> None:
    args = parse_args()
    target = safe_target(args.dir, args.force)
    if args.random_pins:
        # The PINs above are in a public repo, so an online demo must not use them.
        DEMO_USERS[:] = [(first, last, ph, random_pin(), role) for first, last, ph, _pin, role in DEMO_USERS]
    rng = random.Random(args.seed)
    counts = asyncio.run(build(target, args.days, rng))
    csv_path = write_messy_csv(target)
    write_env(target)
    print(f"Demo data in {target}")
    for label, n in counts.items():
        print(f"  {n:>6,} {label}")
    print(f"  messy import file: {csv_path}")
    print("Sign in (synthetic accounts)" + (": write these PINs down, they are not shown again" if args.random_pins else ":"))
    for first, last, ph, pin, role in DEMO_USERS:
        print(f"  {role:<8} {first} {last}: phone {ph}, PIN {pin}")
    print(f"Run it with: PORT=8002 BPS_DATA_DIR={target} ./scripts/run_local.sh")
    print("Then open http://localhost:8002/auth/signin (port 8000 stays free for the live app)")


if __name__ == "__main__":
    main()
