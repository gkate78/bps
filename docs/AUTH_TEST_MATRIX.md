# Auth Manual Test Matrix (BPS-201.10)

Purpose: verify critical auth hardening flows before release.

Environment baseline:
- App running locally (`uvicorn main:app --reload`)
- OTP provider set to local/dev stub (`OTP_PROVIDER=local`)
- Fresh database or known test users

Execution notes:
- Run scenarios in order where possible.
- Capture timestamp, tester name, and result (`PASS`/`FAIL`) for each row.
- If a case fails, record observed behavior and open a backlog follow-up.

## Scenario Matrix

| ID | Flow | Preconditions | Steps | Expected Result | Actual Result | Status |
|---|---|---|---|---|---|---|
| AUTH-001 | Signup + OTP happy path | Unregistered 11-digit phone | Submit `/auth/signup` with valid data, enter valid OTP in `/auth/signup/verify` | Account is created, session starts, user lands on role dashboard | Behavior matched expected outcome | PASS |
| AUTH-002 | Signup invalid OTP | Pending signup OTP session exists | Enter wrong OTP code | Error shown with remaining attempts, account not created | Remaining-attempt error shown; no account created | PASS |
| AUTH-003 | Signup OTP max attempts | Pending signup OTP session exists | Enter wrong OTP repeatedly until limit | Session is cleared, signup blocked, user must restart signup | Session cleared after max attempts; restart required | PASS |
| AUTH-004 | Signup OTP expired | Pending signup exists but OTP expired | Submit OTP after expiry | Signup verification is rejected, user asked to sign up again | Expired OTP rejected; signup restart required | PASS |
| AUTH-005 | Signin happy path | Existing user with valid PIN | Submit `/auth/signin` with correct phone/PIN | Login succeeds and routes by role | Signin succeeded and role routing worked | PASS |
| AUTH-006 | Signin invalid PIN retries | Existing user | Submit wrong PIN below lockout threshold | Signin fails with invalid credentials, failed attempt counter increments | Invalid signin handled; retry counter behavior observed | PASS |
| AUTH-007 | Signin lockout | Existing user | Submit wrong PIN until threshold reached | Account is temporarily locked, signin blocked until lockout window ends | Lockout triggered at threshold and blocked signin | PASS |
| AUTH-008 | PIN reset request happy path | Existing user phone | Submit `/auth/pin/reset/request` | Reset OTP is generated, redirect to `/auth/pin/reset/verify` | OTP generated and redirected to verify page | PASS |
| AUTH-009 | PIN reset invalid OTP | Pending pin reset session exists | Submit wrong OTP with valid new PIN | Error shown with remaining attempts, PIN unchanged | Remaining-attempt error shown; PIN unchanged | PASS |
| AUTH-010 | PIN reset OTP expired | Pending pin reset session exists but OTP expired | Submit OTP + new PIN | Reset is blocked, session reset required | Expired OTP blocked reset; new request required | PASS |
| AUTH-011 | PIN reset happy path | Pending pin reset OTP valid | Submit valid OTP + valid new PIN + confirm | PIN updated, OTP state cleared, signin success with new PIN | PIN updated successfully; signin works with new PIN | PASS |
| AUTH-012 | PIN policy enforcement | Any signup/reset form | Use weak/non-compliant PIN | Request rejected with policy error, no account/PIN update | Weak/non-compliant PIN was rejected as expected | PASS |

## Run Log

| Date | Tester | Build/Branch | Result Summary | Notes |
|---|---|---|---|---|
| 2026-03-09 | KATA | feature/bps-201-10-auth-test-matrix | 12 PASS / 0 FAIL | No blocking issues observed during manual auth regression run |
