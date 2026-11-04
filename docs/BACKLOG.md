# Backlog

## NOW
- [ ] BPS-210 | Theme: Reconciliation reliability | Outcome: Daily reconciliation snapshot finalization and history | Done when: user can finalize a day, persist immutable totals/variance, and review historical snapshots

## NEXT
- [ ] BPS-209 | Theme: Customer comms | Outcome: SMS/Viber confirmation with reference + posting ETA | Done when: message trigger is sent after submission (post-MVP)
- [ ] BPS-211 | Theme: Import observability | Outcome: Batch-level import review and replay tools | Done when: admin can filter by `import_batch_id`, inspect row outcomes, and optionally re-run selected skipped rows | Progress: import results now list skipped/duplicate rows with reasons (BPS-216)

## LATER
- [ ] BPS-223 | Theme: Operations insight | Outcome: Separate read-only analytics app for 2020–2025 yearly CSV history (parked) | Done when: yearly files load with data-quality reporting and year-over-year views, real data stays local, and a public demo runs on synthetic data
- [ ] BPS-226 | Theme: Operations insight | Outcome: Admin can monitor the shop's BPS remotely | Done when: Cloudflare Tunnel + Access (preferred) is set up on a shop-owned domain with an email one-time-code gate, without exposing the PIN login publicly (on hold, DEC-042)
- [ ] BPS-228 | Theme: Documentation | Outcome: Demo video showing how to use the app, linked from the docs (parked until the app is final) | Done when: a walkthrough of sign-in, entry, receipt, My Transactions, records/processing, reconciliation, reports, and Insights is recorded with sample data only and linked in README
- [ ] BPS-212 | Theme: Schema cleanup | Outcome: Remove legacy columns after stabilization (`amt2`, deprecated routing fields) | Done when: controlled SQLite table-rebuild migration is executed in all environments with rollback notes

## Done
- [x] BPS-101 | Shipped on: 2026-03-05 | Notes: Phone + PIN signup/signin with role routing
- [x] BPS-102 | Shipped on: 2026-03-05 | Notes: Dashboard/records view with filters and CRUD
- [x] BPS-103 | Shipped on: 2026-03-05 | Notes: Duplicate detection (`date + account + biller + amount`)
- [x] BPS-104 | Shipped on: 2026-03-06 | Notes: Auto reference generation + receipt print view
- [x] BPS-201 | Shipped on: 2026-03-09 | Notes: OTP-ready signup, PIN lockout/recovery, auth event logging, and manual auth matrix pass (12/12)
- [x] BPS-202 | Shipped on: 2026-03-09 | Notes: Record audit trail with admin audit table (`who/when/channel/status`, plus action/detail)
- [x] BPS-203 | Shipped on: 2026-03-09 | Notes: Per-biller biller_rules validation (active rule required, account digit format enforced in API/UI/CSV)
- [x] BPS-207 | Shipped on: 2026-03-31 | Notes: Added biller-level routing policies, route decision API/engine, entry suggestion + persisted payment channel, processing visibility, and routing scenario matrix (`docs/ROUTING_TEST_MATRIX.md`)
- [x] BPS-208 | Shipped on: 2026-03-09 | Notes: DB-backed biller rules with admin management; computation now reads service/late charges from active rules
- [x] BPS-205 | Shipped on: 2026-03-10 | Notes: EOD reconciliation (collected vs processed, pending, flag); `payment_reference` column for “processed” marker; Processing dashboard to set payment refs and view report (DEC-008). Follow-ups: cash-on-hand variance + date-param compatibility (DEC-015), dedicated daily/monthly/yearly Reports tab (DEC-016).
- [x] BPS-206 | Shipped on: 2026-03-31 | Notes: Added per-biller known-account search/list endpoint and encoder entry-form account picker (datalist) so users can select existing accounts instead of retyping.
- [x] BPS-205 (follow-up) | Shipped on: 2026-04-05 | Notes: Added per-user reconciliation table polish (auto-refresh on selector changes, total-row alignment, pending/status spacing) and reports totals spacing updates.
- [x] BPS-213 | Shipped on: 2026-04-05 | Notes: Added immutable raw-ingest logging table (`bill_record_import_raw`) with `import_batch_id` and row-level status/note/json for CSV import traceability.
- [x] BPS-214 | Shipped on: 2026-04-05 | Notes: Auto-link `customer_accounts.user_id` on signup/signin by phone match with customer-dashboard fallback for linkage consistency.
- [x] BPS-215 | Shipped on: 2026-10-30 | Notes: Python 3.14 compatibility: pinned `sqlalchemy==2.0.44` and `sqlmodel==0.0.44` (0.0.45+ rejects naive datetimes) (DEC-033).
- [x] BPS-216 | Shipped on: 2026-10-31 | Notes: Import feedback: reject files missing required columns, block imports with no active biller rules, list skipped/duplicate rows with reasons, treat spreadsheet placeholders as blank, match headers ignoring case/spaces.
- [x] BPS-217 | Shipped on: 2026-10-30 | Notes: `scripts/run_local.sh` runs everyday use from `~/bps-data` with generated `SESSION_SECRET` and automatic backups (DEC-034).
- [x] BPS-218 | Shipped on: 2026-10-30 | Notes: Insights page (`/admin/insights`): KPI deltas, trend, biller share, late-payment rate, busy-times heatmap, busiest days of the month, top and lapsed customers (DEC-035).
- [x] BPS-219 | Shipped on: 2026-10-31 | Notes: Imports keep the file's amounts and time of day; differences flagged in Reports → Amounts to review; one-off repair scripts for earlier imports (DEC-036).
- [x] BPS-220 | Shipped on: 2026-10-31 | Notes: Phone normalization on import/entry/edit and customer-detail protection against blank or older data (DEC-037).
- [x] BPS-221 | Shipped on: 2026-10-31 | Notes: Offline mode: jQuery, DataTables, and fonts vendored under `app/static/vendor/` (DEC-038).
- [x] BPS-222 | Shipped on: 2026-10-31 | Notes: Larger, bolder 58mm receipt with values-only header fields and right-aligned amounts; entry form asks for "Amount Received" before payment details (DEC-039).
- [x] BPS-224 | Shipped on: 2026-10-31 | Notes: My Transactions on the entry form: encoders see their own payments with date range, totals, and receipt reprint; new `created_by_user_id` backfilled from create audit logs (DEC-041).
- [x] BPS-225 | Shipped on: 2026-10-31 | Notes: Shop-network use: `run_local.sh lan` for other shop computers, plus `scripts/windows-network-setup.ps1` (WSL mirrored networking, Private-only firewall rules); remote access on hold (DEC-042).
- [x] BPS-227 | Shipped on: 2026-10-31 | Notes: New Biller popup on the entry form: an unknown biller opens a dialog to add its rule (service/late charge, account digits) via `POST /api/biller-rules`, then the entry continues (DEC-043).
- [x] BPS-229 | Shipped on: 2026-10-31 | Notes: Per-biller account format (numbers only vs letters and numbers) with exact length, enforced on the entry form and server-side; SSS auto-detected as letters and numbers (DEC-044).
- [x] BPS-230 | Shipped on: 2026-11-04 | Notes: Shop register merged into BPS under `/pos` (shop sales, loading, GCash/Maya cash-in/out, job orders, sales, summary) with one End of day count for bills and shop; `bill_records.settled_at`; data moved with `scripts/import_cashreg.py`; first automated tests in `tests/` (DEC-045, DEC-046).
