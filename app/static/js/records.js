function currency(value) {
    const num = Number(value || 0);
    return num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Return current local date/time as YYYY-MM-DDTHH:mm:ss (no timezone) so server stores and returns same, and display matches. */
function toLocalISOString(d) {
    const date = d || new Date();
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const h = String(date.getHours()).padStart(2, "0");
    const min = String(date.getMinutes()).padStart(2, "0");
    const s = String(date.getSeconds()).padStart(2, "0");
    return `${y}-${m}-${day}T${h}:${min}:${s}`;
}

function formatDateTime(value) {
    if (!value) {
        return "-";
    }
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) {
        return value;
    }
    return dt.toLocaleString();
}

function valueOrEmpty(value) {
    return value == null ? "" : value;
}

function parseNum(value) {
    const num = Number(value);
    return Number.isFinite(num) ? num : 0;
}

function round2(value) {
    return Math.round((parseNum(value) + Number.EPSILON) * 100) / 100;
}

/** Cash is collected to the whole peso: under 50 centavos rounds down, 50 and up rounds up
 * (₱1,025.45 → ₱1,025, ₱1,025.50 → ₱1,026). GCash, Maya and bank payments stay exact. */
function cashToCollect(total, paymentMethod) {
    const method = String(paymentMethod || "").trim().toUpperCase();
    if (method && method !== "CASH") return round2(total);
    return Math.floor((Math.round(round2(total) * 100) + 50) / 100);
}

// Cash is collected to the whole peso (₱328.90 → ₱329). Bills saved before that rule (2026-11-08) hold the
// exact total as cash; editing one (e.g. adding the payment reference) keeps the exact total, with no change.
function cashExpected(total, cash, paymentMethod) {
    const wholePeso = cashToCollect(total, paymentMethod);
    const exact = round2(total);
    return dom.recordId.value && cash < wholePeso && cash >= exact ? exact : wholePeso;
}

function formatStatusPill(value) {
    const status = String(value || "").toLowerCase();
    const cls = status === "success" ? "status-success" : "status-failed";
    return `<span class="status-pill ${cls}">${status || "-"}</span>`;
}

function paymentStatePill(row) {
    const isProcessed = Boolean(row && row.payment_reference);
    const label = isProcessed ? "Processed" : "Pending";
    const cls = isProcessed ? "status-success" : "status-warning";
    return `<span class="status-pill ${cls}">${label}</span>`;
}

function parseDate(value) {
    if (!value) {
        return null;
    }
    const normalized = `${String(value).slice(0, 10)}T00:00:00`;
    const dt = new Date(normalized);
    return Number.isNaN(dt.getTime()) ? null : dt;
}

let kpiAbortController = null;

function showMessage(message, title = "Notice") {
    const dialog = document.getElementById("appMessageDialog");
    const titleEl = document.getElementById("appMessageTitle");
    const textEl = document.getElementById("appMessageText");
    const okBtn = document.getElementById("appMessageOkBtn");
    const closeBtn = document.getElementById("appMessageCloseBtn");
    if (!dialog || !titleEl || !textEl || !okBtn || !closeBtn) {
        alert(message);
        return Promise.resolve();
    }

    titleEl.textContent = title;
    textEl.textContent = message;
    return new Promise((resolve) => {
        let settled = false;
        const done = () => {
            if (settled) return;
            settled = true;
            okBtn.removeEventListener("click", onOk);
            closeBtn.removeEventListener("click", onClose);
            dialog.removeEventListener("close", onClose);
            resolve();
        };
        const onOk = () => {
            dialog.close();
            done();
        };
        const onClose = () => done();

        okBtn.addEventListener("click", onOk);
        closeBtn.addEventListener("click", onClose);
        dialog.addEventListener("close", onClose);
        dialog.showModal();
    });
}

