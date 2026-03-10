# Backlog

## NOW
- [ ] BPS-201 | Theme: Auth hardening | Outcome: Add OTP-ready signup flow + PIN security controls | Done when: phone verification hook, retry limit, and lockout policy are implemented and tested
  - [x] BPS-201.1 Data model: add `otp_code_hash`, `otp_expires_at`, `otp_attempts`, `pin_failed_attempts`, `locked_until` fields (or separate auth table)
  - [x] BPS-201.2 Migration: update `init_db` lightweight migration for new auth columns with safe defaults
  - [x] BPS-201.3 OTP service contract: implement provider-agnostic interface (`send_otp`, `verify_otp`) with local/dev stub
  - [x] BPS-201.4 Signup flow: require OTP verification state before account activation
  - [x] BPS-201.5 PIN policy: enforce 4-digit numeric PIN, hash+salt storage only, reject weak/common demo PINs if configured
  - [x] BPS-201.6 Signin controls: add failed-attempt counter and temporary lockout after threshold
  - [x] BPS-201.7 Recovery flow: add PIN reset request + OTP confirm + new PIN set
  - [x] BPS-201.8 Auth logging: log signin success/failure, lockout events, OTP verify events
  - [x] BPS-201.9 UI updates: signup/signin templates show OTP and lockout states with clear errors
  - [ ] BPS-201.10 Verification: manual test matrix for happy path, invalid OTP, expired OTP, lockout, reset flow
- [ ] BPS-202 | Theme: Reliability | Outcome: Add transaction audit log (`who`, `when`, `channel`, `status`) | Done when: each record state change writes an audit entry and is viewable in admin
- [ ] BPS-203 | Theme: Validation | Outcome: Strengthen counter payment validation by biller rules | Done when: required fields/format are enforced per biller before save

## NEXT
- [ ] BPS-204 | Theme: Operations speed | Outcome: Urgent queue with due-date SLA timer | Done when: overdue/near-due records have a dedicated prioritized view
- [ ] BPS-205 | Theme: Reconciliation | Outcome: End-of-day reconciliation summary | Done when: cash on hand vs collected vs submitted is computed with discrepancy flags
- [ ] BPS-206 | Theme: Data quality | Outcome: Customer account lookup list per biller | Done when: encoder can search/select known accounts without retyping

## LATER
- [ ] BPS-207 | Theme: Routing | Outcome: Payment channel routing rules (`online` vs `branch/manual`) | Done when: routing decision engine works for limits/urgency/availability
- [x] BPS-208 | Theme: Biller standardization | Outcome: Biller directory for charges + required fields | Done when: biller config is editable and used by validation/computation
- [ ] BPS-209 | Theme: Customer comms | Outcome: SMS/Viber confirmation with reference + posting ETA | Done when: message trigger is sent after submission (post-MVP)

## Done
- [x] BPS-101 | Shipped on: 2026-03-05 | Notes: Phone + PIN signup/signin with role routing
- [x] BPS-102 | Shipped on: 2026-03-05 | Notes: Dashboard/records view with filters and CRUD
- [x] BPS-103 | Shipped on: 2026-03-05 | Notes: Duplicate detection (`date + account + biller + amount`)
- [x] BPS-104 | Shipped on: 2026-03-06 | Notes: Auto reference generation + receipt print view
- [x] BPS-202 | Shipped on: 2026-03-09 | Notes: Record audit trail with admin audit table (`who/when/channel/status`, plus action/detail)
- [x] BPS-208 | Shipped on: 2026-03-09 | Notes: DB-backed biller rules with admin management; computation now reads service/late charges from active rules
