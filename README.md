# BPAY

Admin dashboard for managing billing records from a Google Sheet export.

## Features
- SQLite-backed records
- Signup/Signin with phone + 4-digit PIN
- OTP-based signup verification and PIN reset flow
- PIN policy + signin lockout controls + auth event logging
- Session login with role-based routing (`admin`, `encoder`, or `customer`)
- Server-side DataTables endpoint (search, sort, pagination)
- Filters: biller, transaction date range, due status
- CRUD: create, edit, delete records
- Transaction audit log for record state changes (create, update, delete, CSV import) with admin visibility
- CSV import endpoint for bulk loading sheet exports
- Routing decision engine (BPS-207 slice): suggests `ONLINE` vs `BRANCH_MANUAL` using urgency-first rules and availability fallback
- Customer confirmation trigger after submission (BPS-209 slice): sends SMS/Viber-style confirmation via local/provider-agnostic service
- Reconciliation report supports optional cash-on-hand input with variance/status summary
- Reports tab for daily/monthly/yearly reconciliation summaries
- Customer dashboard now shows all bills tied to a phone number with dynamic account/biller filters
- Admin pages include KPI cards, sticky filters, and status chips for faster scanning
- Admin Settings includes popup biller-rule form (Add/Update) and per-field receipt visibility toggles beside business inputs (including receipt footer)
- Admin Records keeps Transaction Audit Log hidden by default and loads it on demand
- Admin Database View (`/admin/database`) provides read-only table browsing with sticky selector controls
- Payment capture now keeps `payment_reference` and `confirmation_reference` as separate fields across entry, admin edit, and CSV import
- Customer entry payment modes are `CASH`, `GCASH`, `MAYA`, `BDO`, `BPI`; admin processing/edit supports `CASH`, `GCASH`, `MAYA`, `BAYAD`, `BPICC`, `BPI`
- Payment channel is stored as encoded/edited (`payment_channel`) and can be explicitly set in admin edit along with mode of payment
- Data entry/payment dialogs now place `Mode of Payment` before amount input, position `confirmation_reference` immediately after mode, and hide suggested routing from the entry screen
- Duplicate detection by `txn_date + account + biller + amount` (create, update, import)
- Auto-generated unique reference code when missing
- Validation guards for due date and amount before save
- Phone validation: exactly 11 digits
- CP number validation: exactly 11 digits when provided
- Text normalization: form text values are standardized to uppercase before persistence
- Amount display formatting: comma separators with 2 decimal places on key views

## Run
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open: `http://127.0.0.1:8000/auth/signin`

### Windows (PowerShell) quickstart
```powershell
./scripts/dev.ps1 setup
./scripts/dev.ps1 run
```

### Quick checks
```powershell
./scripts/dev.ps1 check
```

### OTP development mode
Signup now uses OTP verification before account creation.
By default, OTP runs in local stub mode and logs the code in server output:

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

PIN recovery flow is available from Sign In via `Forgot PIN` (`/auth/pin/reset`).

### Admin phone configuration
Set admin phone numbers (comma-separated) so those users land on admin dashboard after login:

```bash
export ADMIN_PHONES=09171234567,09179998888
```

If not listed, a signed-up user is treated as `customer`.

### Encoder phone configuration
Set encoder phone numbers (comma-separated) so those users land on form-only page after login:

```bash
export ENCODER_PHONES=09175556666,09174443333
```

`encoder` can access data entry form and create records, but not admin tables.

## CSV format
Headers supported (case-sensitive):
- `DATE` or `DATE/TIME`
- `ACCOUNT`
- `BILLER`
- `NAME`
- `NUMBER` or `CP NUM`
- `AMT` or `BILL AMT`
- `AMT2` or `LATE CHARGE`
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

Import note:
- If `payment_reference` is missing but `REFERENCE` exists, import falls back to `REFERENCE` for processed biller reference.

A masked sample is included: `sample_masked_records.csv`

### Biller rules CSV
Use `sample_biller_rules.csv` as a starter for Admin Settings import.
Biller rules headers:
- `BILLER`, `SERVICE_CHARGE`, `CASH`, `GCASH`, `MAYA`, `BAYAD`, `BPI CREDIT CARD`, `BPI`, `LATE_CHARGE`, `ACCOUNT_DIGITS`, `IS_ACTIVE`

## Workflow
Use these files as your working system:
- `docs/WORKFLOW.md` for the development loop and definition of done
- `docs/BACKLOG.md` for `NOW / NEXT / LATER` task planning
- `docs/DECISIONS.md` for architecture/product tradeoff history

Recommended cadence:
1. Pick one `NOW` item and create a focused branch.
2. Build and verify with `./scripts/dev.ps1 check`.
3. Update backlog + decisions, then commit with the task ID.
