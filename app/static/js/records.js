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
    paymentReference: document.getElementById("paymentReference"),
    paymentMethod: document.getElementById("paymentMethod"),
};

const filters = {
    biller: document.getElementById("billerFilter"),
    fromDate: document.getElementById("fromDateFilter"),
    toDate: document.getElementById("toDateFilter"),
    dueStatus: document.getElementById("dueStatusFilter"),
};

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
    const change = round2(cash - total);

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
        },
    },
    columns: [
        { data: "id" },
        { data: "txn_datetime", render: formatDateTime },
        { data: "account" },
        { data: "biller" },
        { data: "customer_name" },
        { data: "bill_amt", render: currency },
        { data: "due_date", render: (d) => d || "-" },
        {
            data: null,
            render: (row) => paymentStatePill(row),
        },
        { data: "reference", render: (d) => d || "" },
        {
            data: null,
            orderable: false,
            searchable: false,
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

const auditTableEl = document.getElementById("auditTable");
const toggleAuditBtn = document.getElementById("toggleAuditBtn");
const auditLogBody = document.getElementById("auditLogBody");
let auditTableInstance = null;

function initAuditTableIfNeeded() {
    if (!auditTableEl || auditTableInstance) {
        return;
    }
    auditTableInstance = new DataTable("#auditTable", {
        processing: true,
        ajax: {
            url: "/api/admin/record-audit",
            dataSrc: "logs",
        },
        pageLength: 10,
        autoWidth: false,
        columns: [
            { data: "created_at", render: formatDateTime },
            { data: "actor_name", render: (d) => d || "-" },
            { data: "actor_role", render: (d) => d || "-" },
            { data: "action", render: (d) => String(d || "").toUpperCase() },
            { data: "channel", render: (d) => String(d || "").toUpperCase() },
            { data: "status", render: formatStatusPill },
            { data: "record_id", render: (d) => (d == null ? "-" : d) },
            { data: "detail", render: (d) => d || "" },
        ],
        order: [[0, "desc"]],
    });
}

function reloadAuditLog() {
    if (auditTableInstance) {
        auditTableInstance.ajax.reload(null, false);
    }
}

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
            { data: "id" },
            { data: "first_name" },
            { data: "last_name" },
            { data: "phone", render: (d) => `<span class="mono">${d || ""}</span>` },
            {
                data: "role",
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
    if (dom.paymentMethod) {
        dom.paymentMethod.value = "";
    }
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
    dom.amt2.value = valueOrEmpty(data.amt2);
    dom.cash.value = valueOrEmpty(data.cash);
    dom.dueDate.value = valueOrEmpty(data.due_date);
    dom.notes.value = valueOrEmpty(data.notes);
    dom.reference.value = valueOrEmpty(data.reference);
    if (dom.paymentReference) {
        dom.paymentReference.value = valueOrEmpty(data.payment_reference);
    }
    if (dom.paymentMethod) {
        dom.paymentMethod.value = valueOrEmpty(data.payment_method || "");
    }
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
        reloadAuditLog();
        return;
    }

    table.ajax.reload(null, false);
    reloadAuditLog();
}

function payloadFromForm() {
    recomputeFinancials();
    return {
        txn_datetime: toLocalISOString(),
        txn_date: dom.txnDate.value,
        account: dom.account.value.trim(),
        biller: dom.biller.value.trim(),
        customer_name: dom.customerName.value.trim(),
        cp_number: dom.cpNumber.value.trim(),
        bill_amt: round2(dom.billAmt.value),
        amt2: round2(dom.amt2.value),
        charge: round2(dom.charge.value),
        total: round2(dom.total.value),
        cash: round2(dom.cash.value),
        change_amt: round2(dom.changeAmt.value),
        due_date: dom.dueDate.value || null,
        notes: dom.notes.value.trim() || null,
        reference: dom.reference.value.trim() || null,
        payment_reference: dom.paymentReference ? dom.paymentReference.value.trim() || null : null,
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

    if (payload.cash < payload.total) {
        showMessage("Cash must be greater than or equal to Total.", "Validation");
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
        reloadAuditLog();
        return;
    }

    dom.dialog.close();
    table.ajax.reload(null, false);
    reloadAuditLog();
}

async function importCsv(event) {
    if (event) {
        event.preventDefault();
    }

    const fileInput = document.getElementById("csvFile");
    const statusEl = document.getElementById("importStatus");

    if (!fileInput.files[0]) {
        return;
    }

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    statusEl.textContent = "Importing...";

    const response = await fetch("/api/records/import-csv", {
        method: "POST",
        body: formData,
    });

    if (!response.ok) {
        statusEl.textContent = "Import failed";
        reloadAuditLog();
        return;
    }

    const result = await response.json();
    statusEl.textContent = `Imported ${result.created}, duplicates ${result.duplicates || 0}, skipped ${result.skipped}`;
    table.ajax.reload();
    reloadAuditLog();
    fileInput.value = "";
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
    table.search("").draw();
});

const refreshAuditBtn = document.getElementById("refreshAuditBtn");
if (refreshAuditBtn) {
    refreshAuditBtn.addEventListener("click", () => {
        initAuditTableIfNeeded();
        reloadAuditLog();
    });
}

if (toggleAuditBtn && auditLogBody) {
    toggleAuditBtn.addEventListener("click", () => {
        const showing = !auditLogBody.classList.contains("is-hidden");
        if (showing) {
            auditLogBody.classList.add("is-hidden");
            toggleAuditBtn.textContent = "Show Audit Log";
            return;
        }
        auditLogBody.classList.remove("is-hidden");
        toggleAuditBtn.textContent = "Hide Audit Log";
        initAuditTableIfNeeded();
        reloadAuditLog();
    });
}

Object.values(filters).forEach((el) => {
    el.addEventListener("change", () => table.ajax.reload());
});

[dom.biller, dom.billAmt, dom.amt2, dom.cash].forEach((el) => {
    el.addEventListener("input", recomputeFinancials);
    el.addEventListener("change", recomputeFinancials);
});

dom.account.addEventListener("blur", lookupAccountDetails);

updateCurrentDateTime();
setInterval(updateCurrentDateTime, 1000);
recomputeFinancials();

window.openEdit = openEdit;
window.removeRecord = removeRecord;
