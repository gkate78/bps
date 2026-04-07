# BPS

Operations-first billing and payment admin app for small businesses.

## Live App
- Production URL: [https://bps.apps.vibecamp.ph](https://bps.apps.vibecamp.ph)

## What BPS Does
BPS helps teams manage bill records end-to-end: encode customer bills, process settlement updates, track cash/online channels, and run daily reconciliation with audit-ready history.

## Core Capabilities
- **Auth and roles**: phone + 4-digit PIN, OTP signup verification, PIN reset, lockout policy, auth logs, role-based routing (`admin`, `encoder`, `customer`)
- **Record operations**: create/edit/delete bill records, searchable/paginated table, due-status/date filters, duplicate prevention (`txn_date + account + biller + amount`)
- **Payment tracking**: separate `confirmation_reference` and `payment_reference`, explicit `payment_channel`, and operator tracking through `processed_by_user_id`
- **CSV import (curated + raw)**: import into `bill_records` with operational defaults and preserve immutable source rows in `bill_record_import_raw` with `import_batch_id`
- **Reconciliation and reports**: EOD reconciliation with optional cash-on-hand variance, per-user reconciliation totals, and daily/monthly/yearly report summaries
- **Admin visibility tools**: on-demand transaction audit log, read-only Database View with auto-load + row search, and KPI-focused dashboards
- **Biller rules and receipts**: popup biller-rule maintenance, per-field receipt visibility toggles, and receipt footer controls
- **Customer dashboard**: phone-scoped bill visibility with account/biller filters and automatic `customer_accounts.user_id` linking on auth success

## Payment Method and Channel Rules
- Customer payment mode options: `CASH`, `GCASH`, `MAYA`, `BDO`, `BPI`
- Admin settlement channel options: `CASH`, `GCASH`, `MAYA`, `BAYAD`, `BPICC`, `BPI`
- `payment_method` and `payment_channel` are intentionally independent fields for operational auditability

## Local Development
### Run (Linux/macOS)
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open locally: `http://127.0.0.1:8000/auth/signin`

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
Supported headers (case-sensitive):
- `DATE` or `DATE/TIME`
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
- If `payment_reference` is blank and `REFERENCE` exists, `payment_reference` falls back to `REFERENCE`
- Import sets operational defaults for curated records (`payment_method=CASH`, `payment_channel=CASH`, and missing references fallback to `reference`)
- Every row is also persisted to immutable `bill_record_import_raw` with `import_batch_id` for traceability

Sample files:
- `import_bill_records_starter.csv`
- `sample_biller_rules.csv`

`sample_biller_rules.csv` headers:
- `BILLER`, `SERVICE_CHARGE`, `CASH`, `GCASH`, `MAYA`, `BAYAD`, `BPI CREDIT CARD`, `BPI`, `LATE_CHARGE`, `ACCOUNT_DIGITS`, `IS_ACTIVE`

## Project Docs
- `docs/WORKFLOW.md` - development loop and definition of done
- `docs/BACKLOG.md` - current priority queue (`NOW/NEXT/LATER/DONE`)
- `docs/DECISIONS.md` - architecture and product tradeoff history
