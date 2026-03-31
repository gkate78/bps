# Backlog

## NOW
- [x] BPS-207 | Theme: Routing | Outcome: Payment channel routing rules (`online` vs `branch/manual`) | Done when: routing decision engine works for limits/urgency/availability
  - [x] BPS-207.1 Data model/migration: add routing fields to biller rules and record `payment_channel`
  - [x] BPS-207.2 Decision engine: add server-side route resolver by biller policy, due urgency, and amount cap
  - [x] BPS-207.3 Entry flow: show suggested route and submit resolved `payment_channel`
  - [x] BPS-207.4 Processing visibility: show route in processing datatable and include route in record audit detail
  - [x] BPS-207.5 Verification: run manual scenarios (urgent due, online disabled, over-limit, within-policy) and document (`docs/ROUTING_TEST_MATRIX.md`)
- [x] BPS-202 | Theme: Reliability | Outcome: Add transaction audit log (`who`, `when`, `channel`, `status`) | Done when: each record state change writes an audit entry and is viewable in admin
- [x] BPS-203 | Theme: Validation | Outcome: Strengthen counter payment validation by biller rules | Done when: required fields/format are enforced per biller before save

## NEXT
- [x] BPS-204 | Theme: Operations speed | Outcome: Urgent queue with due-date SLA timer | Done when: overdue/near-due records have a dedicated prioritized view
- [x] BPS-206 | Theme: Data quality | Outcome: Customer account lookup list per biller | Done when: encoder can search/select known accounts without retyping

## LATER
- [x] BPS-208 | Theme: Biller standardization | Outcome: Biller directory for charges + required fields | Done when: biller config is editable and used by validation/computation
- [ ] BPS-209 | Theme: Customer comms | Outcome: SMS/Viber confirmation with reference + posting ETA | Done when: message trigger is sent after submission (post-MVP)

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
- [x] BPS-205 | Shipped on: 2026-03-10 | Notes: EOD reconciliation (collected vs processed, pending, flag); `payment_reference` column for “processed” marker; Processing dashboard to set payment refs and view report (DEC-008)
- [x] BPS-206 | Shipped on: 2026-03-31 | Notes: Added per-biller known-account search/list endpoint and encoder entry-form account picker (datalist) so users can select existing accounts instead of retyping.
