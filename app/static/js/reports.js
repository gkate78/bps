(function () {
    "use strict";

    function formatMoney(value) {
        const num = Number(value || 0);
        return num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function esc(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    const periodEl = document.getElementById("reportPeriod");
    const refDateEl = document.getElementById("reportRefDate");
    const loadBtn = document.getElementById("loadSummaryBtn");
    const bodyEl = document.getElementById("reportsSummaryBody");
    const totalCollectedEl = document.getElementById("totalCollected");
    const totalProcessedEl = document.getElementById("totalProcessed");
    const totalPendingEl = document.getElementById("totalPending");
    const totalChargesEl = document.getElementById("totalCharges");
    const totalRecordCountEl = document.getElementById("totalRecordCount");
    const totalProcessedCountEl = document.getElementById("totalProcessedCount");

    const today = new Date();
    if (refDateEl) {
        refDateEl.value = today.toISOString().slice(0, 10);
    }

    function renderTotals(totals) {
        totalCollectedEl.textContent = formatMoney(totals?.collected);
        totalProcessedEl.textContent = formatMoney(totals?.processed);
        totalPendingEl.textContent = formatMoney(totals?.pending);
        totalChargesEl.textContent = formatMoney(totals?.total_charges);
        totalRecordCountEl.textContent = String(totals?.record_count ?? 0);
        totalProcessedCountEl.textContent = String(totals?.processed_count ?? 0);
    }

    function renderRows(items) {
        const flagLabels = { match: "Match", short: "Short", pending: "Pending" };
        if (!Array.isArray(items) || items.length === 0) {
            bodyEl.innerHTML = '<tr><td colspan="8">No data for selected period.</td></tr>';
            return;
        }
        bodyEl.innerHTML = items
            .map((item) => {
                const flag = String(item.flag || "");
                return `
                    <tr>
                        <td>${esc(item.period_label)}</td>
                        <td class="amount-cell">${formatMoney(item.collected)}</td>
                        <td class="amount-cell">${formatMoney(item.processed)}</td>
                        <td class="amount-cell">${formatMoney(item.pending)}</td>
                        <td class="amount-cell">${formatMoney(item.total_charges)}</td>
                        <td>${esc(item.record_count)}</td>
                        <td>${esc(item.processed_count)}</td>
                        <td class="report-flag report-flag-${esc(flag)}">${esc(flagLabels[flag] || flag)}</td>
                    </tr>
                `;
            })
            .join("");
    }

    async function loadSummary() {
        const period = (periodEl?.value || "daily").trim();
        const refDate = (refDateEl?.value || "").trim();
        const params = new URLSearchParams({ period });
        if (refDate) {
            params.set("date", refDate);
        }
        const response = await fetch(`/api/admin/reports/summary?${params.toString()}`);
        if (!response.ok) {
            bodyEl.innerHTML = '<tr><td colspan="8">Failed to load summary.</td></tr>';
            return;
        }
        const data = await response.json();
        renderTotals(data.totals || {});
        renderRows(data.items || []);
    }

    if (loadBtn) {
        loadBtn.addEventListener("click", loadSummary);
    }
    if (periodEl) {
        periodEl.addEventListener("change", loadSummary);
    }

    loadSummary();
})();