function showConfirm(message, title = "Please Confirm") {
    const dialog = document.getElementById("appConfirmDialog");
    const titleEl = document.getElementById("appConfirmTitle");
    const textEl = document.getElementById("appConfirmText");
    const okBtn = document.getElementById("appConfirmOkBtn");
    const cancelBtn = document.getElementById("appConfirmCancelBtn");
    const closeBtn = document.getElementById("appConfirmCloseBtn");
    if (!dialog || !titleEl || !textEl || !okBtn || !cancelBtn || !closeBtn) {
        return Promise.resolve(window.confirm(message));
    }

    titleEl.textContent = title;
    textEl.textContent = message;
    return new Promise((resolve) => {
        let settled = false;
        const done = (value) => {
            if (settled) return;
            settled = true;
            okBtn.removeEventListener("click", onOk);
            cancelBtn.removeEventListener("click", onCancel);
            closeBtn.removeEventListener("click", onCancel);
            dialog.removeEventListener("close", onCancel);
            resolve(value);
        };
        const onOk = () => {
            dialog.removeEventListener("close", onCancel);
            dialog.close();
            done(true);
        };
        const onCancel = () => {
            dialog.removeEventListener("close", onCancel);
            dialog.close();
            done(false);
        };

        okBtn.addEventListener("click", onOk);
        cancelBtn.addEventListener("click", onCancel);
        closeBtn.addEventListener("click", onCancel);
        dialog.addEventListener("close", onCancel);
        dialog.showModal();
    });
}

const BILLER_CHARGES = window.BILLER_CHARGES || {};
const BILLER_ACCOUNT_DIGITS = window.BILLER_ACCOUNT_DIGITS || {};

const dom = {
    dialog: document.getElementById("recordDialog"),
    form: document.getElementById("recordForm"),
    title: document.getElementById("dialogTitle"),
    recordId: document.getElementById("recordId"),
    currentDateTime: document.getElementById("currentDateTime"),
    txnDate: document.getElementById("txnDate"),
    account: document.getElementById("account"),
    biller: document.getElementById("biller"),
    customerName: document.getElementById("customerName"),
    cpNumber: document.getElementById("cpNumber"),
    billAmt: document.getElementById("billAmt"),
    amt2: document.getElementById("amt2"),
    charge: document.getElementById("charge"),
    total: document.getElementById("total"),
    cash: document.getElementById("cash"),
    changeAmt: document.getElementById("changeAmt"),
    dueDate: document.getElementById("dueDate"),
    notes: document.getElementById("notes"),
    reference: document.getElementById("reference"),
    paymentChannel: document.getElementById("paymentChannel"),
    paymentReference: document.getElementById("paymentReference"),
    confirmationReference: document.getElementById("confirmationReference"),
    paymentMethod: document.getElementById("paymentMethod"),
};

const filters = {
    biller: document.getElementById("billerFilter"),
    fromDate: document.getElementById("fromDateFilter"),
    toDate: document.getElementById("toDateFilter"),
    dueStatus: document.getElementById("dueStatusFilter"),
    dueFrom: document.getElementById("dueFromFilter"),
    dueTo: document.getElementById("dueToFilter"),
    status: document.getElementById("statusFilter"),
};
// Filter inputs sent as query parameters (the same for the table, the KPIs, Print, Payment Sheet and SMWD references).
const EXTRA_FILTER_PARAMS = { dueFrom: "due_from", dueTo: "due_to", status: "status" };

const kpis = {
    visible: document.getElementById("kpiVisibleRecords"),
    processed: document.getElementById("kpiProcessedRecords"),
    pending: document.getElementById("kpiPendingRecords"),
    urgent: document.getElementById("kpiUrgentRecords"),
    scope: document.getElementById("kpiScopeLabel"),
};

function normalizedBillerKey(value) {
    return String(value || "").trim().toUpperCase();
}

function computeCharge(biller, billAmount) {
    const amount = round2(billAmount);
    if (amount <= 0) {
        return 0;
    }

    const predefined = BILLER_CHARGES[normalizedBillerKey(biller)];
    if (predefined == null) {
        return 0;
    }

    if (amount <= 3300) {
        return round2(Math.max(Number(predefined), 15));
    }

    return round2(Math.ceil((amount - 3300) / 1000) * 10 + 15);
}

function recomputeFinancials() {
    const billAmt = round2(dom.billAmt.value);
    const lateCharge = round2(dom.amt2.value);
    const charge = computeCharge(dom.biller.value, billAmt);
    const total = round2(billAmt + lateCharge + charge);
    const cash = round2(dom.cash.value);
    const change = round2(cash - cashExpected(total, cash, dom.paymentMethod?.value));

    dom.charge.value = charge.toFixed(2);
    dom.total.value = total.toFixed(2);
    dom.changeAmt.value = change.toFixed(2);
}

