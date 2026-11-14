# BPS

Operations-first billing and payment admin app for small businesses.

## Live App
- Production URL: [https://bps.apps.vibecamp.ph](https://bps.apps.vibecamp.ph)

## What BPS Does
BPS helps teams manage bill records end-to-end: encode customer bills, process settlement updates, track cash/online channels, and run daily reconciliation with audit-ready history.

## Core Capabilities
- **Auth and roles**: phone + 4-digit PIN, OTP signup verification, PIN reset, lockout policy, auth logs, role-based routing (`admin`, `encoder`, `customer`)
- **My Transactions** (button next to Save/Print/Clear on the entry form): each encoder sees the payments they entered (today by default, with a date range), their payment count and total collected, and can reprint receipts; based on `created_by_user_id`, which later admin edits don't change
- **Record operations**: create/edit/delete bill records, searchable/paginated table, due-status/date filters, duplicate prevention (`txn_date + account + biller + amount`)
- **Payment tracking**: separate `confirmation_reference` and `payment_reference`, explicit `payment_channel`, and operator tracking through `processed_by_user_id`
- **CSV import (curated + raw)**: import into `bill_records` with operational defaults and preserve immutable source rows in `bill_record_import_raw` with `import_batch_id`
- **Reconciliation and reports**: EOD reconciliation with optional cash-on-hand variance, per-user reconciliation totals, daily/monthly/yearly report summaries, and an **Amounts to review** list of imported records whose file amounts differ from biller rules or don't add up
- **Insights** (`/admin/insights`): KPI tiles with change vs the previous period, monthly/daily trend, biller share, late-payment rate by biller, weekday × hour busy-times heatmap, busiest days of the month, top customers, and regulars who haven't come back
- **Admin visibility tools**: on-demand transaction audit log, read-only Database View with auto-load + row search, and KPI-focused dashboards
- **Account format per biller**: each biller rule sets the account type, *Numbers only* or *Letters and numbers* (e.g. SSS `1A000000000001`, PhilHealth `SPA0A0000000001`), plus an optional exact length (`ACCOUNT_DIGITS`, counting all characters); enforced on the entry form and by the API for new records and account/biller changes
- **New billers during entry**: entering a biller with no rule opens a **New Biller** popup (service charge, late charge, account type, optional account length) that saves the rule and continues the entry; admins and encoders can add new rules this way, existing rules are edited only in Admin Settings, and each addition is audit-logged
- **Double-payment reminder**: a bill noted "DOUBLE PAYMENT ..." in Bills records (paid to the biller twice) shows a warning in the register's bill form when the same account or CP number is entered. In the shop sale, **Add ₱… paid back to this sale** adds the earlier bill's full amount as a DOUBLE PAYMENT PAID BACK line, paid with the sale and on its receipt, counted as received but not income; the warning stays until it's paid back
- **Late charges**: each biller rule's late charge for an overdue bill is a fixed amount, a percent of the bill amount (e.g. STA MARIA WATER 10%), or both. Overdue bills take the penalty printed on the bill when it's typed in, at the register (a **Late charge** field appears once the due date has passed; empty uses the rule) and on the entry form; editing a record keeps a late charge changed by hand
- **Biller rules and receipts**: popup biller-rule maintenance, per-field receipt visibility toggles, and receipt footer controls; 58mm thermal receipt in bold Arial (12px details, 14px business name, 16px total) with amounts flush right
- **Works offline**: jQuery, DataTables, and fonts are served from `app/static/vendor/` (see its README), so no internet connection is needed to run the app
- **Customer dashboard**: phone-scoped bill visibility with account/biller filters and automatic `customer_accounts.user_id` linking on auth success

## Shop Register (`/pos`)
The print shop's cash register runs inside BPS on the shop computer (on when `POS_ENABLED=1`, which `run_local.sh` sets; off on the online deployment). Use **Shop register →** in the top bar. Bills are entered in the register's **Bills payment** tab; after saving, **Shop sale for …** starts a separate shop sale with the customer's name and phone. Encoders work it as cashiers; admins also get its Settings.
- **Register**: shop services with typed prices (suggestions from past sales), loading (the network picked from the mobile no.: its last load here, else its prefix; fee added automatically; promos rounded up to the next ₱10), each account's load discount (Maya 3%: ₱96.03 for ₱99) taken into its balance and the load income, paid in cash or to the shop's GCash/Maya; **job orders** with a down payment (tarpaulin, invitations, …)
- **Personal (admin only)**: the owner's own bills, shop sales, loads and GCash/Maya with no service charge or fees. Choose **I pay** (money comes in as usual) or **From shop funds** (nothing is collected; End of day and Summary list these separately, while loads, cash-ins and bills paid to billers still lower the drawer or GCash/Maya). Receipts say PERSONAL. A personal cash-out can't be from shop funds (record cash taken out in End of day instead).
- **Sale + cash-out in one transfer**: a sale paid by GCash/Maya takes an optional **Amount sent**; anything above the amount due is a cash-out with its fee included (₱55 load + ₱1,020 = ₱1,075 sent → give ₱1,000). It is saved as the sale plus a linked cash-out under the same reference no., printed on one receipt, and voided with the sale. Amounts that don't fit are refused with the nearest total that works
- **Everything in one sale**: besides services and loads, the shop sale takes **CASH-IN**, **CASH-OUT** and **BILL** items, so a customer pays one total (e.g. ₱2,500 cash-in + ID picture + lamination, or a bill paid out of a ₱3,000 cash-out, the shop giving back the rest). Each is still saved in its own records (cash-ins/outs as GCash/Maya transactions, bills in the bills records with their own 2-copy receipts, printed with the sale receipt and marked PAID WITH SALE S-…), so Summary and End of day count them as before. A sale of **only bills** prints just each bill's 2-copy receipt, no sale receipt, showing the one payment: PAID VIA GCash/Maya or bank with its reference, the part paid by GCash/Maya, the cash handed over and the change, and with several bills PAID TOGETHER: n BILLS and their total (DEC-057). A sale with a cash-in or cash-out is settled in cash; otherwise it can be paid in cash, GCash/Maya, BDO or BPI. Not for job orders; cash-ins/outs not in personal sales. A sale with bills can't be voided until its bills are deleted or corrected in Bills records (DEC-055). **Part paid by GCash/Maya, the rest in cash**: a cash sale can take part of the total by GCash/Maya (whole pesos, its reference no. used once); the drawer expects only the cash part and the wallet the rest (DEC-056). The GCash / Maya and Bills payment tabs stay for now
- **Bills payment** tab: several bills (any billers and accounts) paid together with one cash, GCash, Maya, BDO or BPI payment. Each bill is saved to the bills records like before (same charges, checks, reference and SMS) and prints its own 2-copy receipt with the one payment (cash handed over and change, or the GCash/Maya/bank reference). The checkout is saved as a sale of only bills, so it's listed in **Sales** too; Summary and End of day still count the bills from the bills records only (DEC-057). GCash/Maya bills share one reference no. that can't be used again. With the register on, the bills entry form opens this tab instead (DEC-052). A bill for an account that already has a bill of the same amount this month (any biller) is refused as a duplicate (DEC-053). **Bills I entered today** lists them for reprinting
- **Edit before saving**: each item in the current sale has ✎ (puts it back in its form; Update replaces it in place) and ✕ (removes it)
- **Park** an unpaid sale or GCash/Maya transaction to serve the next customer first, then **Resume** it (not counted anywhere until it's paid)
- **Unsaved work survives a brownout**: the shop sale, GCash/Maya transaction and bills being rung up are saved on the server a moment after each change (one copy per cashier, removed when the transaction is saved, parked or cleared) and filled back in when the register opens again, on any shop computer the cashier signs in on (DEC-059). An item still being typed in its form isn't kept. A UPS for the register PC, router and printer is still recommended
- **GCash / Maya cash-in and cash-out** as their own transactions, with step-by-step instructions and the fee rule (₱20 per full ₱1,000 plus ₱10/₱20 on the remainder; loads of ₱50 or less +₱5). A cash-out fee can be deducted from the payout, included in the amount sent (customer sends ₱6,120 to get exactly ₱6,000), or paid in cash. Typing a mobile number used before (register or bill customers) fills in the customer name; a GCash/Maya reference no. is accepted only once across cash-ins, cash-outs and shop sales or job order payments paid by GCash/Maya (ignoring case and spaces; voided ones excluded), with a warning as soon as it is typed.
- **Job orders**: balances collected later, in parts if needed; **Sales** list (encoders see only their own transactions) with reprint (not for voided transactions: the button is greyed out and the receipt refused), and void (admins only, confirmed with their own PIN); **Summary** of shop income
- **End of day** (`/pos/eod`): one count for the whole counter. Expected cash = starting cash + bills paid in cash + shop cash + GCash/Maya cash-in − cash-out payouts − bills paid to billers in cash − cash taken out (± moves to/from GCash/Maya). Each GCash/Maya account gets an expected balance too. Bills count as paid to the biller when their payment reference is first entered (`settled_at`); Bayad/bank settlements are listed for reference. Encoders do a blind closing count for today: they enter the cash counted and each app balance and see the expected GCash/Maya balances, but not the expected cash or over/short; starting cash and opening balances stay admin-only, as does **Summary**. **Hand over drawer**: when the drawer is turned over mid-day, the outgoing cashier encodes every transaction of the shift (no parked ones left), counts the drawer and each app balance, and the reliever starts from that count; the admin sees each shift's expected, counted and over/short (adding up to the day's), and late entries into a closed shift are flagged.
- **Admin → Database** also shows the register's tables. **Backup to Google Sheets** (register Settings): paste the given Apps Script into your own Google Sheet, deploy it as a web app, and save its link; BPS then copies bills and shop records there with **Back up now** and after each End of day. It's a copy for viewing; restore from the `.db` backups.
- 58mm receipts, 1 copy, with the BPS business details and the footer "THIS IS NOT AN OFFICIAL RECEIPT" (the BIR invoice booklet is still used). Money is stored as integer centavos.
- Code in `pos/` (tables `pos_*` in the same database); design notes in DEC-045/DEC-046 and the register's plan (`cashreg/docs/PLAN.md`).

## Payment Method and Channel Rules
- Customer payment mode options: `CASH`, `GCASH`, `MAYA`, `BDO`, `BPI`
- Admin settlement channel options: `CASH`, `GCASH`, `MAYA`, `BAYAD`, `BPICC`, `BPI`
- `payment_method` and `payment_channel` are intentionally independent fields for operational auditability
- Cash is collected to the whole peso: under 50 centavos rounds down, 50 and up rounds up (₱1,025.45 → ₱1,025, so ₱1,100 gets ₱75 change; ₱1,025.50 → ₱1,026, ₱74 change). Bills paid in cash, shop sales and job order payments; End of day expects the rounded amounts. GCash/Maya/bank are not rounded, and totals stay exact (DEC-051).

## Local Development
Requires Python 3.12+ (tested on 3.12 and 3.14). `sqlmodel` is pinned to 0.0.44: later versions reject the timezone-naive datetimes the app stores.

### Run (Linux/macOS)
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

Open locally: `http://localhost:8001/auth/signin`. Port 8000 is left for everyday use (`run_local.sh`, below), so both can run at once. Use `localhost` for testing and `127.0.0.1` for everyday use: the browser keeps their sign-ins apart (on the same host, signing in on one port signs you out of the other).

### Everyday local use (Linux/WSL)
Keep real data separate from development so code changes and test imports never touch it:

```bash
./scripts/run_local.sh          # start on http://127.0.0.1:8000, backing up first
./scripts/run_local.sh backup   # back up only
```

- Data lives in `~/bps-data/` (override with `BPS_DATA_DIR`): `bills_admin.db`, `.env` (generated with a random `SESSION_SECRET`), and `backups/` (last 30 kept, set `BPS_BACKUP_KEEP` to change).
- For development, run `uvicorn main:app --reload --port 8001` and open `http://localhost:8001`; it uses the throwaway `bills_admin.db` in the project folder.
- `PORT` changes the port, e.g. `PORT=8002 ./scripts/run_local.sh`.
- To restore, stop the app and copy a file from `~/bps-data/backups/` over `~/bps-data/bills_admin.db`.
- New model columns are not added to existing databases automatically: add an `ALTER TABLE` step in `init_db()` in `app/database.py` for each one.

### Using BPS from other shop computers
One computer runs BPS and keeps the database; other computers on the shop network use a browser.

One-time setup on the computer that runs BPS:
1. In PowerShell **as Administrator**, from the project folder (e.g. `\\wsl.localhost\Ubuntu\home\<you>\projects\bps`):
   `powershell -ExecutionPolicy Bypass -File scripts\windows-network-setup.ps1`
   It switches WSL to mirrored networking, asks before marking the current network Private (answer yes only on the shop's own network), and opens port 8000 on Private networks to local-network addresses only. Undo the firewall rules with `-Remove`.
2. Run `wsl --shutdown`, reopen WSL, then start BPS with `./scripts/run_local.sh lan`. It prints the address for shop computers, e.g. `http://192.168.1.20:8000`.

Notes: traffic on the shop network is plain HTTP, so only use `lan` mode on a network you control. The BPS computer must stay on and awake while others use it. `./scripts/run_local.sh` without `lan` stays this-computer-only. Remote access from outside the shop is not set up (see DEC-042); the script's `-AllowTailscale` switch exists for if Tailscale is adopted later.

### Maintenance scripts
Run from the project root with `venv/bin/python`. Data-changing scripts are dry runs unless `--apply` is passed; back up first with `./scripts/run_local.sh backup`.

| Script | Purpose |
|---|---|
| `scripts/backup_db.py --db <path>` | Consistent SQLite backup (used by `run_local.sh`) |
| `scripts/repair_txn_times.py --db <path>` | Restore time of day on records imported before DATE values with times were kept |
| `scripts/clean_phone_numbers.py --db <path>` | Normalize stored phone numbers (blank `NA`, restore dropped leading 0) and fill customers' missing phones |
| `scripts/apply_file_amounts.py --db <path>` | Put the import file's own amounts back on records imported before file amounts were kept, flagging differences for review |
| `scripts/db_view.py` | Read-only database preview |
| `scripts/make_demo_data.py [--dir ~/bps-demo] [--days 120] [--force]` | Build a separate demo database with synthetic bills, register sales, demo accounts and a messy CSV for the import demo; run it with `PORT=8002 BPS_DATA_DIR=~/bps-demo ./scripts/run_local.sh` and open `http://localhost:8002`. Refuses `~/bps-data` and the project folder |
| `scripts/import_cashreg.py --from <cashreg.db> --db <path>` | One-time move of the standalone shop register's data into BPS (users matched by phone; backs up first; refuses if BPS already has register sales) |

### Windows (PowerShell) quickstart
```powershell
./scripts/dev.ps1 setup
./scripts/dev.ps1 run
```

### Quick checks
```powershell
./scripts/dev.ps1 check
```

### Tests
```bash
venv/bin/pip install -r requirements-dev.txt
venv/bin/python -m pytest -q
```
Each test runs the app against its own temporary database (`tests/conftest.py`); they currently cover the shop register and End of day.

## Environment Notes
### OTP development mode
Signup uses OTP verification before account creation. By default, OTP runs in local stub mode and logs OTP codes in server output.

```bash
export OTP_PROVIDER=local
export OTP_TTL_SECONDS=300
export PIN_MAX_FAILED_ATTEMPTS=5
export PIN_LOCKOUT_MINUTES=15
export PIN_WEAK_LIST=0000,1111,1234,4321
export ROUTING_URGENT_WINDOW_DAYS=3
export COMMS_PROVIDER=local
export COMMS_DEFAULT_CHANNEL=sms
```

PIN recovery is available at `Forgot PIN` (`/auth/pin/reset`).

### Role phone configuration
Set admin phones (comma-separated):

```bash
export ADMIN_PHONES=09171234567,09179998888
```

Set encoder phones (comma-separated):

```bash
export ENCODER_PHONES=09175556666,09174443333
```

If a signed-up phone is not configured as admin/encoder, it is treated as `customer`.

## CSV Import Format
Headers are matched ignoring case and extra spaces. `DATE` (or `DATE/TIME`), `ACCOUNT`, `BILLER`, and `NAME` are required: a file missing any of them is rejected before import with a message naming the missing columns. Columns with no usable header (blank or `#NAME?`) are ignored and reported as a warning.

Supported headers:
- `DATE` or `DATE/TIME` (a `DATE` value may include a time, e.g. `1/2/2026 9:14:12`, which is kept)
- `ACCOUNT`
- `BILLER`
- `NAME`
- `NUMBER` or `CP NUM`
- `AMT` or `BILL AMT`
- `LATE_CHARGE`, `LATE CHARGE`, or legacy `AMT2`
- `CHARGE` or `SERVICE CHARGE`
- `TOTAL`
- `CASH`
- `CHANGE`
- `DUE DATE`
- `NOTES`
- `REFERENCE`
- `confirmation_reference` (optional)
- `payment_reference` (optional)
- `payment_method` (optional)
- `payment_channel` (optional)

Import behavior:
- The file's own late charge, charge, total, and change are kept (they are what was actually collected); blank cells fall back to the biller rules. Rows whose amounts don't add up or differ from the rules are imported and flagged in **Reports → Amounts to review**. Editing such a record keeps its amounts unless an amount-related field changes.
- Spreadsheet placeholders (`#N/A`, `#NAME?`, `NA`, ...) are treated as blank.
- Phone numbers are normalized: a dropped leading 0 is restored (`9171234567` → `09171234567`), `+63` becomes `0`, number-formatted cells like `9,171,234,567.00` are read correctly, and placeholders or dates become blank.
- Saved customer details are never overwritten with blank values or with rows older than the account's latest payment, so importing an older file can't revert newer names or phone numbers.
- Rows for billers without an active rule are skipped; the result lists each skipped or duplicate row with its reason.
- If `payment_reference` is blank and `REFERENCE` exists, `payment_reference` falls back to `REFERENCE`
- Import sets operational defaults for curated records (`payment_method=CASH`, `payment_channel=CASH`, and missing references fallback to `reference`)
- Every row is also persisted to immutable `bill_record_import_raw` with `import_batch_id` for traceability

Sample files:
- `import_bill_records_starter.csv`
- `sample_biller_rules.csv`

`sample_biller_rules.csv` headers:
- `BILLER`, `SERVICE_CHARGE`, `CASH`, `GCASH`, `MAYA`, `BAYAD`, `BPI CREDIT CARD`, `BPI`, `LATE_CHARGE`, `ACCOUNT_DIGITS`, `IS_ACTIVE`, `ACCOUNT_FORMAT` (optional: `NUMERIC` or `ALPHANUMERIC`; when omitted, existing rules keep their format and new ones are `NUMERIC`)

## Project Docs
- `docs/WORKFLOW.md` - development loop and definition of done
- `docs/BACKLOG.md` - current priority queue (`NOW/NEXT/LATER/DONE`)
- `docs/DECISIONS.md` - architecture and product tradeoff history
