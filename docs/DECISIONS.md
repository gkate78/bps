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

- Date: 2026-04-03
- ID: DEC-024
- Related task: BPS-205 / reconciliation operations
- Decision: Add daily per-user reconciliation summary grouped by `processed_by_user_id` and show it in the Reconciliation page; include user labels (`UNASSIGNED` for null processor) with per-user collected/processed/pending amounts and counts.
- Why: Operators need accountability and workload visibility by processor without leaving the reconciliation workflow.
- Alternatives considered: keep only overall EOD totals; require manual export/reporting for per-user analysis.
- Follow-up: Add date-range and monthly per-user views, and optional historical backfill from audit logs for rows created before processor tracking was introduced.

- Date: 2026-04-03
- ID: DEC-025
- Related task: BPS-203 / BPS-205 data-entry quality
- Decision: Tighten duplicate detection normalization to prioritize `bill_amt` over computed `total` during create/update/import duplicate checks (`txn_date + account + biller + amount`).
- Why: Computed totals can legitimately change when charge rules or due/late conditions change; using `bill_amt` as primary amount key avoids false negatives where duplicate entries bypass checks due to derived charge deltas.
- Alternatives considered: continue using `total` as primary amount key; enforce duplicates on account/date only.
- Follow-up: If needed, expose a duplicate-override workflow for authorized admins with explicit audit reasons.

- Date: 2026-04-03
- ID: DEC-026
- Related task: Admin onboarding UX
- Decision: Redesign admin registration form into structured sections (`Account Setup`, `Business Profile`) with grouped two-column layout, consistent panel styling, and clearer instructional hierarchy.
- Why: First-time setup quality affects operational confidence; better visual structure reduces data-entry mistakes and improves perceived professionalism.
- Alternatives considered: keep single long linear form; split setup into multiple pages.
- Follow-up: Consider adding progressive disclosure/help hints and inline field validation states for faster onboarding.

- Date: 2026-04-05
- ID: DEC-027
- Related task: Billing schema naming cleanup
- Decision: Adopt `late_charge` as the canonical app/UI/API name while keeping legacy DB column `amt2` for backward-compatible writes and safe migration. Database View shows a single `late_charge` header/value and avoids duplicate `amt2` display.
- Why: Existing databases still enforce/contain `amt2`; removing it immediately risks runtime save failures. Canonical naming is still needed to reduce operator confusion.
- Alternatives considered: hard-drop `amt2` immediately; keep using `amt2` across all layers.
- Follow-up: Perform a controlled SQLite table-rebuild migration later to physically remove `amt2` once all environments are validated.

- Date: 2026-04-05
- ID: DEC-028
- Related task: Admin Database View UX
- Decision: Remove manual "Load Table" dependency by auto-loading on table/max-rows selector changes, add in-page row search, and hide deprecated `biller_rules.route_online_max_amount` from Database View output.
- Why: Database inspection should be faster and less cluttered for routine admin use; deprecated legacy fields should not distract operators.
- Alternatives considered: keep manual load button only; keep showing all raw columns including deprecated fields.
- Follow-up: Consider server-side search/filter in Database View if row limits are increased substantially.

- Date: 2026-04-05
- ID: DEC-029
- Related task: CSV import processing defaults
- Decision: During bill-record CSV import, initialize processing fields to operational defaults per row: `payment_method=CASH`, `payment_channel=CASH`, and fallback both `confirmation_reference` and `payment_reference` to `reference` when blank; persist `processed_by_user_id` as the authenticated importing user.
- Why: Initial imports should represent branch-cash intake consistently and preserve a usable trace reference without requiring manual post-import cleanup.
- Alternatives considered: leave imported processing fields as-is from source CSV; set only payment method/channel and keep references empty.
- Follow-up: If mixed-channel historical imports become common, add an optional import mode/override flag instead of hard defaults.

- Date: 2026-04-05
- ID: DEC-030
- Related task: Data-engineering hygiene / import traceability
- Decision: Add immutable raw-ingest logging for bill-record CSV imports via `bill_record_import_raw`, recording `import_batch_id`, source filename, row number, imported user, ingest status (`CREATED`/`DUPLICATE`/`SKIPPED`), note, and original row JSON; keep `bill_records` as curated operational state.
- Why: Preserve raw source-of-truth rows for auditability and reproducibility while still allowing operational defaults/computations in serving tables.
- Alternatives considered: only keep transformed `bill_records`; save raw CSV files externally without row-level statuses.
- Follow-up: Add batch-level inspection/filter UI and optional replay tooling from raw-ingest batches.