function updateCurrentDateTime() {
    const now = new Date();
    dom.currentDateTime.textContent = now.toLocaleString();
}

function setCurrentTxnDate() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const d = String(now.getDate()).padStart(2, "0");
    dom.txnDate.value = `${y}-${m}-${d}`;
}

function syncConfirmationReferenceState() {
    if (!dom.confirmationReference || !dom.paymentMethod) {
        return;
    }
    const isCash = String(dom.paymentMethod.value || "").trim().toUpperCase() === "CASH";
    dom.confirmationReference.disabled = isCash;
    if (isCash) {
        dom.confirmationReference.value = "";
    }
}

const table = new DataTable("#recordsTable", {
    processing: true,
    serverSide: true,
    pageLength: 10,
    ajax: {
        url: "/api/records/datatable",
        data: (d) => {
            if (filters.biller.value) {
                d.biller = filters.biller.value;
            } else {
                delete d.biller;
            }

            if (filters.fromDate.value) {
                d.from_date = filters.fromDate.value;
            } else {
                delete d.from_date;
            }

            if (filters.toDate.value) {
                d.to_date = filters.toDate.value;
            } else {
                delete d.to_date;
            }

            if (filters.dueStatus.value) {
                d.due_status = filters.dueStatus.value;
            } else {
                delete d.due_status;
            }
            Object.entries(EXTRA_FILTER_PARAMS).forEach(([key, param]) => {
                if (filters[key]?.value) d[param] = filters[key].value;
                else delete d[param];
            });
        },
    },
    columns: [
        { data: "id", className: "align-center" },
        { data: "txn_datetime", render: formatDateTime },
        { data: "account" },
        { data: "biller" },
        { data: "customer_name" },
        { data: "bill_amt", render: currency, className: "align-right" },
        { data: "due_date", render: (d) => d || "-", className: "align-center" },
        {
            data: null,
            className: "align-center",
            render: (row) => paymentStatePill(row),
        },
        { data: "reference", render: (d) => d || "" },
        {
            data: null,
            orderable: false,
            searchable: false,
            className: "align-center",
            render: (row) => `
                <div class="action-row">
                    <button type="button" class="btn btn-secondary" onclick="openEdit(${row.id})">Edit</button>
                    <button type="button" class="btn btn-danger" onclick="removeRecord(${row.id})">Delete</button>
                </div>
            `,
        },
    ],
    order: [[1, "desc"]],
});

// Totals of everything matching the filters and search (all pages), sent with each page of the table.
const recordsTotals = document.getElementById("recordsTotals");
table.on("xhr", (event, settings, json) => {
    const t = json?.totals;
    if (!recordsTotals || !t) return;
    recordsTotals.innerHTML =
        `<strong>Total of ${t.count.toLocaleString()} filtered bill${t.count === 1 ? "" : "s"}:</strong> ` +
        `bill amount ₱${currency(t.bill_amt)} · late charges ₱${currency(t.late_charge)} · ` +
        `service charges ₱${currency(t.charge)} · <strong>total ₱${currency(t.total)}</strong>`;
});

