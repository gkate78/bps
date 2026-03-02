# BPAY

Admin dashboard for managing billing records from a Google Sheet export.

## Features
- SQLite-backed records
- Signup/Signin with phone + 4-digit PIN
- Session login with role-based routing (`admin`, `encoder`, or `customer`)
- Server-side DataTables endpoint (search, sort, pagination)
- Filters: biller, transaction date range, due status
- CRUD: create, edit, delete records
- CSV import endpoint for bulk loading sheet exports
- Duplicate detection by `txn_date + account + biller + amount` (create, update, import)
- Auto-generated unique reference code when missing
- Validation guards for due date and amount before save

## Run
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open: `http://127.0.0.1:8000/admin/records`

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
- `AMT2`
- `CHARGE` or `LATE CHARGE`
- `TOTAL`
- `CASH`
- `CHANGE`
- `DUE DATE`
- `NOTES`
- `REFERENCE`

A masked sample is included: `sample_masked_records.csv`