- Date: 2026-04-05
- ID: DEC-031
- Related task: Customer account linkage consistency
- Decision: Auto-link `customer_accounts.user_id` to authenticated users on successful signup/signin by phone match (plus dashboard fallback) instead of leaving linkage as mostly manual/implicit.
- Why: Reduce orphaned customer profiles and keep customer dashboard ownership scoping consistent across sessions.
- Alternatives considered: dashboard-only opportunistic linking; explicit manual admin linkage only.
- Follow-up: Add guarded bulk backfill utility for historical rows and optional confidence checks for shared phone numbers.

- Date: 2026-04-05
- ID: DEC-032
- Related task: Reconciliation & reports UX polish
- Decision: Make reconciliation/report filters auto-refresh on selection changes and standardize per-user reconciliation table spacing/alignment (including Pending vs Status separation and total-row consistency).
- Why: Reduce extra clicks, prevent “does not auto show” confusion, and improve readability of per-user totals during EOD checks.
- Alternatives considered: keep manual load only; rely on default table CSS without per-column spacing/alignment tuning.
- Follow-up: Consider sticky table footer for totals on long per-user lists.

- Date: 2026-10-30
- ID: DEC-033
- Related task: BPS-215
- Decision: Pin `sqlalchemy==2.0.44` and `sqlmodel==0.0.44` for Python 3.14 support; do not upgrade SQLModel past 0.0.44 until stored datetimes are timezone-aware.
- Why: SQLAlchemy 2.0.30 and SQLModel 0.0.19 fail to import on Python 3.14; SQLModel 0.0.45+ rejects naive datetimes, which the app writes via `datetime.utcnow()` (about 38 call sites).
- Alternatives considered: latest SQLModel with a datetime refactor; downgrading the venv to Python 3.12.
- Follow-up: Move to timezone-aware datetimes, then lift the pin.

- Date: 2026-10-30
- ID: DEC-034
- Related task: BPS-217
- Decision: Keep live data in `~/bps-data` (run via `scripts/run_local.sh`), separate from the project-folder database used for development, with a SQLite-API backup on every start (last 30 kept).
- Why: The app is used day to day while it is being improved; experiments, test imports, and schema changes must never touch real records.
- Alternatives considered: a single database with manual copies; Docker volumes.
- Follow-up: Data-changing scripts default to dry runs and are tested on copies before running on live data.

- Date: 2026-10-30
- ID: DEC-035
- Related task: BPS-218
- Decision: Build Insights as server-side aggregation (`/api/admin/insights`) plus hand-drawn inline SVG charts in plain JavaScript, with hover details and a data table under each chart. Day-of-month bars show the average per occurrence of that day in the range; the busy-times heatmap hides edge hours holding under 0.5% of transactions.
- Why: No new front-end dependency or build step, works offline, and averages avoid understating the 29th–31st.
- Alternatives considered: a charting library (Chart.js); extending the Reports tables only.
- Follow-up: Revisit performance if the record count grows past tens of thousands (aggregation loads rows into Python).

- Date: 2026-10-31
- ID: DEC-036
- Related task: BPS-219
- Decision: CSV imports keep the file's late charge, charge, total, and change (falling back to biller rules only for blank cells) and store an `amount_review` JSON note on records that differ from the rules or don't add up. Edits recompute amounts only when an amount-related field changes. Supersedes the part of earlier import behavior that recalculated amounts from rules.
- Why: Imported files record what was actually collected, including operator errors the owner wants visible rather than silently corrected; biller rates also change over time.
- Alternatives considered: always recompute from rules; skip inconsistent rows; keep file amounts without flagging.
- Follow-up: `scripts/apply_file_amounts.py` restored file amounts on earlier imports; consider a "mark reviewed" action in the Amounts to review list.

- Date: 2026-10-31
- ID: DEC-037
- Related task: BPS-220
- Decision: Normalize phone numbers to digits with a leading 0 (restoring zeros dropped by spreadsheets, converting `+63`, reading number-formatted cells, blanking placeholders and dates) before the existing 11-digit validation; never overwrite saved customer details with blank values or with rows older than the account's latest payment.
- Why: Spreadsheet exports stored `NA` and 10-digit numbers for hundreds of records; out-of-order imports could revert newer customer details.
- Alternatives considered: reject non-conforming numbers; always take the last imported row.
- Follow-up: `scripts/clean_phone_numbers.py` cleaned existing rows. Extends DEC-003.

- Date: 2026-10-31
- ID: DEC-038
- Related task: BPS-221
- Decision: Serve jQuery, DataTables, and the Space Grotesk / Source Sans 3 fonts from `app/static/vendor/` instead of CDNs, with licenses and sources documented there.
- Why: The app must work without internet; the Records table broke offline when the CDN scripts couldn't load.
- Alternatives considered: rely on browser cache; system fonts only.
- Follow-up: Update vendored files deliberately (same version folder naming) when upgrading.

