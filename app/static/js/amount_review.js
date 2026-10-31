(function () {
    "use strict";

    const issueEl = document.getElementById("reviewIssue");
    const fromEl = document.getElementById("reviewFrom");
    const toEl = document.getElementById("reviewTo");
    const summaryEl = document.getElementById("reviewSummary");
    const bodyEl = document.getElementById("reviewBody");
    if (!bodyEl) return;

    let issueLabels = {};

    function formatMoney(value) {
        const num = Number(value || 0);
        return num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function signedMoney(value) {
        const num = Number(value || 0);
        return `${num >= 0 ? "+" : "−"}₱${formatMoney(Math.abs(num))}`;
    }

    function cell(text, className) {
        const td = document.createElement("td");
        td.textContent = text;
        if (className) td.className = className;
        return td;
    }

    function pairCell(fileValue, otherValue, isDiff) {
        const td = cell(
            otherValue === null || otherValue === undefined || !isDiff
                ? formatMoney(fileValue)
                : `${formatMoney(fileValue)} / ${formatMoney(otherValue)}`,
            isDiff ? "amount-cell is-diff" : "amount-cell",
        );
        return td;
    }

    function fillIssueOptions(labels) {
        if (issueEl.options.length > 1) return;
        Object.entries(labels).forEach(([value, label]) => {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = label;
            issueEl.appendChild(option);
        });
    }

    function renderSummary(data) {
        if (!data.flagged_records) {
            summaryEl.textContent = "No imported records need review.";
            return;
        }
        const parts = Object.entries(data.counts)
            .filter(([, n]) => n > 0)
            .map(([key, n]) => `${n} — ${issueLabels[key].toLowerCase()}`);
        let text = `${data.flagged_records} records to review: ${parts.join("; ")}.`;
        if (data.charge_diff_total || data.late_diff_total) {
            text += ` Compared with your rules, the shown records collected ${signedMoney(data.charge_diff_total)} in service charges and ${signedMoney(data.late_diff_total)} in late charges.`;
        }
        summaryEl.textContent = text;
    }

    function renderRows(items) {
        if (!items.length) {
            const tr = document.createElement("tr");
            const td = cell("No records match these filters.");
            td.colSpan = 9;
            tr.appendChild(td);
            bodyEl.replaceChildren(tr);
            return;
        }
        bodyEl.replaceChildren(
            ...items.map((item) => {
                const tr = document.createElement("tr");
                const issues = document.createElement("td");
                item.issues.forEach((key) => {
                    const span = document.createElement("span");
                    span.className = "review-issue";
                    span.textContent = issueLabels[key] || key;
                    issues.appendChild(span);
                });
                tr.append(
                    cell(item.txn_date),
                    cell(item.customer_name),
                    cell(item.account),
                    cell(item.biller),
                    cell(formatMoney(item.bill_amt), "amount-cell"),
                    pairCell(item.late_charge, item.expected_late_charge, item.issues.includes("LATE_CHARGE_DIFFERS_FROM_RULE")),
                    pairCell(item.charge, item.expected_charge, item.issues.includes("CHARGE_DIFFERS_FROM_RULE")),
                    pairCell(item.total, item.total_from_parts, item.issues.includes("TOTAL_MISMATCH")),
                    issues,
                );
                return tr;
            }),
        );
    }

    async function loadReview() {
        const params = new URLSearchParams();
        if (issueEl.value) params.set("issue", issueEl.value);
        if (fromEl.value) params.set("from_date", fromEl.value);
        if (toEl.value) params.set("to_date", toEl.value);
        summaryEl.textContent = "Loading...";
        try {
            const response = await fetch(`/api/admin/records/amount-review?${params}`);
            if (!response.ok) {
                summaryEl.textContent = "Could not load amounts to review";
                return;
            }
            const data = await response.json();
            issueLabels = data.issue_labels || {};
            fillIssueOptions(issueLabels);
            renderSummary(data);
            renderRows(data.items || []);
        } catch (err) {
            summaryEl.textContent = "Could not load amounts to review";
        }
    }

    [issueEl, fromEl, toEl].forEach((el) => el.addEventListener("change", loadReview));
    loadReview();
})();
