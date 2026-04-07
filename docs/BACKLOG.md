# Backlog

## NOW
- [ ] BPS-210 | Theme: Reconciliation reliability | Outcome: Daily reconciliation snapshot finalization and history | Done when: user can finalize a day, persist immutable totals/variance, and review historical snapshots

## NEXT
- [ ] BPS-209 | Theme: Customer comms | Outcome: SMS/Viber confirmation with reference + posting ETA | Done when: message trigger is sent after submission (post-MVP)
- [ ] BPS-211 | Theme: Import observability | Outcome: Batch-level import review and replay tools | Done when: admin can filter by `import_batch_id`, inspect row outcomes, and optionally re-run selected skipped rows

## LATER
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
