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
const BILLER_ACCOUNT_FORMATS = window.BILLER_ACCOUNT_FORMATS || {};
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

/** Same rule as the server: numbers only, or letters and numbers (e.g. SSS), with an optional exact length. */
function accountFormatError(account, biller) {
    const key = normalizedBillerKey(biller);
    const value = String(account || "").trim().toUpperCase();
    const length = BILLER_ACCOUNT_DIGITS[key] != null ? Number(BILLER_ACCOUNT_DIGITS[key]) : null;
    if ((BILLER_ACCOUNT_FORMATS[key] || "NUMERIC") === "ALPHANUMERIC") {
        if (!/^[A-Z0-9]+$/.test(value)) return `ACCOUNT MUST CONTAIN ONLY LETTERS AND NUMBERS (NO SPACES OR SYMBOLS) FOR ${key}.`;
        if (length && value.length !== length) return `ACCOUNT MUST BE EXACTLY ${length} LETTERS/NUMBERS FOR ${key}.`;
        return "";
    }
    if (!/^\d+$/.test(value)) return `ACCOUNT MUST CONTAIN NUMBERS ONLY FOR ${key}.`;
    if (length && value.length !== length) return `ACCOUNT MUST BE EXACTLY ${length} DIGITS (NUMBERS ONLY) FOR ${key}.`;
    return "";
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
        late_charge: round2(dom.amt2.value),
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
    if (!isKnownBiller(payload.biller)) {
        openBillerRuleDialog(payload.biller);
        return false;
    }
    const accountError = accountFormatError(payload.account, payload.biller);
    if (accountError) {
        alert(accountError);
        return false;
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
        alert("AMOUNT RECEIVED MUST BE GREATER THAN OR EQUAL TO TOTAL");
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
        ["LATE CHARGE", formatMoney(payload.late_charge)],
        ["SERVICE CHARGE", formatMoney(payload.charge)],
        ["TOTAL", formatMoney(payload.total)],
        ["AMOUNT RECEIVED", formatMoney(payload.cash)],
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
    loadMyTransactions();
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

// --- My Transactions: payments the signed-in user entered ---------------------

const myTx = {
    panel: document.getElementById("myTxPanel"),
    toggleBtn: document.getElementById("myTxToggleBtn"),
    from: document.getElementById("myTxFrom"),
    to: document.getElementById("myTxTo"),
    todayBtn: document.getElementById("myTxTodayBtn"),
    status: document.getElementById("myTxStatus"),
    body: document.getElementById("myTxBody"),
    count: document.getElementById("myTxCount"),
    total: document.getElementById("myTxTotal"),
};

function myTxToday() {
    return toLocalISOString(new Date()).slice(0, 10);
}

function myTxDateTime(value) {
    if (!value) return "-";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString("en-PH", { month: "2-digit", day: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function myTxCell(text, className) {
    const td = document.createElement("td");
    td.textContent = text ?? "";
    if (className) td.className = className;
    return td;
}

function renderMyTransactions(data) {
    myTx.count.textContent = String(data.count);
    myTx.total.textContent = formatMoney(data.total);
    const range = data.range.from === data.range.to ? data.range.from : `${data.range.from} to ${data.range.to}`;
    myTx.status.textContent = data.truncated
        ? `Showing the latest ${data.items.length} of ${data.count} payments for ${range}.`
        : `Payments you entered for ${range}.`;

    if (!data.items.length) {
        const tr = document.createElement("tr");
        const td = myTxCell("No payments entered for these dates.");
        td.colSpan = 10;
        tr.appendChild(td);
        myTx.body.replaceChildren(tr);
        return;
    }
    myTx.body.replaceChildren(
        ...data.items.map((item) => {
            const tr = document.createElement("tr");
            const actions = document.createElement("td");
            const reprint = document.createElement("button");
            reprint.type = "button";
            reprint.className = "btn btn-secondary btn-small";
            reprint.textContent = "Reprint";
            reprint.addEventListener("click", () => window.open(`/api/records/${item.id}/receipt?copies=1`, "_blank"));
            actions.appendChild(reprint);
            tr.append(
                myTxCell(myTxDateTime(item.txn_datetime)),
                myTxCell(item.customer_name),
                myTxCell(item.account),
                myTxCell(item.biller),
                myTxCell(formatMoney(item.total), "amount-cell"),
                myTxCell(formatMoney(item.cash), "amount-cell"),
                myTxCell(formatMoney(item.change_amt), "amount-cell"),
                myTxCell(item.payment_method || "-"),
                myTxCell(item.reference || "-"),
                actions,
            );
            return tr;
        }),
    );
}

async function loadMyTransactions() {
    if (!myTx.body || myTx.panel.hidden) return;
    const params = new URLSearchParams();
    if (myTx.from.value) params.set("from_date", myTx.from.value);
    if (myTx.to.value) params.set("to_date", myTx.to.value);
    myTx.status.textContent = "Loading...";
    try {
        const response = await fetch(`/api/records/mine?${params}`);
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            myTx.status.textContent = err.detail || "Could not load your transactions";
            return;
        }
        renderMyTransactions(await response.json());
    } catch (err) {
        myTx.status.textContent = "Could not load your transactions";
    }
}

if (myTx.body) {
    myTx.from.value = myTxToday();
    myTx.to.value = myTxToday();
    [myTx.from, myTx.to].forEach((el) => el.addEventListener("change", loadMyTransactions));
    myTx.todayBtn.addEventListener("click", () => {
        myTx.from.value = myTxToday();
        myTx.to.value = myTxToday();
        loadMyTransactions();
    });
    // Hidden until asked for, so the entry form stays uncluttered.
    myTx.toggleBtn.addEventListener("click", () => {
        const opening = myTx.panel.hidden;
        myTx.panel.hidden = !opening;
        myTx.toggleBtn.setAttribute("aria-expanded", String(opening));
        myTx.toggleBtn.textContent = opening ? "Hide My Transactions" : "My Transactions";
        if (opening) {
            loadMyTransactions();
            myTx.panel.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    });
}


// --- New biller rule: add a rule without leaving the form ----------------------

const ruleDialog = {
    dialog: document.getElementById("billerRuleDialog"),
    form: document.getElementById("billerRuleForm"),
    intro: document.getElementById("billerRuleIntro"),
    biller: document.getElementById("ruleBiller"),
    serviceCharge: document.getElementById("ruleServiceCharge"),
    lateCharge: document.getElementById("ruleLateCharge"),
    accountDigits: document.getElementById("ruleAccountDigits"),
    accountFormat: document.getElementById("ruleAccountFormat"),
    status: document.getElementById("billerRuleStatus"),
    saveBtn: document.getElementById("billerRuleSaveBtn"),
};
// Biller the user dismissed the popup for, so leaving the field again doesn't reopen it.
let dismissedRuleBiller = "";

function isKnownBiller(name) {
    return BILLER_CHARGES[normalizedBillerKey(name)] != null;
}

function openBillerRuleDialog(name) {
    const biller = normalizedBillerKey(name);
    ruleDialog.biller.value = biller;
    ruleDialog.serviceCharge.value = "15";
    ruleDialog.lateCharge.value = "0";
    ruleDialog.accountDigits.value = "";
    // Suggest from the account typed so far, e.g. SPA0A0000000001 -> letters and numbers, length 15.
    const typed = String(dom.account.value || "").trim().toUpperCase();
    ruleDialog.accountFormat.value = /[A-Z]/.test(typed) ? "ALPHANUMERIC" : "NUMERIC";
    if (typed) ruleDialog.accountDigits.placeholder = `e.g., ${typed.length}`;
    ruleDialog.intro.textContent = `${biller || "This biller"} has no rule yet. Add its charges to continue.`;
    ruleDialog.status.textContent = "";
    ruleDialog.dialog.showModal();
    ruleDialog.serviceCharge.focus();
    ruleDialog.serviceCharge.select();
}

function closeBillerRuleDialog() {
    dismissedRuleBiller = normalizedBillerKey(dom.biller.value);
    ruleDialog.dialog.close();
    if (dom.saveStatus && !isKnownBiller(dom.biller.value)) {
        dom.saveStatus.textContent = "Biller has no rule yet; it's needed before saving.";
    }
}

function addBillerOption(biller) {
    const list = document.getElementById("billerOptions");
    if (!list || Array.from(list.options).some((opt) => opt.value === biller)) return;
    const option = document.createElement("option");
    option.value = biller;
    list.appendChild(option);
}

async function saveBillerRule(event) {
    event.preventDefault();
    const biller = normalizedBillerKey(ruleDialog.biller.value);
    const serviceCharge = Number(ruleDialog.serviceCharge.value);
    const lateCharge = Number(ruleDialog.lateCharge.value || 0);
    const digitsRaw = String(ruleDialog.accountDigits.value || "").trim();
    if (!biller) {
        ruleDialog.status.textContent = "Enter the biller name.";
        return;
    }
    if (!Number.isFinite(serviceCharge) || serviceCharge < 0 || !Number.isFinite(lateCharge) || lateCharge < 0) {
        ruleDialog.status.textContent = "Charges must be zero or more.";
        return;
    }
    if (digitsRaw && !(Number.isInteger(Number(digitsRaw)) && Number(digitsRaw) > 0)) {
        ruleDialog.status.textContent = "Account digits must be a whole number above zero.";
        return;
    }

    ruleDialog.saveBtn.disabled = true;
    ruleDialog.status.textContent = "Saving...";
    try {
        const response = await fetch("/api/biller-rules", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                biller,
                service_charge: round2(serviceCharge),
                late_charge: round2(lateCharge),
                account_digits: digitsRaw ? Number(digitsRaw) : null,
                account_format: ruleDialog.accountFormat.value,
            }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = Array.isArray(data.detail) ? "Please check the values." : data.detail;
            ruleDialog.status.textContent = detail || "Could not save the rule.";
            return;
        }
        BILLER_CHARGES[data.biller] = data.service_charge;
        BILLER_LATE_CHARGES[data.biller] = data.late_charge;
        if (data.account_digits) BILLER_ACCOUNT_DIGITS[data.biller] = data.account_digits;
        BILLER_ACCOUNT_FORMATS[data.biller] = data.account_format;
        addBillerOption(data.biller);
        dom.biller.value = data.biller;
        dismissedRuleBiller = "";
        ruleDialog.dialog.close();
        if (dom.saveStatus) dom.saveStatus.textContent = `Rule for ${data.biller} saved.`;
        recomputeFinancials();
        fetchKnownAccounts({ query: dom.account.value });
        (dom.customerName.value ? dom.dueDate : dom.customerName).focus();
    } catch (err) {
        ruleDialog.status.textContent = "Could not save the rule. Check the connection and try again.";
    } finally {
        ruleDialog.saveBtn.disabled = false;
    }
}

if (ruleDialog.dialog) {
    ruleDialog.form.addEventListener("submit", saveBillerRule);
    document.getElementById("billerRuleCancelBtn").addEventListener("click", closeBillerRuleDialog);
    document.getElementById("billerRuleCloseBtn").addEventListener("click", closeBillerRuleDialog);
    ruleDialog.dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        closeBillerRuleDialog();
    });
    ruleDialog.biller.addEventListener("input", () => setUppercaseInput(ruleDialog.biller));
    // Offer the rule as soon as an unknown biller is entered (when leaving the field).
    dom.biller.addEventListener("change", () => {
        const biller = normalizedBillerKey(dom.biller.value);
        if (biller && !isKnownBiller(biller) && biller !== dismissedRuleBiller) {
            openBillerRuleDialog(biller);
        }
    });
}