- Date: 2026-10-31
- ID: DEC-039
- Related task: BPS-222
- Decision: Receipt uses bold Arial (12px details, 14px business name, 16px total), prints reference/date/account/biller/name as values only, keeps amount labels with amounts flush right, and fits the printable width up to 58mm (right page margin 1.5mm, left 3mm). The entry form labels the cash field "Amount Received" and asks for it before payment details; the receipt keeps "CASH".
- Why: Courier at 11px printed small and faint on thermal paper; amounts were pushed off the right edge by a fixed 58mm body inside 52mm of printable width.
- Alternatives considered: larger monospace font; centered header values.
- Follow-up: The `@page size: 58mm auto` declaration is invalid CSS and ignored by browsers; printer driver paper size governs.

- Date: 2026-10-31
- ID: DEC-040
- Related task: Data privacy
- Decision: Never commit databases, real CSV exports, or backups; removed `bills_admin.db` and `sample_masked_records.csv` from all git history (filter-repo + force-push of `main` and `release/v1.1-pwa`). Pre-2026 history is analysed outside BPS (BPS-223) rather than imported.
- Why: The public repository exposed user PIN hashes and lightly masked customer records; older years used different rates and would overwrite current customer details.
- Alternatives considered: making the repository private; leaving history as is.
- Follow-up: Ask GitHub Support to purge cached views and `refs/pull/1/head`; sample data must use invented names and accounts.

- Date: 2026-10-31
- ID: DEC-041
- Related task: BPS-224
- Decision: Track who entered each record in a new `created_by_user_id` column (set on form entry and import, never changed by edits) and use it for the encoder's My Transactions list via `/api/records/mine`; backfill existing rows from the latest successful `create` audit log entry, else `processed_by_user_id`.
- Why: `processed_by_user_id` is overwritten when an admin edits or processes a record, which would make payments disappear from the encoder's list.
- Alternatives considered: query the audit log at read time; reuse `processed_by_user_id`.
- Follow-up: Could feed per-encoder reconciliation totals from the same field.

- Date: 2026-10-31
- ID: DEC-042
- Related task: BPS-225
- Decision: Serve the shop from one computer: `run_local.sh lan` binds 0.0.0.0 (default stays 127.0.0.1); Windows setup uses WSL mirrored networking and allows TCP 8000 only on Private networks from private LAN ranges. Remote access from outside the shop is on hold: keep the local app plus the existing online deployment.
- Why: Encoders and the admin need separate computers in the shop; a 4-digit PIN login over plain HTTP must not face the public internet.
- Alternatives considered: Tailscale (simplest, but the free Personal plan is non-commercial; Standard is $8/user/month); Cloudflare Tunnel + Access (free plan up to 50 users, needs a domain, email one-time code gate); hosting on GCP Compute Engine (loses offline use, exposes the app publicly, adds server upkeep); router port forwarding; WSL NAT with netsh portproxy.
- Follow-up: Owner's preferred option for future remote monitoring is Cloudflare Tunnel + Access (free plan, domain required, email one-time code before the PIN login); Tailscale remains a fallback (`windows-network-setup.ps1 -AllowTailscale`). Consider auto-starting BPS on boot.

- Date: 2026-10-31
- ID: DEC-043
- Related task: BPS-227
- Decision: Let admins and encoders add a rule for a biller that has none from the entry form (`POST /api/biller-rules`: service charge, late charge, optional account digits; Bayad system charge defaults to 5.39 like the Settings form). Existing or inactive rules cannot be changed this way (409) and stay admin-only in Admin Settings; each addition is written to the record audit log.
- Why: Encoders couldn't save payments for new billers and can't open Admin Settings; leaving the form loses the entry in progress.
- Alternatives considered: admin-only quick add; block the entry until an admin adds the rule.
- Follow-up: The record create/update API does not enforce `account_digits` server-side (only the entry form and CSV import do); consider enforcing it in the API.

- Date: 2026-10-31
- ID: DEC-044
- Related task: BPS-229
- Decision: Add `biller_rules.account_format` (`NUMERIC` default, `ALPHANUMERIC` for billers such as SSS and PhilHealth whose references mix letters and numbers). `account_digits` is the exact account length, counting every character. Accounts must match the format (no spaces or symbols) and length on the entry form and in the record API for new records and when the account or biller changes; other edits of older records are not blocked. The migration marks billers with existing letter-containing accounts as `ALPHANUMERIC`.
- Why: The form counted only digits, so SSS accounts like `AA123456789012` were rejected by hand entry while a letter typo in a numeric account could pass; the API didn't check accounts at all (resolves the DEC-043 follow-up).
- Alternatives considered: a per-biller regex pattern; numbers-only everywhere a length is set.
- Follow-up: CSV record imports still don't check account formats; consider flagging mismatches in the review list.

