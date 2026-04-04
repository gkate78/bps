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

function parseNum(value) {
    const num = Number(value);
    return Number.isFinite(num) ? num : 0;
}

function round2(value) {
    return Math.round((parseNum(value) + Number.EPSILON) * 100) / 100;
}

function formatMoney(value) {
    const num = round2(value);
    return num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const BILLER_CHARGES = window.BILLER_CHARGES || {};
const BILLER_LATE_CHARGES = window.BILLER_LATE_CHARGES || {};
const BILLER_ACCOUNT_DIGITS = window.BILLER_ACCOUNT_DIGITS || {};
let lastSavedRecordId = null;
let accountOptionsAbortController = null;
let accountOptionsDebounceTimer = null;

const dom = {
    form: document.getElementById("entryForm"),
    confirmDialog: document.getElementById("confirmDialog"),
    confirmSummary: document.getElementById("confirmSummary"),
    confirmProceedBtn: document.getElementById("confirmProceedBtn"),
    confirmCancelBtn: document.getElementById("confirmCancelBtn"),
    confirmCloseBtn: document.getElementById("confirmCloseBtn"),
    currentDateTime: document.getElementById("currentDateTime"),
    account: document.getElementById("account"),
    accountOptions: document.getElementById("accountOptions"),
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
    clearBtn: document.getElementById("clearEntryBtn"),
    printReceiptBtn: document.getElementById("printReceiptBtn"),
    saveStatus: document.getElementById("saveStatus"),
    paymentReference: document.getElementById("paymentReference"),
    confirmationReference: document.getElementById("confirmationReference"),
    paymentMethod: document.getElementById("paymentMethod"),
};

function normalizedBillerKey(value) {
    return String(value || "").trim().toUpperCase();
}

function isOverdue(dueDateValue) {
    if (!dueDateValue) {
        return false;
    }
    const due = new Date(`${dueDateValue}T00:00:00`);
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    return due < now;
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

function computeLateCharge(biller, dueDateValue) {
    if (!isOverdue(dueDateValue)) {
        return 0;
    }
    return round2(BILLER_LATE_CHARGES[normalizedBillerKey(biller)] || 0);
}

function recomputeFinancials() {
    const rawBillAmt = (dom.billAmt.value || "").trim();
    const rawCash = (dom.cash.value || "").trim();

    const billAmt = round2(rawBillAmt);
    const lateCharge = computeLateCharge(dom.biller.value, dom.dueDate.value);
    const charge = computeCharge(dom.biller.value, billAmt);
    const total = round2(billAmt + lateCharge + charge);
    const cash = round2(rawCash);
    const change = round2(cash - total);

    dom.amt2.value = rawBillAmt || dom.dueDate.value ? lateCharge.toFixed(2) : "";
    dom.charge.value = rawBillAmt ? charge.toFixed(2) : "";
    dom.total.value = rawBillAmt ? total.toFixed(2) : "";
    dom.changeAmt.value = rawBillAmt && rawCash ? change.toFixed(2) : "";
}

function updateCurrentDateTime() {
    if (!dom.currentDateTime) {
        return;
    }
    dom.currentDateTime.textContent = new Date().toLocaleString();
}

function setUppercaseInput(el) {
    el.value = String(el.value || "").toUpperCase();
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

function clearForm() {
    dom.form.reset();
    dom.saveStatus.textContent = "";
    dom.printReceiptBtn.disabled = true;
    lastSavedRecordId = null;
    syncConfirmationReferenceState();
    updateCurrentDateTime();
    recomputeFinancials();
}

function renderAccountOptions(items) {
    if (!dom.accountOptions) {
        return;
    }
    dom.accountOptions.innerHTML = "";
    for (const item of items) {
        const option = document.createElement("option");
        option.value = item.account || "";
        option.label = [item.customer_name, item.phone].filter(Boolean).join(" | ");
        dom.accountOptions.appendChild(option);
    }
}

async function fetchKnownAccounts({ query = "" } = {}) {
    const biller = dom.biller.value.trim();
    if (!biller) {
        renderAccountOptions([]);
        return;
    }

    if (accountOptionsAbortController) {
        accountOptionsAbortController.abort();
    }
    accountOptionsAbortController = new AbortController();

    const params = new URLSearchParams({ biller, limit: "50" });
    const q = String(query || "").trim();
    if (q) {
        params.set("query", q);
    }

    try {
        const response = await fetch(`/api/customers?${params}`, {
            signal: accountOptionsAbortController.signal,
        });
        if (!response.ok) {
            return;
        }
        const data = await response.json();
        renderAccountOptions(Array.isArray(data.items) ? data.items : []);
    } catch (err) {
        if (err && err.name !== "AbortError") {
            console.error("Failed to load customer accounts", err);
        }
    }
}

function scheduleKnownAccountsLookup() {
    if (accountOptionsDebounceTimer) {
        clearTimeout(accountOptionsDebounceTimer);
    }
    accountOptionsDebounceTimer = setTimeout(() => {
        fetchKnownAccounts({ query: dom.account.value });
    }, 250);
}

/** Lookup by account only; if found, fill biller, name, phone. If not, show message so user can enter details (saved to customer DB on save). */
async function lookupAccountDetails() {
    const account = dom.account.value.trim();
    if (!account) {
        if (dom.saveStatus) dom.saveStatus.textContent = "";
        return;
    }

    const params = new URLSearchParams({ account });
    const response = await fetch(`/api/customers/lookup?${params}`);
    if (!response.ok) {
        if (response.status === 404) {
            alert("Account does not exist. You may enter the details below.");
            if (dom.saveStatus) dom.saveStatus.textContent = "Account does not exist. Enter biller, name, and CP number.";
        }
        return;
    }

    if (dom.saveStatus) dom.saveStatus.textContent = "";
    const data = await response.json();
    dom.biller.value = data.biller || "";
    dom.customerName.value = data.customer_name || "";
    dom.cpNumber.value = data.phone || "";
    [dom.biller, dom.customerName, dom.cpNumber].forEach(setUppercaseInput);
    await fetchKnownAccounts({ query: dom.account.value });
    recomputeFinancials();
    if (dom.dueDate && !dom.dueDate.value) {
        dom.dueDate.focus();
    }
}

function payloadFromForm() {
    [dom.account, dom.biller, dom.customerName, dom.cpNumber].forEach(setUppercaseInput);
    syncConfirmationReferenceState();
    recomputeFinancials();
    return {
        txn_datetime: toLocalISOString(),
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
        payment_reference:
            dom.paymentReference && !dom.paymentReference.disabled
                ? dom.paymentReference.value.trim() || null
                : null,
        confirmation_reference:
            dom.confirmationReference && !dom.confirmationReference.disabled
                ? dom.confirmationReference.value.trim() || null
                : null,
        payment_method:
            dom.paymentMethod && !dom.paymentMethod.disabled
                ? (dom.paymentMethod.value || null)
                : null,
    };
}

function validatePayload(payload) {
    if (!payload.account || !payload.biller || !payload.customer_name) {
        alert("ACCOUNT, BILLER, AND NAME ARE REQUIRED");
        return false;
    }
    if (BILLER_CHARGES[normalizedBillerKey(payload.biller)] == null) {
        alert("BILLER RULE IS NOT CONFIGURED. PLEASE UPDATE ADMIN SETTINGS.");
        return false;
    }
    const requiredDigits = BILLER_ACCOUNT_DIGITS[normalizedBillerKey(payload.biller)];
    if (requiredDigits != null) {
        const accountDigits = String(payload.account || "").replace(/\D/g, "");
        if (accountDigits.length !== Number(requiredDigits)) {
            alert(`ACCOUNT MUST BE EXACTLY ${requiredDigits} DIGITS FOR ${payload.biller}.`);
            return false;
        }
    }
    if (payload.cp_number && !/^\d{11}$/.test(payload.cp_number)) {
        alert("CP NUMBER MUST BE EXACTLY 11 DIGITS");
        return false;
    }
    if (!payload.due_date) {
        alert("DUE DATE IS REQUIRED");
        return false;
    }
    if (payload.bill_amt <= 0) {
        alert("BILL AMOUNT IS REQUIRED");
        return false;
    }
    if (payload.cash < payload.total) {
        alert("CASH MUST BE GREATER THAN OR EQUAL TO TOTAL");
        return false;
    }
    return true;
}

function confirmDetails(payload) {
    const rows = [
        ["DATE/TIME", dom.currentDateTime.textContent],
        ["ACCOUNT", payload.account],
        ["BILLER", payload.biller],
        ["NAME", payload.customer_name],
        ["CP NUMBER", payload.cp_number || "-"],
        ["DUE DATE", payload.due_date || "-"],
        ["BILL AMOUNT", formatMoney(payload.bill_amt)],
        ["LATE CHARGE", formatMoney(payload.amt2)],
        ["SERVICE CHARGE", formatMoney(payload.charge)],
        ["TOTAL", formatMoney(payload.total)],
        ["CASH", formatMoney(payload.cash)],
        ["CHANGE", formatMoney(payload.change_amt)],
    ];

    dom.confirmSummary.innerHTML = rows
        .map(
            ([label, value]) =>
                `<div class="confirm-row"><span>${label}</span><strong>${value}</strong></div>`
        )
        .join("");

    return new Promise((resolve) => {
        let settled = false;
        const settle = (ok) => {
            if (settled) {
                return;
            }
            settled = true;
            dom.confirmProceedBtn.removeEventListener("click", onConfirm);
            dom.confirmCancelBtn.removeEventListener("click", onCancel);
            dom.confirmCloseBtn.removeEventListener("click", onCancel);
            dom.confirmDialog.removeEventListener("close", onClose);
            resolve(ok);
        };
        const onConfirm = () => {
            dom.confirmDialog.removeEventListener("close", onClose);
            dom.confirmDialog.close();
            settle(true);
        };
        const onCancel = () => {
            dom.confirmDialog.removeEventListener("close", onClose);
            dom.confirmDialog.close();
            settle(false);
        };
        const onClose = () => settle(false);

        dom.confirmProceedBtn.addEventListener("click", onConfirm);
        dom.confirmCancelBtn.addEventListener("click", onCancel);
        dom.confirmCloseBtn.addEventListener("click", onCancel);
        dom.confirmDialog.addEventListener("close", onClose);
        dom.confirmDialog.showModal();
    });
}

async function saveEntry(event) {
    event.preventDefault();

    const payload = payloadFromForm();
    if (!validatePayload(payload)) {
        return;
    }
    const confirmed = await confirmDetails(payload);
    if (!confirmed) {
        return;
    }

    const response = await fetch("/api/records", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });

    if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        alert((err.detail || "SAVE FAILED").toString().toUpperCase());
        return;
    }

    const saved = await response.json();
    lastSavedRecordId = saved.id;
    dom.printReceiptBtn.disabled = false;
    dom.saveStatus.textContent = "SAVED SUCCESSFULLY";
}

function printReceipt() {
    if (!lastSavedRecordId) {
        return;
    }
    window.open(`/api/records/${lastSavedRecordId}/receipt`, "_blank");
}

function moveToNextControl(current) {
    const controls = getNavigableControls();

    const idx = controls.indexOf(current);
    if (idx >= 0 && idx < controls.length - 1) {
        controls[idx + 1].focus();
    }
}

function moveToPrevControl(current) {
    const controls = getNavigableControls();
    const idx = controls.indexOf(current);
    if (idx > 0) {
        controls[idx - 1].focus();
    }
}

function getNavigableControls() {
    return Array.from(dom.form.querySelectorAll("input, select, textarea, button")).filter(
        (el) => !el.disabled && el.type !== "hidden" && el.tabIndex !== -1 && !el.readOnly
    );
}

[dom.account, dom.biller, dom.customerName, dom.cpNumber].forEach((el) => {
    el.addEventListener("input", () => setUppercaseInput(el));
});

dom.account.addEventListener("input", scheduleKnownAccountsLookup);
dom.biller.addEventListener("input", scheduleKnownAccountsLookup);
dom.biller.addEventListener("change", () => fetchKnownAccounts({ query: dom.account.value }));
if (dom.paymentMethod) {
    dom.paymentMethod.addEventListener("input", syncConfirmationReferenceState);
    dom.paymentMethod.addEventListener("change", syncConfirmationReferenceState);
}

[dom.biller, dom.billAmt, dom.cash, dom.dueDate].forEach((el) => {
    el.addEventListener("input", recomputeFinancials);
    el.addEventListener("change", recomputeFinancials);
});

/* Lookup only when user leaves the account field (blur), not while typing */
dom.account.addEventListener("blur", lookupAccountDetails);

dom.form.addEventListener("submit", saveEntry);
dom.form.addEventListener("keydown", (event) => {
    const target = event.target;
    if (event.key === "Enter" && target.tagName !== "TEXTAREA") {
        if (target.tagName === "BUTTON") {
            return;
        }
        event.preventDefault();
        moveToNextControl(target);
        return;
    }
    if (event.key === "ArrowDown") {
        event.preventDefault();
        moveToNextControl(target);
        return;
    }
    if (event.key === "ArrowUp") {
        event.preventDefault();
        moveToPrevControl(target);
        return;
    }
    if (event.key === "ArrowRight" && (target.tagName === "SELECT" || target.tagName === "BUTTON")) {
        event.preventDefault();
        moveToNextControl(target);
        return;
    }
    if (event.key === "ArrowLeft" && (target.tagName === "SELECT" || target.tagName === "BUTTON")) {
        event.preventDefault();
        moveToPrevControl(target);
    }
});
dom.clearBtn.addEventListener("click", clearForm);
dom.printReceiptBtn.addEventListener("click", printReceipt);

updateCurrentDateTime();
if (dom.currentDateTime) {
    setInterval(updateCurrentDateTime, 1000);
}
clearForm();
fetchKnownAccounts();