// SMWD references: look up the pending STA MARIA WATER bills on SMWD's Billing Inquiry, preview, then apply.
const smwd = {
    dialog: document.getElementById("smwdDialog"),
    body: document.getElementById("smwdBody"),
    status: document.getElementById("smwdStatus"),
    apply: document.getElementById("smwdApplyBtn"),
    channel: document.getElementById("smwdChannel"),
    items: [],
};
const escapeText = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
function renderSmwd() {
    smwd.body.innerHTML = smwd.items
        .map((item, i) => `<tr>
            <td>${item.smwd_reference ? `<input type="checkbox" data-smwd="${i}" ${item.matched ? "checked" : ""} aria-label="Apply ${escapeText(item.smwd_reference)}">` : ""}</td>
            <td>${escapeText(item.id_number)}</td>
            <td>${escapeText(item.customer_name)}<div class="status-text">${escapeText(item.reference)} · ${escapeText(item.txn_date)}</div></td>
            <td class="align-right">${currency(item.bill_amt)}</td>
            <td>${escapeText(item.smwd_reference || "")}</td>
            <td class="align-right">${item.amount_paid == null ? "" : currency(item.amount_paid)}</td>
            <td>${escapeText((item.date_paid || "").replace("T", " "))}</td>
            <td>${item.matched ? "<strong>✓ Matched</strong>" : escapeText(item.reason)}</td>
        </tr>`)
        .join("") || '<tr><td colspan="8">No pending STA MARIA WATER bills match the filters.</td></tr>';
    updateSmwdApply();
}
function smwdChecked() {
    return Array.from(smwd.body.querySelectorAll("[data-smwd]:checked")).map((el) => smwd.items[Number(el.dataset.smwd)]);
}
function updateSmwdApply() {
    const count = smwdChecked().length;
    smwd.apply.disabled = !count;
    smwd.apply.textContent = count ? `Apply ${count} reference${count === 1 ? "" : "s"}` : "Apply checked references";
}
smwd.body?.addEventListener("change", updateSmwdApply);
document.getElementById("smwdCloseBtn")?.addEventListener("click", () => smwd.dialog.close());
document.getElementById("smwdRefsBtn")?.addEventListener("click", async () => {
    if (!/STA MARIA WATER/i.test(filters.biller?.value || "")) {
        await showMessage("Choose the biller STA MARIA WATER in the filters first. Only its pending bills are looked up.", "SMWD References");
        return;
    }
    const params = buildFilterParams();
    params.delete("status"); // always the pending ones
    const search = table.search();
    if (search) params.set("search", search);
    smwd.items = [];
    smwd.body.innerHTML = "";
    smwd.apply.disabled = true;
    smwd.status.textContent = "Checking each pending bill on SMWD's Billing Inquiry… this can take a minute.";
    smwd.dialog.showModal();
    try {
        const response = await fetch(`/api/records/smwd/preview?${params}`, { method: "POST" });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "Couldn't check SMWD");
        smwd.items = data.items || [];
        const matched = smwd.items.filter((i) => i.matched).length;
        smwd.status.textContent =
            `${matched} of ${smwd.items.length} pending bill${smwd.items.length === 1 ? "" : "s"} matched a payment at SMWD.` +
            (data.pending > data.checked ? ` Only the first ${data.checked} of ${data.pending} were checked; run it again after applying.` : "") +
            " Matched ones are checked; nothing is saved until you apply.";
        renderSmwd();
    } catch (err) {
        smwd.status.textContent = err.message;
    }
});
smwd.apply?.addEventListener("click", async () => {
    const items = smwdChecked().map((item) => ({ id: item.id, reference: item.smwd_reference }));
    if (!items.length) return;
    smwd.apply.disabled = true;
    try {
        const response = await fetch("/api/records/smwd/apply", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ items, channel: smwd.channel.value }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "Couldn't save the references");
        smwd.dialog.close();
        table.ajax.reload(null, false);
        await showMessage(
            `${data.applied} bill${data.applied === 1 ? "" : "s"} now processed with SMWD's reference.` +
                (data.skipped ? ` ${data.skipped} skipped (no longer pending).` : ""),
            "SMWD References",
        );
    } catch (err) {
        smwd.status.textContent = err.message;
        updateSmwdApply();
    }
});

// Payment sheet: the bills of one biller to pay at the biller in cash (choose the biller, usually Status: Pending).
document.getElementById("paymentSheetBtn")?.addEventListener("click", async () => {
    if (!filters.biller?.value) {
        await showMessage("Choose a biller first: a payment sheet is for one biller (e.g. STA MARIA WATER, Status: Pending).", "Payment Sheet");
        return;
    }
    const params = buildFilterParams();
    const search = table.search();
    if (search) params.set("search", search);
    window.open(`/admin/records/payment-sheet?${params}`, "_blank");
});

// Print: every bill matching the filters and search (not just this page), with the totals.
document.getElementById("printRecordsBtn")?.addEventListener("click", () => {
    const params = buildFilterParams();
    const search = table.search();
    if (search) params.set("search", search);
    window.open(`/admin/records/print${params.toString() ? `?${params}` : ""}`, "_blank");
});