- Date: 2026-11-04
- ID: DEC-045
- Related task: BPS-230
- Decision: Merge the standalone shop register (built separately in `cashreg`) into BPS as the `pos/` package: routes under `/pos`, tables prefixed `pos_` in the same `bills_admin.db`, BPS accounts and session (admin = register admin, encoder = cashier, customers kept out), BPS business profile on shop receipts. Bills and shop sales stay separate transactions (bills keep their 2-copy receipt); a top-bar switch and a "Next: Shop sale" button on the entry form connect them. On only when `POS_ENABLED=1` (set by `run_local.sh`), so the online deployment stays bills-only. Register money is integer centavos; BPS amounts stay decimals and are converted only in End of day. `scripts/import_cashreg.py` moves the standalone register's data in (users matched by phone).
- Why: The counter has one cash drawer and one set of GCash/Maya accounts, so one login and one end-of-day count must cover both bills and shop.
- Alternatives considered: keep two apps and add a combined report across two databases; install the register as a separate Python package.
- Follow-up: The register's own plan and history are in `cashreg/docs/PLAN.md`; SMS when a job order is ready; split payment (part cash, part GCash).

- Date: 2026-11-04
- ID: DEC-046
- Related task: BPS-230
- Decision: Add `bill_records.settled_at`, set when a bill's `payment_reference` is first set (entry with a reference, record edit/processing, Mark Cash + Download) and cleared if it is removed; CSV import doesn't set it and existing records stay empty. The shop register's End of day page (`/pos/eod`) takes bills paid to billers out of the drawer (`payment_channel` CASH) or that GCash/Maya account (GCASH/MAYA) on the day they were settled; other channels (Bayad, banks) are listed for reference only. Bills collected count by `txn_date` and `payment_method` (cash into the drawer, GCASH/MAYA into that account). The page also records starting cash (default in register Settings), cash taken out/added and moves between drawer and wallets, and the counted cash and wallet balances.
- Why: Bills are settled sometimes in cash but mostly online, often not the same day they're collected, so the count needs when and how each bill was paid out; until now only `updated_at` hinted at it. Existing records were recorded as cash while the app was being tested, so they're left out.
- Alternatives considered: use `updated_at` as the settlement time; record settlements by hand as cash movements.
- Follow-up: The older Reconciliation page still compares cash on hand with all bills collected (including GCash); point staff to End of day for the drawer count.

- Date: 2026-11-04
- ID: DEC-047
- Related task: BPS-231
- Decision: The register can **park** a shop sale or a GCash/Maya transaction that isn't paid yet, so the next customer can be served first. Parking saves the screen as-is (cart, customer, cash received, wallet choices) in `pos_parked_txns` under the customer's name (or WALK-IN); Resume puts it back and removes it, parking whatever of the same kind is on the screen in its place; ✕ discards it. Parked transactions are not sales: no number, no receipt, no money in the summary or End of day, which instead warns while any are still parked.
- Why: Customers often wait at the counter (files to send, money still arriving in GCash) while others need quick service; clearing the sale meant re-entering it.
- Alternatives considered: keep parked carts in the browser only (lost if the browser data is cleared, invisible to a second computer); save them as unpaid job orders (would number and count them as sales).
- Follow-up: none.

- Date: 2026-11-04
- ID: DEC-048
- Related task: BPS-232
- Decision: (1) Admin → Database lists the shop register's tables too (added by `register_pos`), with `*_cents` columns shown in pesos without the suffix. (2) Backup to Google Sheets: register Settings holds an Apps Script web app link (must be `https://script.google.com/macros/s/…/exec`) and a generated password; BPS posts each of 13 tabs (bills, customers, billers, staff names and roles, shop sales and lines, job order payments, GCash/Maya cash-in/out, End of day, cash movements, services, accounts) and the script replaces that tab and notes the time in a BACKUP INFO tab. Runs from a "Back up now" button and, when on, in the background after End of day is saved; the result shows in Settings and the register audit log. Never sent: PIN hashes, OTP fields, settings (including the password), auth logs, raw imports.
- Why: The owner wants the records viewable outside the shop computer, without a Google Cloud project or new libraries.
- Alternatives considered: a Google Cloud service account with the Sheets API (more setup, extra dependencies); an Excel download uploaded by hand.
- Follow-up: The sheet is a copy for viewing, not for restoring; the `.db` backups remain the restore path. Whole tabs are rewritten each time; if bills grow past tens of thousands of rows, send only recent changes.

- Date: 2026-11-04
- ID: DEC-049
- Related task: BPS-233
- Decision: Each GCash/Maya account has a load discount (`pos_wallets.load_discount_bp`, basis points; Maya 3% because Maya deducts ₱96.03 for a ₱99 load, GCash 0% until known), set in register Settings. Each load line stores what the app deducted (`pos_sale_lines.wallet_cost_cents`): the account's discount by default, or the amount typed in "Deducted by the app" when the app shows something else (must be more than zero and not more than the load). Wallet balances in the Summary and End of day go down by that amount, and load income is what the customer paid minus it. Loads recorded before this keep an empty `wallet_cost_cents` and count as the full load.
- Why: The expected Maya balance at closing was short by the discount on every load, and the discount is shop income.
- Alternatives considered: a discount per network or per promo (no evidence it varies); typing the deducted amount for every load.
- Follow-up: Confirm GCash's load discount and set it in Settings.

