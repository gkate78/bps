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
    const loadReportBtn = document.getElementById("loadReportBtn");
    const reportBlock = document.getElementById("reportBlock");
    const billerFilter = document.getElementById("billerFilter");
    const fromDateFilter = document.getElementById("fromDateFilter");
    const toDateFilter = document.getElementById("toDateFilter");
    const clearFiltersBtn = document.getElementById("clearFiltersBtn");
    const paymentRefDialog = document.getElementById("paymentRefDialog");
    const paymentRefForm = document.getElementById("paymentRefForm");
    const paymentRefRecordId = document.getElementById("paymentRefRecordId");
    const paymentRefInput = document.getElementById("paymentRefInput");
    const closePaymentRefBtn = document.getElementById("closePaymentRefBtn");

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
        const res = await fetch("/api/admin/reconciliation-summary?date=" + encodeURIComponent(dateVal));
        if (!res.ok) {
            showMessage("Failed to load report.", "Error");
            return;
        }
        const data = await res.json();
        document.getElementById("reportDateDisp").textContent = data.date || dateVal;
        document.getElementById("reportCollected").textContent = currency(data.collected);
        document.getElementById("reportProcessed").textContent = currency(data.processed);
        document.getElementById("reportPending").textContent = currency(data.pending);
        document.getElementById("reportRecordCount").textContent = data.record_count ?? 0;
        document.getElementById("reportProcessedCount").textContent = data.processed_count ?? 0;
        const flagEl = document.getElementById("reportFlag");
        const flagLabels = { match: "Match", short: "Short", pending: "Pending" };
        flagEl.textContent = flagLabels[data.flag] || data.flag || "";
        flagEl.className = "report-flag report-flag-" + (data.flag || "");
        reportBlock.classList.remove("is-hidden");
    }

    if (loadReportBtn) {
        loadReportBtn.addEventListener("click", loadReport);
    }

    const table = new DataTable("#processingTable", {
        processing: true,
        serverSide: true,
        pageLength: 25,
        ajax: {
            url: "/api/records/datatable",
            data: function (d) {
                if (billerFilter?.value) {
                    d.biller = billerFilter.value;
                } else {
                    delete d.biller;
                }
                if (fromDateFilter?.value) {
                    d.from_date = fromDateFilter.value;
                } else {
                    delete d.from_date;
                }
                if (toDateFilter?.value) {
                    d.to_date = toDateFilter.value;
                } else {
                    delete d.to_date;
                }
            },
        },
        columns: [
            { data: "id" },
            { data: "txn_date" },
            { data: "account" },
            { data: "biller" },
            { data: "customer_name" },
            { data: "total", render: currency },
            { data: "reference", render: (d) => d || "" },
            { data: "payment_reference", render: (d) => (d ? String(d) : "—") },
            {
                data: null,
                orderable: false,
                searchable: false,
                render: function (row) {
                    return '<button type="button" class="btn btn-secondary set-ref-btn" data-id="' + row.id + '" data-ref="' + (row.payment_reference || "").replace(/"/g, "&quot;") + '">Set ref</button>';
                },
            },
        ],
        order: [[1, "desc"]],
    });

    document.getElementById("processingTable").addEventListener("click", function (e) {
        const btn = e.target.closest(".set-ref-btn");
        if (!btn) return;
        const id = btn.getAttribute("data-id");
        const ref = btn.getAttribute("data-ref") || "";
        paymentRefRecordId.value = id;
        paymentRefInput.value = ref;
        paymentRefDialog.showModal();
    });

    if (closePaymentRefBtn) {
        closePaymentRefBtn.addEventListener("click", () => paymentRefDialog.close());
    }

    paymentRefForm.addEventListener("submit", async function (e) {
        e.preventDefault();
        const id = paymentRefRecordId.value;
        const value = (paymentRefInput.value || "").trim();
        const res = await fetch("/api/records/" + id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ payment_reference: value || null }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            showMessage(err.detail || "Update failed.", "Error");
            return;
        }
        paymentRefDialog.close();
        table.ajax.reload(null, false);
        showMessage("Payment reference saved.", "Saved");
    });

    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener("click", function () {
            if (billerFilter) billerFilter.value = "";
            if (fromDateFilter) fromDateFilter.value = "";
            if (toDateFilter) toDateFilter.value = "";
            table.search("").draw();
        });
    }

    [billerFilter, fromDateFilter, toDateFilter].filter(Boolean).forEach(function (el) {
        el.addEventListener("change", function () {
            table.ajax.reload();
        });
    });
})();
