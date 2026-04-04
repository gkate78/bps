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

- Date: 2026-03-10
- ID: DEC-009
- Related task: BPS-205 / operations
- Decision: Treat `BusinessProfile.admin_user_id` as the **registered business owner**: they get the same admin-area access as `role=admin` (records, processing, settings, related APIs) even if their role is not `admin`, and `/dashboard` sends them to `/admin/records`. CSV bill-record import maps optional `payment_reference` / `payment_method` (including export-style lowercase headers) so round-tripped rows stay “processed” when those columns are present.
- Why: Owners must see the full record set and reconciliation state; imports from app exports were losing processing metadata and showed everything as pending.
- Alternatives considered: introduce a distinct `owner` role column; restrict owner to read-only admin views.
- Follow-up: If multi-tenant profiles exist, scope owner checks to the correct profile row.

- Date: 2026-03-31
- ID: DEC-010
- Related task: BPS-206
- Decision: Implement customer lookup as a per-biller known-account index (`/api/customers`) and keep direct account lookup (`/api/customers/lookup`) for fast prefill, with encoder UI using a biller-filtered datalist on the account field.
- Why: Encoders need faster entry with fewer typing errors; biller-scoped suggestions keep account selection relevant while preserving existing account-first workflows.
- Alternatives considered: account-only lookup without list suggestions; separate full-screen customer search modal.
- Follow-up: If account volume grows, add pagination and optional server-ranked search (recently used / frequency).

- Date: 2026-03-31
- ID: DEC-011
- Related task: BPS-207
- Decision: Use biller-level routing policy fields (`route_online_enabled`, optional `route_online_max_amount`) plus an urgency window to compute a suggested `payment_channel` (`ONLINE` or `BRANCH_MANUAL`) server-side; expose this via `/api/routing/decision` and persist the resolved channel on each record.
- Why: Routing must be deterministic and auditable across entry and updates, while still allowing per-biller operational control without code changes.
- Alternatives considered: hardcoded routing in frontend only; global (non-biller) routing limits; manual route tagging without a decision engine.
- Follow-up: Add online availability signal from real channel status provider and complete scenario matrix for routing verification.

- Date: 2026-03-31
- ID: DEC-012
- Related task: BPS-207
- Decision: For overdue and near-due accounts (within urgency window), prioritize suggested `payment_channel=ONLINE` when online is available and enabled for the biller.
- Why: Urgent liabilities benefit from faster posting paths; suggesting online for near/past due cases reduces late-payment risk and aligns with operations priority.
- Alternatives considered: urgent -> branch/manual default; leave urgent behavior neutral and use amount-cap only.
- Follow-up: Observe operational outcomes and adjust urgency window or cap precedence if edge cases appear.

- Date: 2026-03-31
- ID: DEC-013
- Related task: BPS-207
- Decision: Remove `route_online_enabled` and `route_online_max_amount` from biller-rule configuration and simplify route suggestion to urgency-first: urgent => `ONLINE` (if available), non-urgent => `BRANCH_MANUAL`.
- Why: Keep operator setup simple and avoid extra policy knobs while routing behavior is still being tuned with real usage.
- Alternatives considered: keep full per-biller routing toggles/caps; keep caps only.
- Follow-up: Reintroduce configurable routing controls only if operations later require finer channel balancing.

- Date: 2026-03-31
- ID: DEC-014
- Related task: BPS-209
- Decision: Send customer confirmation as a post-submission trigger using a provider-agnostic confirmation service (`COMMS_PROVIDER`), with local stub as default; do not block record creation if messaging fails.
- Why: Operations need immediate customer comms signal with minimal delivery risk; local stub enables safe rollout while preserving a clean integration point for real SMS/Viber providers.
- Alternatives considered: synchronous hard-fail send on submission; channel-specific vendor SDK integration first.
- Follow-up: Add real provider adapters, delivery retries, and customer-facing delivery status if communication volume increases.

- Date: 2026-04-02
- ID: DEC-015
- Related task: BPS-205
- Decision: Extend reconciliation summary to accept optional `cash_on_hand` and report `cash_variance`/`cash_flag`, while accepting both `summary_date` and `date` query params for compatibility with existing UI callers.
- Why: Operators need a same-screen EOD cash check against collected totals; date-param compatibility avoids silent mismatches between frontend and API naming.
- Alternatives considered: separate cash reconciliation endpoint/page; keeping date parameter strict and changing only frontend.
- Follow-up: Add export for reconciliation summary including cash variance columns.

- Date: 2026-04-02
- ID: DEC-016
- Related task: BPS-205 (follow-up)
- Decision: Add a dedicated Reports tab (`/admin/reports`) with period-based reconciliation summary views: daily (by day within selected month), monthly (by month within selected year), and yearly (across all years).
- Why: Operations needs a quick trend view beyond single-day reconciliation so admins can monitor performance over day/month/year without exporting first.
- Alternatives considered: keep only single EOD report; generate summaries only via CSV export.
- Follow-up: Add CSV export for report rows and biller-level breakdowns if reporting needs expand.