- Date: 2026-11-05
- ID: DEC-050
- Related task: BPS-234
- Decision: Admins can mark a bill (entry form "Transaction Type"), a shop sale or a GCash/Maya transaction (register "Personal") as their own. A `personal` column on `bill_records`, `pos_sales` and `pos_wallet_txns` holds `paid` (the admin pays like a customer) or `shop` (paid from shop funds). Personal means no service charge on bills (the late charge stays, it goes to the biller), loads at the load amount (no fee, no promo rounding) and GCash/Maya with no fee. From shop funds: bills store no cash or mode of payment, sales use `payment_method = shop`, cash-ins collect nothing; End of day leaves them out of money received and lists them in a note, and the Summary leaves them out of shop income. Paying the bill to the biller, sending the load and sending the cash-in still lower the drawer or GCash/Maya. Personal cash-outs can't be from shop funds; personal sales can't be job orders. Only admins (and the business owner for bills) can set it, checked on the server.
- Why: The owner pays their own bills and loads through the counter and either pays in cash or takes it from the shop's money; without a marker the charges were wrong and End of day expected money that never came in.
- Alternatives considered: a new payment method value on bills (the records edit and "Mark Cash" both rewrite `payment_method`, which would lose it); recording shop-funded ones as cash taken out (separate step, easy to forget, and the fee would still be charged).
- Follow-up: The older Reconciliation page still counts shop-funded bills as collected; End of day is the count to use. Personal can't be changed after saving: re-enter the bill, or void and redo the register transaction.

- Date: 2026-11-07
- ID: DEC-051
- Related task: none
- Decision: Cash is collected to the whole peso: under 50 centavos rounds down, 50 centavos and up rounds up (₱1,025.45 → ₱1,025, so ₱1,100 gets ₱75 change; ₱1,025.50 → ₱1,026, ₱74 change). This applies to bills paid in cash (or with no mode of payment), shop sales, job order down payments and balance payments. Totals stay exact (the bill total is what the biller gets and what the receipt shows); change is cash received minus the rounded amount, and the amount received only has to cover the rounded amount. End of day expects the rounded amounts in the drawer. GCash, Maya and bank payments are not rounded. Helpers: `pos.money.cash_due_cents` and `app.controllers.bill_controller.cash_to_collect`, with matching `cashDue` / `cashToCollect` in the register and bill form scripts.
- Why: The counter has always rounded this way; with exact change the cashier couldn't enter ₱1,025 for a ₱1,025.45 bill, change and receipts didn't match what was given, and End of day was off by the centavos.
- Alternatives considered: rounding the stored total (would change what's paid to the biller and the bill's charges); always rounding down (not the shop's rule).
- Follow-up: The rounding difference (shop absorbs up to ₱0.49, gains up to ₱0.50 per cash payment) isn't reported as its own line. Bills and sales saved before this keep their exact change; End of day rounds them too, which matches what was collected if the counter was already rounding. The older Reconciliation page still compares cash on hand to exact totals.

- Date: 2026-11-08
- ID: DEC-052
- Related task: none
- Decision: Bills are entered in the shop register's **Bills payment** tab: several bills (any billers and accounts) for one customer, paid with one payment (cash, GCash, Maya, BDO or BPI, or the admin's personal options). Each bill is still saved to `bill_records` on its own, through the same checks and steps as the entry form (`prepare_new_record`/`finish_new_record`: biller rule, account format, CP number, duplicate check, charges, reference, customer list, audit log with channel `register`, SMS); the register stores nothing about them except while parked (`pos_parked_txns.kind = bills`). All bills of a checkout are checked first and saved in one transaction, so none are saved if one is wrong. Cash is collected per bill to the whole peso (DEC-051); each bill stores its own amount as cash with no change, except the last, which holds the change, so the bills add up to the cash handed over. GCash/Maya bills share one reference no., required and counted as used (no later cash-in, sale or bills checkout can reuse it). Each bill prints its own 2-copy receipt; the receipts print together from `/api/receipts/bills?ids=…`. Every copy is put on the page (each bill's copies together, a page break between each) and printed with one `window.print()`; the window closes on `afterprint`, never straight after `print()`, which can cancel the job before it reaches the printer (the register's sale receipts already worked this way). `?copies=1` gives one copy, for reprints. With the register on (`POS_ENABLED=1`), `/entry/form` redirects to `/pos?tab=bills` and "Add Record" links there; the entry form stays for the online (bills-only) deployment. The register's "← Bills records" link is shown to admins only.
- Why: Customers often pay several bills from different billers at once; one form per bill meant typing their details and taking payment again for each. Keeping `bill_records` as the only store leaves Records, Processing, reports, End of day and the customer dashboard unchanged.
- Alternatives considered: bills as lines in the shop sale cart (mixes bill money into shop sales and their totals); a combined receipt for all bills (customers and billers expect one receipt per bill); a new table for bills checkouts (nothing needs it yet).
- Follow-up: There's no record linking bills paid together beyond their shared time, customer and (for GCash/Maya) reference no. The register's Sales page doesn't list bills; "Bills I entered today" on the Bills tab replaces the entry form's My Transactions for reprints.

