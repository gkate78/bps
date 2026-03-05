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
let isDirtySinceSave = false;

const dom = {
    form: document.getElementById("entryForm"),
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
    saveBtn: document.getElementById("saveEntryBtn"),
    clearBtn: document.getElementById("clearEntryBtn"),
    printPreviewBtn: document.getElementById("printPreviewBtn"),
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

    // Always show computed amounts so service/late charge fields never look missing.
    dom.amt2.value = lateCharge.toFixed(2);
    dom.charge.value = charge.toFixed(2);
    dom.total.value = total.toFixed(2);
    dom.changeAmt.value = change.toFixed(2);
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
    lastSavedRecordId = null;
    isDirtySinceSave = false;
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

async function saveEntry() {
    const payload = payloadFromForm();
    if (!validatePayload(payload)) {
        return null;
    }

    const response = await fetch("/api/records", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });

    if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        alert((err.detail || "SAVE FAILED").toString().toUpperCase());
        return null;
    }

    const saved = await response.json();
    lastSavedRecordId = saved.id;
    isDirtySinceSave = false;
    dom.saveStatus.textContent = "SAVED SUCCESSFULLY";
    return saved;
}

async function openPrintPreview() {
    if (!lastSavedRecordId) {
        alert("PLEASE SAVE FIRST BEFORE PRINTING.");
        return;
    }
    if (isDirtySinceSave) {
        alert("FORM CHANGED AFTER LAST SAVE. PLEASE SAVE AGAIN BEFORE PRINTING.");
        return;
    }
    const previewUrl = `/api/records/${lastSavedRecordId}/receipt?from=entry&copies=2`;
    const previewWindow = window.open(previewUrl, "_blank");
    if (!previewWindow) {
        alert("POP-UP BLOCKED. PLEASE ALLOW POP-UPS TO OPEN PRINT PREVIEW.");
    }
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

[
    dom.account,
    dom.biller,
    dom.customerName,
    dom.cpNumber,
    dom.billAmt,
    dom.cash,
    dom.dueDate,
].forEach((el) => {
    el.addEventListener("input", () => {
        isDirtySinceSave = true;
    });
    el.addEventListener("change", () => {
        isDirtySinceSave = true;
    });
});

let lookupTimer = null;
dom.account.addEventListener("input", () => {
    if (lookupTimer) {
        clearTimeout(lookupTimer);
    }
    lookupTimer = setTimeout(lookupAccountDetails, 350);
});
dom.account.addEventListener("blur", lookupAccountDetails);

dom.form.addEventListener("submit", (event) => event.preventDefault());
dom.form.addEventListener("keydown", (event) => {
    const target = event.target;
    if (event.key === "Enter" && target.tagName !== "TEXTAREA") {
        event.preventDefault();
        moveToNextControl(target);
    }
});
dom.saveBtn.addEventListener("click", saveEntry);
dom.clearBtn.addEventListener("click", clearForm);
dom.printPreviewBtn.addEventListener("click", openPrintPreview);
window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) {
        return;
    }
    if (event.data && event.data.type === "receipt_print_completed") {
        clearForm();
        dom.saveStatus.textContent = "PRINTED 2 COPIES. READY FOR NEXT ENTRY";
        dom.account.focus();
    }
});

updateCurrentDateTime();
setInterval(updateCurrentDateTime, 1000);
clearForm();