- Date: 2026-04-03
- ID: DEC-017
- Related task: BPS-206 / customer portal
- Decision: Scope customer dashboard bills by logged-in phone (`cp_number`) and support two-way dynamic account/biller filters; show bill reference to customers only when payment is already processed.
- Why: Customers can have multiple accounts and billers under one phone; filtering by account/biller reduces confusion while avoiding exposure of pending/processing references.
- Alternatives considered: single-account customer dashboard; always showing reference regardless of payment status.
- Follow-up: Add client-side pagination/sorting for large bill histories and optional “view by biller only” quick chips.

- Date: 2026-04-03
- ID: DEC-018
- Related task: Admin UX polish / BPS-205 operations
- Decision: Simplify admin workflows by removing inline payment-ref editing from the Processing transactions table, adding KPI-first dashboard presentation, and moving biller-rule create/update into a popup form; keep receipt print controls directly beside each business-profile input and include a dedicated footer visibility toggle.
- Why: Operators should scan status quickly and change settings with less clutter; pairing receipt toggles with their exact fields reduces configuration mistakes.
- Alternatives considered: keep inline edit controls on processing table; keep always-visible biller-rule form; keep receipt toggles in a separate checklist section.
- Follow-up: Add lightweight tooltips/help text for each receipt toggle and include before/after UI snapshots in docs if onboarding friction appears.

- Date: 2026-04-03
- ID: DEC-019
- Related task: Admin operations visibility controls
- Decision: Keep heavy admin data views on-demand by default: hide Transaction Audit Log and Biller Rules table until explicitly toggled, and add a dedicated read-only Database View page (`/admin/database`) for table inspection with sticky selector controls.
- Why: Reduces visual clutter and load noise on routine workflows while still giving admins quick access to diagnostics and raw data when needed.
- Alternatives considered: always-visible audit/rules tables; direct inline DB editing inside settings pages.
- Follow-up: Add optional column-level search/export controls in Database View if investigation workflows become frequent.

- Date: 2026-04-03
- ID: DEC-020
- Related task: BPS-205 / payment capture consistency
- Decision: Keep `payment_reference` and `confirmation_reference` as separate persisted fields, and restrict `payment_method` to `CASH`, `GCASH`, `MAYA`, `BDO`, `BPI` in both encoder and admin record flows (validated in UI and API).
- Why: `payment_reference` (processor/biller trace) and `confirmation_reference` (customer-provided confirmation) represent different business meanings; separating them preserves audit clarity and avoids overwriting critical references. Standardized payment-method options remove drift between forms and reports.
- Alternatives considered: reuse one shared reference field; allow open-ended/free-text payment methods.
- Follow-up: Add reporting/export columns that display both references side-by-side in reconciliation and audit views when needed.

- Date: 2026-04-03
- ID: DEC-021
- Related task: BPS-205 / data-entry UX
- Decision: Simplify entry and admin edit payment sections by removing the visible Suggested Route field and prioritizing input order as `Mode of Payment` -> `Confirmation Reference` -> amount (`cash` value field, labeled "Amount").
- Why: Operators finalize payment details faster when the primary decision (mode) appears first and confirmation details follow immediately; hiding route suggestion removes noise from the encode flow while keeping backend routing capabilities available if needed.
- Alternatives considered: keep suggested-route field visible; keep previous amount-first ordering.
- Follow-up: If operators still need routing context, add a compact optional tooltip/help indicator instead of a full input row.

- Date: 2026-04-03
- ID: DEC-022
- Related task: BPS-205 / processing controls
- Decision: Keep `payment_channel` as an explicit persisted field entered/edited by operations (no automatic overwrite in create/update), and separate payment-method scopes by workflow: customer entry allows `CASH`, `GCASH`, `MAYA`, `BDO`, `BPI`, while admin processing/edit allows `CASH`, `GCASH`, `MAYA`, `BAYAD`, `BPI_CC`, `BPI`.
- Why: Operations tracks actual posting routes and processing methods that can differ from customer-facing input options; preserving the encoded channel and allowing richer processing methods improves audit fidelity and reconciliation accuracy.
- Alternatives considered: derive/force channel from payment method; use a single payment-method list for all flows.
- Follow-up: Consider adding channel/method consistency checks or warnings (non-blocking) when operators set unusual combinations.

- Date: 2026-04-03
- ID: DEC-023
- Related task: BPS-205 / processing auditability
- Decision: Persist `processed_by_user_id` on bill-record create/update using the authenticated operator (`current_user.id`), and keep admin edit dropdowns explicit: `payment_method` uses customer-facing modes (`CASH`, `GCASH`, `MAYA`, `BDO`, `BPI`) while `payment_channel` uses processing channels (`CASH`, `GCASH`, `MAYA`, `BAYAD`, `BPI_CC`, `BPI`).
- Why: Reconciliation and audit investigation require knowing exactly who last processed a record and preserving operations-specific channel labels independent from customer payment-mode input.
- Alternatives considered: infer processor from audit log only; force channel from method or use ONLINE/BRANCH-only channel values.
- Follow-up: Add optional backfill utility to populate `processed_by_user_id` for historical rows from audit logs if needed.