- Date: 2026-11-08
- ID: DEC-053
- Related task: none
- Decision: A new bill is a duplicate when the same account already has a bill of the same amount (its bill amount or total) entered in the same calendar month, under any biller. It's refused with the earlier bill's biller, date and reference, in the register's Bills tab (when the bill is added, and again on save, also within the same checkout) and on the bills entry form (`build_record`, 409). Supersedes DEC-025's same-day rule (`txn_date + account + biller + amount`) for new bills only; record edits and CSV imports keep the same-day check.
- Why: The owner wants a bill paid twice in a month caught at the counter, not later in reconciliation; a same-day check missed repeats on different days.
- Alternatives considered: the last 30 days (would block next month's fixed-amount bill paid early in its month); keeping the biller in the match (account and amount are enough, and a different biller with the same account and amount is almost always a mistake).
- Follow-up: There's no override. A customer paying two months of a fixed-amount bill (e.g. the same plan price for September and October) in one month is refused for the second; enter it with an admin's record edit, or add an override if it happens often. Imports still allow it so history files aren't trimmed.

- Date: 2026-11-08
- ID: DEC-054
- Related task: none
- Decision: The register's Summary page includes bills (`bill_records`), counted the way End of day counts them: collected by transaction date, paid to billers by `settled_at` (bill amount and late charge, not the service charge). It shows a Bills payment panel (bill amounts, late charges, service charges, total, by mode of payment), Bills by biller, and Paid to billers by channel. The Income KPI is shop income plus bills service charges; the cash drawer change adds bills paid in cash (each to the whole peso) and subtracts bills paid to billers in cash; GCash/Maya bills and payments to billers move the first active wallet of that provider; bills count toward each cashier (`created_by_user_id`); bills from shop funds join the personal (admin) note. A blank mode of payment counts as cash. Done in `add_bills`, called only by the Summary page; `day_summary` is unchanged so End of day doesn't count bills twice.
- Why: The owner wants one summary for the whole shop, bills included.
- Alternatives considered: adding bills inside `day_summary` (End of day already adds bills itself and would double-count them).
- Follow-up: none.

- Date: 2026-11-08
- ID: DEC-055
- Related task: none
- Decision: The shop sale can carry everything a customer pays (or gets) at the counter, so they pay one total: services and loads (its own lines), plus CASH-IN, CASH-OUT and BILL items, each saved in its own records and linked to the sale. Cash-ins and cash-outs are `pos_wallet_txns` with `sale_id`; bills are `bill_records` (checked and saved exactly as from the Bills tab: rules, monthly duplicate, charges, reference, SMS) linked through a new `pos_sale_bills` table, so the BPS table is unchanged. The sale's own amounts (`total_cents`, `checkout_paid_cents`) are the services and loads only; Summary and End of day count each part in its own records as before, and a sale with no service or load lines isn't counted as a shop sale. Payment: in cash, each part is collected as on its own (shop items and each bill to the whole peso, cash-ins with their fee) and a cash-out pays toward it, so the shop may give cash back (receipt: CASH GIVEN); a sale with a cash-in or cash-out is settled in cash. Without those it can also be paid to the shop's GCash/Maya (one reference no., also stored on its bills, used once) or bank (BDO/BPI, new `payment_method = bank`, reference optional; Summary lists bank payments; not in the drawer or GCash/Maya). Cash-ins need their reference no. (entered in the checkout after sending); cash-outs need theirs when added. Not allowed in a job order; cash-ins/outs not in a personal sale (personal bills follow the sale's Personal). Receipt: the sale receipt lists every item and one total, followed in the same print job by each bill's own 2-copy receipt (`_bill_receipt.html`, shared with BPS). A sale with only bills (no services, loads, cash-ins or cash-outs) prints just each bill's 2-copy receipt, without the sale receipt, the same as the Bills tab (2026-11-10). Voiding the sale voids its cash-ins and cash-outs; a sale with bills can't be voided until the bills are deleted or corrected in Bills records. The GCash / Maya and Bills payment tabs stay for single transactions for now (the Bills tab's form is moved into the sale for BILL items).
- Why: Customers often pay for several kinds of things at once (a cash-in with an ID picture, a bill paid out of a cash-out) and expect one total, one change and one receipt.
- Alternatives considered: cash-ins, cash-outs and bills as sale lines (would mix wallet and bill money into service sales and income); a `sale_id` column on `bill_records` (changes the BPS table; a link table keeps the bills data separate); a combined receipt only (billers' customers expect each bill's own receipt).
- Follow-up: The separate GCash / Maya and Bills payment tabs can be removed once the staff use the sale for everything. The Sales list shows the sale's amount as its services and loads only, with bills, cash-ins and cash-outs described in its details.

