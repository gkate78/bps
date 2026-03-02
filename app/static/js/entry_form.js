function parseNum(value) {
    const num = Number(value);
    return Number.isFinite(num) ? num : 0;
}

function round2(value) {
    return Math.round((parseNum(value) + Number.EPSILON) * 100) / 100;
}

const BILLER_CHARGES = window.BILLER_CHARGES || {};
const BILLER_LATE_CHARGES = window.BILLER_LATE_CHARGES || {};
let lastSavedRecordId = null;

const dom = {
    form: document.getElementById("entryForm"),
    confirmDialog: document.getElementById("confirmDialog"),
    confirmSummary: document.getElementById("confirmSummary"),
    confirmProceedBtn: document.getElementById("confirmProceedBtn"),
    confirmCancelBtn: document.getElementById("confirmCancelBtn"),
    confirmCloseBtn: document.getElementById("confirmCloseBtn"),
    currentDateTime: document.getElementById("currentDateTime"),
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
    clearBtn: document.getElementById("clearEntryBtn"),
    printReceiptBtn: document.getElementById("printReceiptBtn"),
    saveStatus: document.getElementById("saveStatus"),
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
    dom.currentDateTime.textContent = new Date().toLocaleString();
}

function setUppercaseInput(el) {
    el.value = String(el.value || "").toUpperCase();
}

function clearForm() {
    dom.form.reset();
    dom.saveStatus.textContent = "";
    dom.printReceiptBtn.disabled = true;
    lastSavedRecordId = null;
    recomputeFinancials();
}

async function lookupAccountDetails() {
    const account = dom.account.value.trim();
    if (!account) {
        return;
    }

    const response = await fetch(`/api/records/by-account/${encodeURIComponent(account)}`);
    if (!response.ok) {
        return;
    }

    const data = await response.json();
    dom.biller.value = data.biller || "";
    dom.customerName.value = data.customer_name || "";
    dom.cpNumber.value = data.cp_number || "";
    recomputeFinancials();
}

function payloadFromForm() {
    [dom.account, dom.biller, dom.customerName, dom.cpNumber].forEach(setUppercaseInput);
    recomputeFinancials();
    return {
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
    };
}

function validatePayload(payload) {
    if (!payload.account || !payload.biller || !payload.customer_name) {
        alert("ACCOUNT, BILLER, AND NAME ARE REQUIRED");
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
        ["BILL AMOUNT", payload.bill_amt.toFixed(2)],
        ["LATE CHARGE", payload.amt2.toFixed(2)],
        ["SERVICE CHARGE", payload.charge.toFixed(2)],
        ["TOTAL", payload.total.toFixed(2)],
        ["CASH", payload.cash.toFixed(2)],
        ["CHANGE", payload.change_amt.toFixed(2)],
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
    const controls = Array.from(
        dom.form.querySelectorAll("input, select, textarea, button")
    ).filter((el) => !el.disabled && el.type !== "hidden" && el.tabIndex !== -1 && !el.readOnly);

    const idx = controls.indexOf(current);
    if (idx >= 0 && idx < controls.length - 1) {
        controls[idx + 1].focus();
    }
}

[dom.account, dom.biller, dom.customerName, dom.cpNumber].forEach((el) => {
    el.addEventListener("input", () => setUppercaseInput(el));
});

[dom.biller, dom.billAmt, dom.cash, dom.dueDate].forEach((el) => {
    el.addEventListener("input", recomputeFinancials);
    el.addEventListener("change", recomputeFinancials);
});

let lookupTimer = null;
dom.account.addEventListener("input", () => {
    if (lookupTimer) {
        clearTimeout(lookupTimer);
    }
    lookupTimer = setTimeout(lookupAccountDetails, 350);
});
dom.account.addEventListener("blur", lookupAccountDetails);

dom.form.addEventListener("submit", saveEntry);
dom.form.addEventListener("keydown", (event) => {
    const target = event.target;
    if (event.key === "Enter" && target.tagName !== "TEXTAREA") {
        event.preventDefault();
        moveToNextControl(target);
    }
});
dom.clearBtn.addEventListener("click", clearForm);
dom.printReceiptBtn.addEventListener("click", printReceipt);

updateCurrentDateTime();
setInterval(updateCurrentDateTime, 1000);
clearForm();
