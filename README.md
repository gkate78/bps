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
- **Biller rules and receipts**: popup biller-rule maintenance, per-field receipt visibility toggles, and receipt footer controls; 58mm thermal receipt in bold Arial (12px details, 14px business name, 16px total) with amounts flush right
- **Works offline**: jQuery, DataTables, and fonts are served from `app/static/vendor/` (see its README), so no internet connection is needed to run the app
- **Customer dashboard**: phone-scoped bill visibility with account/biller filters and automatic `customer_accounts.user_id` linking on auth success

## Payment Method and Channel Rules
- Customer payment mode options: `CASH`, `GCASH`, `MAYA`, `BDO`, `BPI`
- Admin settlement channel options: `CASH`, `GCASH`, `MAYA`, `BAYAD`, `BPICC`, `BPI`
- `payment_method` and `payment_channel` are intentionally independent fields for operational auditability

## Local Development
Requires Python 3.12+ (tested on 3.12 and 3.14). `sqlmodel` is pinned to 0.0.44: later versions reject the timezone-naive datetimes the app stores.

### Run (Linux/macOS)
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open locally: `http://127.0.0.1:8000/auth/signin`

### Everyday local use (Linux/WSL)
Keep real data separate from development so code changes and test imports never touch it:

```bash
./scripts/run_local.sh          # start on http://127.0.0.1:8000, backing up first
./scripts/run_local.sh backup   # back up only
```

- Data lives in `~/bps-data/` (override with `BPS_DATA_DIR`): `bills_admin.db`, `.env` (generated with a random `SESSION_SECRET`), and `backups/` (last 30 kept, set `BPS_BACKUP_KEEP` to change).
- For development, run `uvicorn main:app --reload --port 8001`; it uses the throwaway `bills_admin.db` in the project folder.
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

### Windows (PowerShell) quickstart
```powershell
./scripts/dev.ps1 setup
./scripts/dev.ps1 run
```

### Quick checks
```powershell
./scripts/dev.ps1 check
```

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