async function updateRecordsKpis() {
    if (kpiAbortController) {
        kpiAbortController.abort();
    }
    kpiAbortController = new AbortController();
    const params = new URLSearchParams();
    if (filters.biller?.value) params.set("biller", filters.biller.value);
    if (filters.fromDate?.value) params.set("from_date", filters.fromDate.value);
    if (filters.toDate?.value) params.set("to_date", filters.toDate.value);
    if (filters.dueStatus?.value) params.set("due_status", filters.dueStatus.value);
    Object.entries(EXTRA_FILTER_PARAMS).forEach(([key, param]) => filters[key]?.value && params.set(param, filters[key].value));
    const url = `/api/admin/records/kpis${params.toString() ? `?${params.toString()}` : ""}`;

    try {
        const response = await fetch(url, { signal: kpiAbortController.signal });
        if (!response.ok) {
            return;
        }
        const data = await response.json();
        if (kpis.visible) kpis.visible.textContent = String(data.visible_records ?? 0);
        if (kpis.processed) kpis.processed.textContent = String(data.processed_records ?? 0);
        if (kpis.pending) kpis.pending.textContent = String(data.pending_records ?? 0);
        if (kpis.urgent) kpis.urgent.textContent = String(data.urgent_records ?? 0);
        if (kpis.scope) kpis.scope.textContent = data.default_scope ? "Scope: Current month" : "Scope: Filtered";
    } catch (err) {
        if (err && err.name === "AbortError") {
            return;
        }
    }
}

table.on("draw", updateRecordsKpis);

const usersDialog = document.getElementById("usersDialog");
const openUsersBtn = document.getElementById("openUsersBtn");
const closeUsersBtn = document.getElementById("closeUsersBtn");
const openAddUserBtn = document.getElementById("openAddUserBtn");
const addUserDialog = document.getElementById("addUserDialog");
const closeAddUserBtn = document.getElementById("closeAddUserBtn");
const addUserForm = document.getElementById("addUserForm");
const addUserFirstName = document.getElementById("addUserFirstName");
const addUserLastName = document.getElementById("addUserLastName");
const addUserPhone = document.getElementById("addUserPhone");
const addUserPin = document.getElementById("addUserPin");
const addUserRole = document.getElementById("addUserRole");
let usersTableInitialized = false;
let usersTableInstance = null;

function initUsersTableIfNeeded() {
    if (usersTableInitialized) {
        return;
    }

    const usersTableEl = document.getElementById("usersTable");
    if (!usersTableEl) {
        return;
    }

    usersTableInstance = new DataTable("#usersTable", {
        processing: true,
        ajax: {
            url: "/api/admin/users",
            dataSrc: "users",
        },
        pageLength: 10,
        autoWidth: false,
        columns: [
            { data: "id", className: "align-center" },
            { data: "first_name" },
            { data: "last_name" },
            { data: "phone", render: (d) => `<span class="mono">${d || ""}</span>`, className: "align-center" },
            {
                data: "role",
                className: "align-center",
                render: (d) => {
                    const role = String(d || "").toLowerCase();
                    const roleClass = role === "encoder" ? "role-encoder" : "role-customer";
                    return `<span class="role-pill ${roleClass}">${role || ""}</span>`;
                },
            },
            { data: "created_at", render: formatDateTime },
        ],
        order: [[5, "desc"]],
    });

    usersTableInitialized = true;
}

if (usersDialog && openUsersBtn && closeUsersBtn) {
    openUsersBtn.addEventListener("click", () => {
        initUsersTableIfNeeded();
        usersDialog.showModal();
    });
    closeUsersBtn.addEventListener("click", () => usersDialog.close());
}

function resetAddUserForm() {
    if (!addUserForm) {
        return;
    }
    addUserForm.reset();
    if (addUserRole) {
        addUserRole.value = "encoder";
    }
}

if (openAddUserBtn && addUserDialog && closeAddUserBtn) {
    openAddUserBtn.addEventListener("click", () => {
        resetAddUserForm();
        addUserDialog.showModal();
    });
    closeAddUserBtn.addEventListener("click", () => addUserDialog.close());
}

