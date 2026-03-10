# Decisions Log

Track meaningful technical and product decisions so future changes stay consistent.

## Template
- Date: YYYY-MM-DD
- ID: DEC-###
- Related task: BPS-###
- Decision: <what was decided>
- Why: <reason and tradeoff>
- Alternatives considered: <other options>
- Follow-up: <migration, cleanup, docs>

---

## Entries

- Date: 2026-03-07
- ID: DEC-001
- Related task: BPS-130
- Decision: Standardize workflow around docs-based backlog + decision log + PowerShell helper script.
- Why: Keep planning and delivery consistent without introducing heavyweight tooling.
- Alternatives considered: external PM tools only, ad-hoc TODO files.
- Follow-up: Revisit if team size grows or CI pipeline is introduced.

- Date: 2026-03-07
- ID: DEC-002
- Related task: BPS-201 to BPS-209
- Decision: Adopt the PDF goals/brainstorm as the canonical product roadmap and map each idea into prioritized backlog items.
- Why: The PDF captures business intent, risks, and sequencing better than generic placeholders.
- Alternatives considered: continue with placeholder backlog, or prioritize by technical ease only.
- Follow-up: Re-rank `NOW/NEXT/LATER` every Friday based on incident risk, reconciliation impact, and operational speed.

- Date: 2026-03-09
- ID: DEC-005
- Related task: BPS-208
- Decision: Replace hardcoded biller charge maps with a DB-backed `biller_rules` directory managed from Admin Settings.
- Why: New/updated billers should not require code changes and redeploys to keep charge computation accurate.
- Alternatives considered: keep hardcoded constants, JSON config file in repo, external spreadsheet only.
- Follow-up: Extend rules to include per-biller required field validation (BPS-203) and add import/export tooling for large rule sets.

- Date: 2026-03-10
- ID: DEC-006
- Related task: BPS-203
- Decision: Enforce per-biller validation by requiring an active `biller_rules` entry, enforcing configured account digit length, and applying these rules consistently in API routes, entry form UI, and CSV import.
- Why: Payments should not be accepted for unconfigured billers or accounts that do not match the expected format, regardless of entry channel.
- Alternatives considered: keep only generic validation (due date / amount) without biller-specific rules.
- Follow-up: Consider richer per-biller schemas (e.g., required `cp_number` or reference formats) and bulk rule management tooling if operational needs grow.

- Date: 2026-03-10
- ID: DEC-007
- Related task: BPS-204
- Decision: Add an "urgent" due-status filter and view that surfaces records whose due dates are overdue or within the next 3 days, using the existing datatable and filters.
- Why: Admins need a single prioritized view for payments that are at risk (overdue/near-due) rather than manually toggling multiple filters.
- Alternatives considered: separate urgent-only page with custom queries; reusing only the "overdue" filter without near-due items.
- Follow-up: Consider making the urgency window configurable and adding SLA countdown badges in the UI if operational needs increase.

- Date: 2026-03-10
- ID: DEC-008
- Related task: BPS-205
- Decision: (1) Keep `reference` as the auto-generated value used on customer receipts only. (2) Add `payment_reference` as a separate column set by staff when a transaction has been processed (e.g. biller/channel ref); when non-empty, the record counts as “processed” for reconciliation. (3) EOD reconciliation: collected = sum of total for date; processed = sum of total where payment_reference is set; pending = collected − processed; flag = match / short / pending. (4) Provide a Processing dashboard to update payment references and view the EOD report; optional “cash on hand” can be added later.
- Why: Receipt reference must stay stable for customers; real processing refs come from billers/channels and are needed for reconciliation and audit.
- Alternatives considered: reusing a single reference for both receipt and processing; reconciliation without a processed marker.
- Follow-up: Optional cash-on-hand vs collected comparison; export of reconciliation report.
