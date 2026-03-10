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
- ID: DEC-004
- Related task: BPS-202
- Decision: Add a dedicated `record_audit_logs` table and log record state changes (`create`, `update`, `delete`, `import_csv`) from route handlers with actor, channel, status, and detail metadata.
- Why: We need traceability of operational changes directly in admin tooling without relying on external logs.
- Alternatives considered: reusing auth event logs table, filesystem logs only, no UI exposure.
- Follow-up: Expand audit coverage to future record status transitions and add filter/search controls on the audit table if volume grows.

- Date: 2026-03-09
- ID: DEC-005
- Related task: BPS-208
- Decision: Replace hardcoded biller charge maps with a DB-backed `biller_rules` directory managed from Admin Settings.
- Why: New/updated billers should not require code changes and redeploys to keep charge computation accurate.
- Alternatives considered: keep hardcoded constants, JSON config file in repo, external spreadsheet only.
- Follow-up: Extend rules to include per-biller required field validation (BPS-203) and add import/export tooling for large rule sets.
