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
- Related task: N/A (Process)
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
- ID: DEC-003
- Related task: BPS-203
- Decision: Enforce strict numeric length rules for identity/contact inputs (`phone` and optional `cp_number`) with both frontend and backend validation.
- Why: Prevent invalid data at source and avoid inconsistent records caused by client-side bypasses.
- Alternatives considered: frontend-only validation, backend-only validation.
- Follow-up: Keep templates, JS validators, and API models aligned whenever field rules change.

- Date: 2026-03-09
- ID: DEC-004
- Related task: BPS-203
- Decision: Standardize text-form input persistence to uppercase and normalize existing DB rows during init.
- Why: Improve data consistency for search, reporting, and receipt output.
- Alternatives considered: preserve input casing, normalize only at display time.
- Follow-up: Ensure new text fields are included in normalization rules.