- Date: 2026-11-08
- ID: DEC-056
- Related task: none
- Decision: A cash sale can have part paid to the shop's GCash/Maya ("Part paid by GCash/Maya, the rest in cash"): the cashier enters the account, the amount sent (whole pesos, not more than the total) and its reference no. (used once, like any GCash/Maya reference); the rest is collected in cash as usual (each part to the whole peso), with change. It's stored on the sale (`split_wallet_id`, `split_wallet_name`, `split_reference`, `split_cents`, added to `pos_sales` on startup); the sale stays `payment_method = cash`. Summary and End of day move that part from the drawer to the wallet (drawer, shop cash and the cashier's drawer change lower by it; the wallet's "payments" rise by it), so the drawer expects only the cash actually handed over. Bills in a split sale are recorded as cash in the bills records (one method per bill); the money still lands in the right place through the sale. Not with a cash-in or cash-out (settled in cash), a job order's down payment, or a sale from shop funds. The receipt shows PAID VIA GCASH/MAYA with its reference, then CASH and CHANGE.
- Why: Customers sometimes pay part in cash and the rest by GCash/Maya.
- Alternatives considered: a zero-fee cash-out to carry the GCash/Maya part (right money, but it would count as a cash-out); splitting each bill's own payment method (bill_records has one method per bill).
- Follow-up: Splits with BDO/BPI, splits on job order payments, and in the Bills tab aren't offered yet.

