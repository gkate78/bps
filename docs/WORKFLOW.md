# Workflow Guide (BPS)

This workflow is now based on your PDF roadmap (goals tracker + brainstorm tabs).

## 1) Product Themes From Source Doc
Track all work under these themes:
1. Auth hardening (`phone + PIN`, OTP, retry lockout, recovery)
2. Operations dashboard parity with Google Sheet
3. Payment reliability and controls (duplicate checks, audit, routing, validation)
4. Reconciliation and operations speed (urgent queue, EOD recon, account lookup)
5. Biller standardization and receipt/reference consistency

## 2) Planning System
Use `docs/BACKLOG.md` as the single source of truth:
- `NOW`: in progress this sprint
- `NEXT`: ready after NOW
- `LATER`: not yet refined
- `DONE`: shipped

Task format:
- `ID`: `BPS-###`
- `Theme`: one of the 5 themes above
- `Outcome`: user-facing result
- `Done when`: measurable checks

## 3) Branch + Delivery Rules
Branch naming:
- `feature/bps-###-short-name`
- `fix/bps-###-short-name`
- `chore/bps-###-short-name`

Delivery slice:
1. Data/model changes
2. Controller/service logic
3. Route/API changes
4. Template/JS/UI updates
5. Manual flow verification
6. Update backlog + decisions log

## 4) Prioritization Rule (From PDF)
Prioritize items that reduce:
1. Double entry / duplicate risk
2. Failed or late payment risk
3. Reconciliation and traceability gaps

De-prioritize low-impact convenience items (for example, customer messaging) until controls are stable.

## 5) Definition of Done
A task is done only if:
1. Correct behavior for role-based users (`admin`, `encoder`, `customer`)
2. Validation and duplicate detection still pass
3. Main UI flow is manually tested
   For auth changes, execute and update `docs/AUTH_TEST_MATRIX.md`.
4. `./scripts/dev.ps1 check` passes
5. `docs/BACKLOG.md` and `docs/DECISIONS.md` are updated

## 6) Current Standards
Unless explicitly overridden by a task requirement:
1. Phone fields must enforce exactly 11 digits.
2. CP number must enforce exactly 11 digits when provided.
3. Text form values are normalized to uppercase before persistence.
4. Amount displays should use comma separators with 2 decimal places on summaries/receipts/tables.

## 7) Weekly Cadence
1. Monday: pick top `NOW` items from backlog
2. Mid-week: close blockers, update decisions
3. Friday: move completed tasks to `DONE`, re-rank `NEXT`