async function saveUser(event) {
    event.preventDefault();
    const payload = {
        first_name: (addUserFirstName?.value || "").trim(),
        last_name: (addUserLastName?.value || "").trim(),
        phone: (addUserPhone?.value || "").trim(),
        pin: (addUserPin?.value || "").trim(),
        role: (addUserRole?.value || "").trim(),
    };

    if (!payload.first_name || !payload.last_name || !payload.phone || !payload.pin || !payload.role) {
        await showMessage("All fields are required.", "Validation");
        return;
    }

    const response = await fetch("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        await showMessage(err.detail || "Unable to save user.", "Save Failed");
        return;
    }

    addUserDialog.close();
    if (usersTableInstance) {
        usersTableInstance.ajax.reload(null, false);
    }
    await showMessage("User saved successfully.", "Saved");
}

if (addUserForm) {
    addUserForm.addEventListener("submit", saveUser);
}

function clearForm() {
    dom.form.reset();
    dom.recordId.value = "";
    setCurrentTxnDate();
    updateCurrentDateTime();
    dom.billAmt.value = "0";
    dom.amt2.value = "0";
    dom.cash.value = "0";
    dom.reference.value = "";
     if (dom.paymentReference) {
        dom.paymentReference.value = "";
    }
    if (dom.confirmationReference) {
        dom.confirmationReference.value = "";
    }
    if (dom.paymentMethod) {
        dom.paymentMethod.value = "";
    }
    if (dom.paymentChannel) {
        dom.paymentChannel.value = "";
    }
    syncConfirmationReferenceState();
    recomputeFinancials();
}

/** Lookup by account only; if found, fill biller, name, phone. If not, show message so user can enter details (saved to customer DB on save). */
async function lookupAccountDetails() {
    const account = dom.account.value.trim();
    if (!account) {
        return;
    }

    const params = new URLSearchParams({ account });
    const response = await fetch(`/api/customers/lookup?${params}`);
    if (!response.ok) {
        if (response.status === 404) {
            alert("Account does not exist. You may enter the details below.");
        }
        return;
    }

    const data = await response.json();
    dom.biller.value = valueOrEmpty(data.biller);
    dom.customerName.value = valueOrEmpty(data.customer_name);
    dom.cpNumber.value = valueOrEmpty(data.phone);
    recomputeFinancials();
}

function openCreate() {
    clearForm();
    dom.title.textContent = "Payment Entry";
    dom.dialog.showModal();
}

async function openEdit(id) {
    const response = await fetch(`/api/records/${id}`);
    if (!response.ok) {
        await showMessage("Unable to load record.", "Load Failed");
        return;
    }

    const data = await response.json();
    dom.title.textContent = "Edit Payment Entry";
    dom.recordId.value = data.id;
    dom.txnDate.value = valueOrEmpty(data.txn_date);
    dom.account.value = valueOrEmpty(data.account);
    dom.biller.value = valueOrEmpty(data.biller);
    dom.customerName.value = valueOrEmpty(data.customer_name);
    dom.cpNumber.value = valueOrEmpty(data.cp_number);
    dom.billAmt.value = valueOrEmpty(data.bill_amt);
    dom.amt2.value = valueOrEmpty(data.late_charge ?? data.amt2);
    dom.cash.value = valueOrEmpty(data.cash);
    dom.dueDate.value = valueOrEmpty(data.due_date);
    dom.notes.value = valueOrEmpty(data.notes);
    dom.reference.value = valueOrEmpty(data.reference);
    if (dom.paymentReference) {
        dom.paymentReference.value = valueOrEmpty(data.payment_reference);
    }
    if (dom.confirmationReference) {
        dom.confirmationReference.value = valueOrEmpty(data.confirmation_reference);
    }
    if (dom.paymentMethod) {
        dom.paymentMethod.value = valueOrEmpty(data.payment_method || "");
    }
    if (dom.paymentChannel) {
        dom.paymentChannel.value = valueOrEmpty(data.payment_channel || "");
    }
    syncConfirmationReferenceState();
    updateCurrentDateTime();
    recomputeFinancials();

    dom.dialog.showModal();
}

async function removeRecord(id) {
    const confirmed = await showConfirm("Delete this record?", "Delete Record");
    if (!confirmed) {
        return;
    }

    const response = await fetch(`/api/records/${id}`, { method: "DELETE" });
    if (!response.ok) {
        await showMessage("Delete failed. Please try again.", "Delete Failed");
        return;
    }

    table.ajax.reload(null, false);
}

