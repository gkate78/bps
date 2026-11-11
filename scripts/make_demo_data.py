#!/usr/bin/env python3
"""
Build a demo database with synthetic data for presentations and videos. No real customer data is used.

    venv/bin/python scripts/make_demo_data.py                 # creates ~/bps-demo
    venv/bin/python scripts/make_demo_data.py --dir ~/bps-demo --days 120 --force
    PORT=8002 BPS_DATA_DIR=~/bps-demo ./scripts/run_local.sh  # run BPS on the demo data: http://localhost:8002

It writes:
  <dir>/bills_admin.db           users, biller rules, ~N days of bill payments, two weeks of register sales
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", default="~/bps-demo", help="demo data folder (default ~/bps-demo)")
    p.add_argument("--days", type=int, default=120, help="days of bill history before today (default 120)")
    p.add_argument("--seed", type=int, default=2026, help="random seed, for the same data every time")
    p.add_argument("--force", action="store_true", help="replace an existing demo database in --dir")
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
                    processed_by_user_id=encoder.id, created_by_user_id=encoder.id,
                ))
                latest[c["account"]] = c
                bills += 1
        for c in latest.values():
            db.add(Customer(account=c["account"], biller=c["biller"], customer_name=c["name"], phone=c["phone"]))
        await db.commit()
        counts["bill payments"] = bills
        counts["customers"] = len(latest)

        # Register: two weeks of shop sales, loads and GCash/Maya, through the register's own rules.
        services = {s.name: s.id for s in (await db.execute(select(PosService))).scalars().all()}
        networks = [n.id for n in (await db.execute(select(PosNetwork))).scalars().all()]
        wallets = {w.name: w.id for w in (await db.execute(select(PosWallet))).scalars().all()}
        menu = [("PRINTING", 5, (1, 30)), ("XEROX", 3, (1, 40)), ("ID PICTURE", 60, (1, 2)), ("LAMINATION", 20, (1, 3)),
                ("SCAN", 10, (1, 5))]
        shop, wallet_txns = 0, 0
        for offset in range(14, 0, -1):
            day = today - timedelta(days=offset)
            if day.weekday() == 6:
                continue
            for _ in range(rng.randint(10, 22)):
                name, price, qty_range = rng.choice(menu)
                lines = [SaleLineIn(kind="service", service_id=services[name], qty=rng.randint(*qty_range), unit_price=str(price))]
                if rng.random() < 0.3:
                    lines.append(SaleLineIn(kind="load", network_id=rng.choice(networks), wallet_id=rng.choice(list(wallets.values())),
                                            mobile_no=phone(rng), amount=str(rng.choice([20, 50, 99, 100, 299]))))
                sale = await sales.create_sale(db, SaleIn(lines=lines, cash="2000"), rng.choice([ana, ben]))
                sale.created_at = datetime.combine(day, time(rng.choices(hours, hour_w)[0], rng.randint(0, 59)))
                db.add(sale)
                shop += 1
            for _ in range(rng.randint(2, 6)):
                kind = rng.choice(["cash_in", "cash_out"])
                txn = await sales.create_wallet_txn(db, WalletTxnIn(
                    kind=kind, wallet_id=rng.choice(list(wallets.values())), amount=str(rng.choice([500, 1000, 2000, 3000, 5000])),
                    customer_mobile=phone(rng), reference=f"W{rng.randint(10**7, 10**8 - 1)}", tendered="6000",
                ), rng.choice([ana, ben]))
                txn.created_at = datetime.combine(day, time(rng.choices(hours, hour_w)[0], rng.randint(0, 59)))
                db.add(txn)
                wallet_txns += 1
            await db.commit()
        counts["shop sales"] = shop
        counts["GCash/Maya transactions"] = wallet_txns
    await app_db.engine.dispose()
    return counts


MESSY_ROWS = [
    # The patterns from real spreadsheets, on made-up people: placeholders, phones that lost their 0,
    # +63, a phone typed in a number cell, a date with a time, a charge that differs from the rule,
    # a biller with no rule (skipped) and a repeated row (duplicate).
    ["{d}", "8412057391", "MERALCO", "JUANA DELA PAZ", "9171234567", "1285.45", "0", "15", "1300.45", "1500", "199.55", ""],
    ["{d}", "5401983276", "MERALCO", "PEDRO PENDUKO", "NA", "965.20", "0", "15", "980.20", "1000", "19.80", ""],
    ["{us} 9:14:12", "30155792041", "STA MARIA WATER", "LOLA BASYANG", "+63 918 765 4321", "420.00", "0", "15", "435.00", "500", "65.00", ""],
    ["{d}", "3015579204", "PLDT FIBER", "TOTOY MOLA", "9,191,112,222.00", "1499.00", "0", "25", "1524.00", "1600", "76.00", ""],
    ["{d}", "0017348809123", "CONVERGE", "INDAY BADIDAY", "#N/A", "1720.00", "0", "25", "1745.00", "1800", "55.00", "#NAME?"],
    ["{d}", "9988776655", "MERALCO", "MANG KANOR", "09175550000", "800.00", "0", "20", "820.00", "1000", "180.00", "CHARGE DIFFERS FROM RULE"],
    ["{d}", "1234567", "UNKNOWN BILLER CO", "NO RULE YET", "09175550001", "500.00", "0", "15", "515.00", "600", "85.00", ""],
    ["{d}", "8412057391", "MERALCO", "JUANA DELA PAZ", "9171234567", "1285.45", "0", "15", "1300.45", "1500", "199.55", ""],
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


def main() -> None:
    args = parse_args()
    target = safe_target(args.dir, args.force)
    rng = random.Random(args.seed)
    counts = asyncio.run(build(target, args.days, rng))
    csv_path = write_messy_csv(target)
    write_env(target)
    print(f"Demo data in {target}")
    for label, n in counts.items():
        print(f"  {n:>6,} {label}")
    print(f"  messy import file: {csv_path}")
    print("Sign in (synthetic accounts):")
    for first, last, ph, pin, role in DEMO_USERS:
        print(f"  {role:<8} {first} {last}: phone {ph}, PIN {pin}")
    print(f"Run it with: PORT=8002 BPS_DATA_DIR={target} ./scripts/run_local.sh")
    print("Then open http://localhost:8002/auth/signin (port 8000 stays free for the live app)")


if __name__ == "__main__":
    main()
