# Decisions Log

The technical and product decisions behind BPS, in short. This public log keeps the general idea of each
decision; the detailed records (the shop's own prices, fees, costs, owner choices and fixes to live data) are
kept privately.

When adding a decision, use the template, and keep shop-specific numbers out of this file: write "the shop's
fee" or "a set price", not the amount.

## Template
- Date: YYYY-MM-DD
- ID: DEC-###
- Related task: BPS-###
- Decision: <what was decided, in general terms>
- Why: <reason and tradeoff>

## Workflow and foundations
- **DEC-001**: Docs-based workflow: backlog, decision log and a helper script.
- **DEC-002**: The product roadmap is mapped into a prioritized backlog.
- **DEC-003**: Phone numbers have strict length rules, checked in the browser and on the server.
- **DEC-004**: Text fields are saved in uppercase; existing rows are normalized at start-up.
- **DEC-033**: SQLAlchemy and SQLModel are pinned to versions that work on Python 3.14.
- **DEC-034**: Live data lives in a folder outside the project, backed up on every start; the project database is for development only.
- **DEC-038**: Front-end libraries and fonts are served locally, so the app works with no internet.
- **DEC-040**: Databases, real CSV exports and backups are never committed (removed from history once).
- **DEC-042**: One shop computer serves the app to the others over the shop network (WSL mirrored networking, firewall limited to private networks).

## Bills: rules, entry and records
- **DEC-005**: Biller charges come from a `biller_rules` table edited in Admin Settings, not from code.
- **DEC-006**: A bill needs an active rule for its biller, and the account length the rule sets.
- **DEC-007**: An "urgent" view lists bills that are overdue or due within a few days.
- **DEC-008**: The receipt reference (generated) and the payment reference (typed by staff) are separate fields.
- **DEC-010**: Customer lookup by biller and account, with a fast direct lookup.
- **DEC-011–013**: Payment-channel routing was tried and then simplified to an urgency-first suggestion.
- **DEC-014**: Customer confirmations go through a provider-agnostic messaging service (local stub by default).
- **DEC-017**: Customers see only the bills for their own phone number.
- **DEC-020–023**: Payment method (how the customer paid) and payment channel (how the shop paid the biller) are separate, explicit fields; the operator who processed a bill is recorded.
- **DEC-025**: Duplicate checks compare the bill amount, not the computed total.
- **DEC-027**: `late_charge` is the canonical name; the old `amt2` column is kept for compatibility.
- **DEC-041**: Each record keeps who entered it (`created_by_user_id`), unchanged by later edits.
- **DEC-043**: Staff can add a rule for a new biller from the entry form; editing existing rules stays in Admin Settings.
- **DEC-044**: Biller rules set the account format: numbers only, or letters and numbers.
- **DEC-046**: A bill counts as paid to the biller (`settled_at`) when its payment reference is first entered.
- **DEC-053**: A bill with the same account and amount as one already entered that month is refused as a duplicate.
- **DEC-061**: A late charge can be a fixed amount, a percent of the bill, or both; the penalty printed on the bill can be typed in.
- **DEC-062**: Deleting a bill also deletes its links to register sales (SQLite reuses ids).
- **DEC-063**: Older bills saved before whole-peso cash can still be processed at their exact total.
- **DEC-064–065**: A bill noted as paid to the biller twice warns the cashier when that account comes up again, and the amount can be paid back in a sale (received, not income).
- **DEC-067–069, 073**: Bills records filters (due date, status), totals, sort, and printable lists, including a payment sheet for paying one biller in cash.
- **DEC-070**: Pending bills for one water district are matched against its public billing inquiry to fill in payment references.
- **DEC-071**: A bulk "mark as cash and download" action was removed in favour of the payment sheet and reference lookups.
- **DEC-072**: The Google Sheet backup has a payment-references tab that staff can fill in from home; BPS reads it back and marks the rows done.
- **DEC-074**: Billers have a category (electricity, water, internet, …) for reports.

## Imports and data quality
- **DEC-029–030**: CSV imports set processing defaults and keep every raw row, by batch, for traceability.
- **DEC-036**: Imports keep the amounts actually collected and flag rows that don't match the rules for review, instead of correcting them.
- **DEC-037**: Phone numbers are normalized (dropped leading zeros, `+63`, number-formatted cells).
- **DEC-076**: Data clean-ups are made after a backup, with the owner's approval, and every change is audit-logged; the customer list takes a corrected phone number from an older bill.

## Admin, reports and insights
- **DEC-009**: The registered business owner gets admin access.
- **DEC-015–016, 024, 032**: Reconciliation with optional cash count, per-user totals, and daily/monthly/yearly reports.
- **DEC-018–019, 026, 028**: Admin screens favour KPIs, load heavy tables on demand, and auto-refresh on filter changes.
- **DEC-031**: Customer accounts link to a user automatically by phone on sign-in.
- **DEC-035**: Insights are aggregated on the server and drawn as inline SVG charts in plain JavaScript.
- **DEC-039**: 58 mm receipt layout (font sizes, values only, amounts flush right).

## Shop register (`/pos`)
- **DEC-045**: The standalone shop register was merged into BPS as the `pos/` package, sharing sign-in, database and end of day.
- **DEC-047**: An unpaid sale can be parked to serve the next customer and resumed later.
- **DEC-048**: The register's tables show in Admin → Database; records can be backed up to a Google Sheet.
- **DEC-049**: Each GCash/Maya account can have a load discount (set in Settings), used in its balance and load income.
- **DEC-050**: Admins can mark their own transactions as personal (no fees; paid by them or from shop funds), shown separately.
- **DEC-051**: Cash is collected to the whole peso; the biller still receives the exact amount.
- **DEC-052, 054–057**: One sale can hold services, loads, cash-ins, cash-outs and bills, paid with one payment (cash, e-wallet, bank, or split), while each part is still saved in its own records with the right receipts.
- **DEC-058–059**: Unsaved register work is saved on the server as it's typed, so a brownout or closed browser loses nothing.
- **DEC-060**: The Load form picks the network from the mobile number.
- **DEC-066**: The Load form starts on a default sending account.
- Fees for loads and GCash/Maya are set in Settings as a fee per full block plus brackets for the remainder; a cash-out can have its fee deducted, paid in cash, or included in the amount sent (the one payout whose amount plus fee equals what was sent is found by binary search). The numbers in `pos/fees.py` are examples.
- Cashier controls: blind closing counts, voids only by a signed-in admin with their own PIN, a GCash/Maya reference accepted once across all transaction types, and drawer handovers split by time.

## Stock and costs
- **DEC-075**: Each service has a pick list of usual items and prices; the register suggests them first.
- **DEC-077**: Materials stock: pick list items use materials per unit (fractions allowed); sales take stock off, voids put it back, restocks average the cost, counts correct it; low-stock warnings; cost and profit per service.
- **DEC-078**: Rejects (misprints, paper jams, customer reprints with their sale) are recorded by cashiers, taken off stock at once and reported at cost by reason.
- **DEC-081**: Tarpaulin jobs: each sale with a tarpaulin goes to the designer set in Settings with the customer's specs typed at the register, who sees only their own jobs and marks the steps (layout, customer approval, sent to print shop, ready, claimed); claimed needs the balance paid; admins see all and reassign.
- **DEC-079**: Tarpaulins printed by another shop: the printing cost a sq ft and small-tarp price and cost are set in Settings; the cost is tracked as a never-counted material so profit shows correctly.

## Repository
- **DEC-080**: Business details (prices, fees, costs, discounts, live-data fixes) are kept in a private repo; the public docs are general, and the code and tests use example numbers, with the shop's own set in Settings.