function payloadFromForm() {
    syncConfirmationReferenceState();
    recomputeFinancials();
    return {
        txn_datetime: toLocalISOString(),
        txn_date: dom.txnDate.value,
        account: dom.account.value.trim(),
        biller: dom.biller.value.trim(),
        customer_name: dom.customerName.value.trim(),
        cp_number: dom.cpNumber.value.trim(),
        bill_amt: round2(dom.billAmt.value),
        late_charge: round2(dom.amt2.value),
        charge: round2(dom.charge.value),
        total: round2(dom.total.value),
        cash: round2(dom.cash.value),
        change_amt: round2(dom.changeAmt.value),
        due_date: dom.dueDate.value || null,
        notes: dom.notes.value.trim() || null,
        reference: dom.reference.value.trim() || null,
        payment_channel: dom.paymentChannel ? (dom.paymentChannel.value || null) : null,
        payment_reference: dom.paymentReference ? dom.paymentReference.value.trim() || null : null,
        confirmation_reference: dom.confirmationReference ? dom.confirmationReference.value.trim() || null : null,
        payment_method: dom.paymentMethod ? (dom.paymentMethod.value || null) : null,
    };
}

function validatePayload(payload) {
    if (!payload.txn_date) {
        showMessage("Transaction date is required.", "Validation");
        return false;
    }

    if (payload.cp_number && !/^\d{11}$/.test(payload.cp_number)) {
        showMessage("CP number must be exactly 11 digits.", "Validation");
        return false;
    }

    if (!payload.account) {
        showMessage("Account is required.", "Validation");
        return false;
    }

    if (BILLER_CHARGES[normalizedBillerKey(payload.biller)] == null) {
        showMessage("Biller rule is not configured. Please update Admin Settings.", "Validation");
        return false;
    }
    const requiredDigits = BILLER_ACCOUNT_DIGITS[normalizedBillerKey(payload.biller)];
    if (requiredDigits != null) {
        const accountDigits = String(payload.account || "").replace(/\D/g, "");
        if (accountDigits.length !== Number(requiredDigits)) {
            showMessage(
                `Account must be exactly ${requiredDigits} digits for ${payload.biller}.`,
                "Validation"
            );
            return false;
        }
    }

    if (!payload.due_date) {
        showMessage("Due date is required.", "Validation");
        return false;
    }

    if (payload.bill_amt <= 0) {
        showMessage("Bill amount is required.", "Validation");
        return false;
    }

    const toCollect = cashExpected(payload.total, payload.cash, payload.payment_method);
    if (payload.cash < toCollect) {
        showMessage(`Cash must be at least ${toCollect.toFixed(2)}.`, "Validation");
        return false;
    }

    return true;
}

async function saveRecord(event) {
    if (event) {
        event.preventDefault();
    }

    const id = dom.recordId.value;
    const method = id ? "PUT" : "POST";
    const endpoint = id ? `/api/records/${id}` : "/api/records";
    const payload = payloadFromForm();

    if (!validatePayload(payload)) {
        return;
    }

    const response = await fetch(endpoint, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });

    if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        if (Array.isArray(err.detail)) {
            const messages = err.detail
                .map((item) => item.msg)
                .filter(Boolean)
                .join("\n");
            await showMessage(messages || "Save failed.", "Save Failed");
        } else {
            await showMessage(err.detail || "Save failed.", "Save Failed");
        }
        return;
    }

    dom.dialog.close();
    table.ajax.reload(null, false);
}

