# Routing Manual Test Matrix (BPS-207.5)

Purpose: verify payment channel routing decisions for limits, urgency, and availability.

Environment baseline:
- App running locally (`uvicorn main:app --reload`)
- Routing policy columns migrated (`route_online_enabled`, `route_online_max_amount`)
- Test biller rule available (`ROUTING-TEST`)

## Scenario Matrix

| ID | Scenario | Inputs | Expected | Actual | Status |
|---|---|---|---|---|---|
| ROUTE-001 | Within policy | biller=`ROUTING-TEST`, total=1500, due_date=today+10, online_available=true | `ONLINE` + `WITHIN_ROUTING_POLICY` | `ONLINE` + `WITHIN_ROUTING_POLICY` | PASS |
| ROUTE-002 | Urgent due window | biller=`ROUTING-TEST`, total=1500, due_date=today+1, online_available=true | `ONLINE` + `URGENT_DUE_DATE_ONLINE_PRIORITY` | `ONLINE` + `URGENT_DUE_DATE_ONLINE_PRIORITY` | PASS |
| ROUTE-003 | Above online cap | biller=`ROUTING-TEST`, total=7000, due_date=today+10, online_available=true | `BRANCH_MANUAL` + `ABOVE_ONLINE_LIMIT` | `BRANCH_MANUAL` + `ABOVE_ONLINE_LIMIT` | PASS |
| ROUTE-004 | Online unavailable | biller=`ROUTING-TEST`, total=1500, due_date=today+10, online_available=false | `BRANCH_MANUAL` + `ONLINE_UNAVAILABLE` | `BRANCH_MANUAL` + `ONLINE_UNAVAILABLE` | PASS |

## Run Log

| Date | Tester | Build/Branch | Result Summary | Notes |
|---|---|---|---|---|
| 2026-03-31 | KATA | main (local) | 4 PASS / 0 FAIL | Verified via local async scenario script calling `decide_payment_channel` with seeded biller rule. |
