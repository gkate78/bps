(function () {
    "use strict";

    function currency(value) {
        const num = Number(value || 0);
        return num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function showMessage(message, title) {
        const dialog = document.getElementById("appMessageDialog");
        const titleEl = document.getElementById("appMessageTitle");
        const textEl = document.getElementById("appMessageText");
        const okBtn = document.getElementById("appMessageOkBtn");
        const closeBtn = document.getElementById("appMessageCloseBtn");
        if (dialog && titleEl && textEl && okBtn && closeBtn) {
            titleEl.textContent = title || "Notice";
            textEl.textContent = message;
            const onClose = () => {
                dialog.close();
                okBtn.removeEventListener("click", onClose);
                closeBtn.removeEventListener("click", onClose);
                dialog.removeEventListener("close", onClose);
            };
            okBtn.addEventListener("click", onClose);
            closeBtn.addEventListener("click", onClose);
            dialog.addEventListener("close", onClose);
            dialog.showModal();
        } else {
            alert(message);
        }
    }

    const reportDateEl = document.getElementById("reportDate");
    const cashOnHandEl = document.getElementById("cashOnHand");
    const loadReportBtn = document.getElementById("loadReportBtn");
    const reportBlock = document.getElementById("reportBlock");
    const kpiCollected = document.getElementById("kpiCollected");
    const kpiProcessed = document.getElementById("kpiProcessed");
    const kpiPending = document.getElementById("kpiPending");
    const kpiCashVariance = document.getElementById("kpiCashVariance");

    if (reportDateEl) {
        const today = new Date();
        reportDateEl.value = today.toISOString().slice(0, 10);
    }

    async function loadReport() {
        const dateVal = reportDateEl?.value;
        if (!dateVal) {
            showMessage("Please select a report date.", "Report");
            return;
        }
        const params = new URLSearchParams({ date: dateVal });
        const cashRaw = (cashOnHandEl?.value || "").trim();
        if (cashRaw !== "") {
            params.set("cash_on_hand", cashRaw);
        }
        const res = await fetch("/api/admin/reconciliation-summary?" + params.toString());
        if (!res.ok) {
            showMessage("Failed to load report.", "Error");
            return;
        }
        const data = await res.json();
        document.getElementById("reportDateDisp").textContent = data.date || dateVal;
        document.getElementById("reportCollected").textContent = currency(data.collected);
        document.getElementById("reportProcessed").textContent = currency(data.processed);
        document.getElementById("reportPending").textContent = currency(data.pending);
        document.getElementById("reportTotalCharges").textContent = currency(data.total_charges);
        document.getElementById("reportCashOnHand").textContent =
            data.cash_on_hand == null ? "—" : currency(data.cash_on_hand);
        document.getElementById("reportCashVariance").textContent =
            data.cash_variance == null ? "—" : currency(data.cash_variance);
        const cashFlagEl = document.getElementById("reportCashFlag");
        const cashFlagLabels = { match: "Match", short: "Short", over: "Over" };
        cashFlagEl.textContent = data.cash_flag ? (cashFlagLabels[data.cash_flag] || data.cash_flag) : "—";
        cashFlagEl.className = "report-flag report-flag-" + (data.cash_flag || "");
        document.getElementById("reportRecordCount").textContent = data.record_count ?? 0;
        document.getElementById("reportProcessedCount").textContent = data.processed_count ?? 0;
        const flagEl = document.getElementById("reportFlag");
        const flagLabels = { match: "Match", short: "Short", pending: "Pending" };
        flagEl.textContent = flagLabels[data.flag] || data.flag || "";
        flagEl.className = "report-flag report-flag-" + (data.flag || "");
        if (kpiCollected) kpiCollected.textContent = currency(data.collected);
        if (kpiProcessed) kpiProcessed.textContent = currency(data.processed);
        if (kpiPending) kpiPending.textContent = currency(data.pending);
        if (kpiCashVariance) {
            kpiCashVariance.textContent = data.cash_variance == null ? "—" : currency(data.cash_variance);
        }
        reportBlock.classList.remove("is-hidden");
    }

    if (loadReportBtn) {
        loadReportBtn.addEventListener("click", loadReport);
    }
})();