async function importCsv(event) {
    if (event) {
        event.preventDefault();
    }

    const fileInput = document.getElementById("csvFile");
    const statusEl = document.getElementById("importStatus");
    const skippedEl = document.getElementById("importSkipped");

    if (!fileInput.files[0]) {
        return;
    }

    skippedEl.replaceChildren();
    skippedEl.hidden = true;

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    statusEl.textContent = "Importing...";

    const response = await fetch("/api/records/import-csv", {
        method: "POST",
        body: formData,
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        statusEl.textContent = error.detail ? `Import failed: ${error.detail}` : "Import failed";
        return;
    }

    const result = await response.json();
    const batchNote = result.import_batch_id ? `, batch ${result.import_batch_id}` : "";
    statusEl.textContent = `Imported ${result.created}, duplicates ${result.duplicates || 0}, skipped ${result.skipped}, raw logged ${result.raw_logged || 0}${batchNote}`;
    renderImportSkipped(skippedEl, result);
    table.ajax.reload();
    fileInput.value = "";
}

const IMPORT_SKIP_REASONS = {
    INVALID_OR_MISSING_DATE: "invalid or missing date",
    MISSING_ACCOUNT_OR_CUSTOMER_NAME: "missing account or customer name",
    BILLER_NOT_IN_ACTIVE_RULES: "biller not in active biller rules",
    MATCHING_DATE_ACCOUNT_BILLER_AMOUNT: "duplicate of an existing record",
};

function renderImportSkipped(listEl, result) {
    const rows = result.skipped_rows || [];
    rows.forEach((item) => {
        const li = document.createElement("li");
        const reason = IMPORT_SKIP_REASONS[item.reason] || item.reason || item.status;
        const biller = item.biller ? ` (${item.biller})` : "";
        li.textContent = `Row ${item.row}${biller}: ${reason}`;
        listEl.appendChild(li);
    });
    const shown = rows.length;
    const total = (result.skipped || 0) + (result.duplicates || 0);
    if (total > shown) {
        const li = document.createElement("li");
        li.textContent = `...and ${total - shown} more (see batch ${result.import_batch_id} in the Database view)`;
        listEl.appendChild(li);
    }
    (result.warnings || []).forEach((warning) => {
        const li = document.createElement("li");
        li.textContent = warning;
        listEl.appendChild(li);
    });
    if (result.flagged) {
        const li = document.createElement("li");
        li.append(`${result.flagged} imported row(s) kept file amounts that differ from your biller rules or don't add up. `);
        const link = document.createElement("a");
        link.href = "/admin/reports";
        link.textContent = "Review them in Reports";
        li.appendChild(link);
        listEl.appendChild(li);
    }
    listEl.hidden = listEl.children.length === 0;
}

function buildFilterParams() {
    const params = new URLSearchParams();
    if (filters.biller?.value) params.set("biller", filters.biller.value);
    if (filters.fromDate?.value) params.set("from_date", filters.fromDate.value);
    if (filters.toDate?.value) params.set("to_date", filters.toDate.value);
    if (filters.dueStatus?.value) params.set("due_status", filters.dueStatus.value);
    Object.entries(EXTRA_FILTER_PARAMS).forEach(([key, param]) => filters[key]?.value && params.set(param, filters[key].value));
    return params;
}

const openCreateBtn = document.getElementById("openCreateBtn");
if (openCreateBtn) {
    openCreateBtn.addEventListener("click", openCreate);
}
document.getElementById("closeDialogBtn").addEventListener("click", () => dom.dialog.close());
dom.form.addEventListener("submit", saveRecord);
document.getElementById("saveRecordBtn").addEventListener("click", saveRecord);

document.getElementById("importForm").addEventListener("submit", importCsv);
document.getElementById("importCsvBtn").addEventListener("click", importCsv);

document.getElementById("clearFiltersBtn").addEventListener("click", () => {
    filters.biller.value = "";
    filters.fromDate.value = "";
    filters.toDate.value = "";
    filters.dueStatus.value = "";
    Object.keys(EXTRA_FILTER_PARAMS).forEach((key) => filters[key] && (filters[key].value = ""));
    table.search("").draw();
});

Object.values(filters).forEach((el) => {
    el.addEventListener("change", () => table.ajax.reload());
});

[dom.biller, dom.billAmt, dom.amt2, dom.cash].forEach((el) => {
    el.addEventListener("input", recomputeFinancials);
    el.addEventListener("change", recomputeFinancials);
});
if (dom.paymentMethod) {
    dom.paymentMethod.addEventListener("input", syncConfirmationReferenceState);
    dom.paymentMethod.addEventListener("change", recomputeFinancials);
    dom.paymentMethod.addEventListener("change", syncConfirmationReferenceState);
}

dom.account.addEventListener("blur", lookupAccountDetails);

updateCurrentDateTime();
setInterval(updateCurrentDateTime, 1000);
recomputeFinancials();

window.openEdit = openEdit;
window.removeRecord = removeRecord;