- Date: 2026-11-10
- ID: DEC-057
- Related task: none
- Decision: Bill receipts show what was actually paid. A sale of only bills prints each bill's own 2-copy receipt (no sale receipt) with the sale's one payment in place of the bill's own CASH/CHANGE: PAID VIA GCASH/MAYA or bank with its reference, the GCash/Maya part of a split with its reference, then the cash handed over and the change; with several bills, each receipt also says PAID TOGETHER: n BILLS (sale no.) with the combined total. A bill rung up with other items says PAID WITH SALE S-…, since the sale receipt printed with it has the payment. The Bills tab now saves its checkout as such a sale too (`_bills_sale`: zero own total, linked through `pos_sale_bills`, payment on the sale), prints from `/pos/receipt/sale/{id}`, and shows in History. Summary and End of day are unchanged: a sale's own total is zero, so bills still count from `bill_records` only. A GCash/Maya reference used by a bills-only sale is described by its bills.
- Why: The bill's own CASH/CHANGE showed that bill's share (₱1,215 and 0) rather than the ₱1,300 handed over and ₱85 change, and a GCash/Maya part didn't appear at all; the receipts should back up what the customer paid. Saving Bills tab checkouts as sales is a step toward folding the Bills tab into the sale.
- Alternatives considered: spreading the change over the bills (a change belongs to the whole payment); a separate payment slip (one more receipt to print and keep); passing the payment in the receipt URL (can't be trusted for a reprint).
- Follow-up: Bills entered from the BPS entry form, and the Bills tab's per-bill Reprint, still show the bill's own cash and change.

- Date: 2026-11-10
- ID: DEC-058
- Related task: none
- Decision: The register keeps unsaved work in the browser so a brownout, crash or closed tab doesn't lose it. The shop sale, the GCash/Maya transaction and the bills being rung up (the same data as parking) are copied to `localStorage` (`pos-draft:<user id>`) on every input, change and click, every 3 seconds and when the page closes, and removed once there's nothing in progress (saved, parked or cleared). When the register opens again it fills them back in and says so, with a reminder to check History in case the power went off while saving. Only items already added are kept, not a half-typed item in an editor.
- Why: A brownout while encoding a sale lost everything and the cashier had to start over.
- Alternatives considered: saving drafts on the server (survives a different computer, but adds a write per keystroke and the server PC loses power too); auto-parking (would fill the Parked bar with drafts).
- Follow-up: A UPS for the register PC, router and printer is still the real protection against brownouts. Superseded by DEC-059: the copy is now kept on the server (browser storage wasn't written to disk in time in a sudden power cut).

- Date: 2026-11-11
- ID: DEC-059
- Related task: none
- Decision: Unsaved register work is kept on the server, replacing the browser-only copy of DEC-058. The shop sale, the GCash/Maya transaction and the bills being rung up (the same data as parking) are sent a moment after each change (on input, change and click, every 2 seconds, and with `keepalive` when the page closes) to a new `pos_drafts` table: one row per cashier and kind, replaced each time (`PUT /pos/api/drafts`, `DELETE /pos/api/drafts/{kind}`, `GET /pos/api/drafts`). Requests go one at a time in order, so a late copy never overwrites a removal. The server removes a kind's copy when its sale, cash-in/cash-out or bills checkout is saved, or when it's parked; clearing the screen removes it too. When the register opens it fills back what the server has (any computer the cashier signs in on), then says so. A copy also stays in `localStorage`, used only when the server can't be reached. Nothing counts drafts (no money has moved). Shown in Admin → Database as "Shop Unsaved".
- Why: In a test with the browser killed ½–1 second after the last change, the browser hadn't written its storage to disk yet and the sale was lost (the owner saw the same when closing the browser). The server's SQLite commit is on disk at once.
- Alternatives considered: keeping the browser copy only (lost in a sudden power cut); auto-parking (fills the Parked bar and needs a resume step); keeping the copy until the receipt prints (the owner chose removal on save: a saved sale reprints from Sales, and a kept copy risks ringing it up twice).
- Follow-up: The same cashier with the register open in two tabs or on two computers at once shares one copy; the last change wins.

- Date: 2026-11-13
- ID: DEC-060
- Related task: BPS-252
- Decision: In the Load form the network follows the mobile no. From the fourth digit the prefix picks the network family's main brand (GLOBE for Globe/TM/GOMO prefixes, SMART for Smart/TNT/Sun, DITO), matched by name against the active networks; an unknown prefix clears the choice and asks the cashier to choose. Once all 11 digits are in, a number loaded here before takes the network of its last completed load (from the existing mobile suggestions). A note under the field says which it used. A network the cashier clicks is kept until the number is cleared or the load is added; an edited line keeps its saved network. The prefix list is in `register.js`.
- Why: The owner asked for the network to be recognised from the number. The prefix can't tell TM from Globe or TNT from Smart, and ported numbers keep their old prefix, so the number's own history comes first and the cashier can always override.
- Alternatives considered: the prefix only (wrong for TM/TNT and ported numbers); learning each prefix's usual brand from past loads (more code for little gain over the per-number history).
- Follow-up: New prefixes are assigned from time to time; add them to `NETWORK_PREFIXES` when a number isn't recognised.

- Date: 2026-11-13
- ID: DEC-061
- Related task: BPS-253
- Decision: Biller rules get `late_charge_rate` (percent of the bill amount, 0–100) besides the fixed `late_charge`; an overdue bill's late charge is fixed + rate% of the bill, to the centavo (half up). STA MARIA WATER is set to 10%. Because the printed penalty can differ, an overdue bill can carry the late charge typed from the bill (`late_charge_typed` on new records; `late_charge` on register bills and the bill quote), which replaces the rule's; it is ignored when the bill isn't overdue. In the register a Late charge field shows for any overdue bill (whatever the rule, so a penalty can be typed for a biller with no late charge rule), with the rule's amount as its placeholder, and the quote marks a typed one "(from the bill)". On the entry form the Late Charge box becomes typeable when overdue. Editing a record keeps a late charge changed by hand; other amount changes still recompute from the rule. Set in Admin Settings (Late Charge - % of Bill Amount) or the rules CSV (optional LATE_CHARGE_RATE).
- Why: The owner asked for a 10% late payment charge on the water bill. Past STA MARIA WATER penalties were 9.6–9.8% of the amount entered (the district takes 10% of its water charge only, before added fees: ₱411.25 → ₱39.85), so a fixed 10% alone would overcharge by up to a few pesos; the cashier has the printed amount.
- Alternatives considered: 10% of the bill with no override (overcharges slightly); typing the late charge only (no default); estimating the water charge from the bill (the added fees vary).
- Follow-up: Amounts to review (imports) compares against the rule, so a typed penalty imported from a file shows as differing from the rule.

- Date: 2026-11-13
- ID: DEC-062
- Related task: BPS-254
- Decision: Deleting a bill record also deletes its `pos_sale_bills` links (when that table exists), in the same commit. The one stale link in the live data (S-000430 → bill 3070) was removed after a backup (`~/bps-data/backups/bills_admin-before-link-fix-*.db`).
- Why: `bill_records.id` has no AUTOINCREMENT, so SQLite reuses the id of the newest bill once it's deleted. A bill deleted and entered again in a new sale got the same id, and the old sale's leftover link pointed at the new bill, so the old sale refused to void ("This sale includes 1 bill (REF-20261113-E040FD)") and would have reprinted the wrong bill.
- Alternatives considered: rebuilding `bill_records` with AUTOINCREMENT (a table rebuild of live data for the same effect); checking bill creation time against the sale (timestamps are in different zones).
- Follow-up: Audit log entries are by record id too, so a reused id shows both bills' history together.
