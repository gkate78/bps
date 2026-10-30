const SVG_NS = "http://www.w3.org/2000/svg";
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MEASURES = {
    transactions: { label: "Transactions", money: false },
    service_income: { label: "Service income", money: true },
    bill_total: { label: "Bills paid", money: true },
};
// Sequential blue ramp (light -> dark) for the busy-times heatmap.
const HEAT_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];

const els = {
    from: document.getElementById("insFrom"),
    to: document.getElementById("insTo"),
    biller: document.getElementById("insBiller"),
    preset: document.getElementById("insPreset"),
    status: document.getElementById("insStatus"),
    kpis: document.getElementById("insKpis"),
    tooltip: document.getElementById("chartTooltip"),
};

let measure = "transactions";
let data = null;

const pesoFmt = new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP", maximumFractionDigits: 2 });
const intFmt = new Intl.NumberFormat("en-PH");

function money(value) {
    return pesoFmt.format(value || 0);
}

function compact(value, isMoney) {
    const abs = Math.abs(value);
    let text;
    if (abs >= 1e6) text = `${(value / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}M`;
    else if (abs >= 1e3) text = `${(value / 1e3).toFixed(abs >= 1e4 ? 0 : 1)}K`;
    else text = intFmt.format(Math.round(value));
    return isMoney ? `₱${text}` : text;
}

function pct(value) {
    return `${(value * 100).toFixed(1)}%`;
}

function formatMeasure(value, key) {
    return MEASURES[key].money ? money(value) : intFmt.format(value);
}

function isoDate(d) {
    const off = d.getTimezoneOffset();
    return new Date(d.getTime() - off * 60000).toISOString().slice(0, 10);
}

function periodLabel(period, granularity) {
    if (granularity === "month") {
        const [y, m] = period.split("-").map(Number);
        return new Date(y, m - 1, 1).toLocaleDateString("en-PH", { month: "short", year: "numeric" });
    }
    const [y, m, d] = period.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString("en-PH", { month: "short", day: "numeric" });
}

function svgEl(tag, attrs = {}, text) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    if (text !== undefined) node.textContent = text;
    return node;
}

// Bar with a 4px rounded data-end and a square baseline.
function barPath(x, y, w, h, horizontal) {
    const r = Math.min(4, horizontal ? h / 2 : w / 2, horizontal ? w : h);
    if (h <= 0 || w <= 0) return "";
    if (horizontal) {
        return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
    }
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function niceMax(value) {
    if (value <= 0) return 1;
    const exp = Math.pow(10, Math.floor(Math.log10(value)));
    const f = value / exp;
    const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 3 ? 3 : f <= 4 ? 4 : f <= 5 ? 5 : f <= 8 ? 8 : 10;
    return nice * exp;
}

// --- Tooltip ---------------------------------------------------------------

function showTooltip(event, lines) {
    const tip = els.tooltip;
    tip.replaceChildren();
    lines.forEach((line, i) => {
        const row = document.createElement("div");
        row.textContent = line;
        if (i === 0) row.className = "chart-tooltip-title";
        tip.appendChild(row);
    });
    tip.hidden = false;
    const pad = 12;
    const rect = tip.getBoundingClientRect();
    let left = event.clientX + pad;
    let top = event.clientY + pad;
    if (left + rect.width > window.innerWidth - 8) left = event.clientX - rect.width - pad;
    if (top + rect.height > window.innerHeight - 8) top = event.clientY - rect.height - pad;
    tip.style.left = `${Math.max(8, left)}px`;
    tip.style.top = `${Math.max(8, top)}px`;
}

function hideTooltip() {
    els.tooltip.hidden = true;
}

function attachHover(target, lines) {
    target.addEventListener("mousemove", (e) => showTooltip(e, lines()));
    target.addEventListener("mouseleave", hideTooltip);
    target.addEventListener("focus", (e) => {
        const box = target.getBoundingClientRect();
        showTooltip({ clientX: box.left + box.width / 2, clientY: box.top }, lines());
    });
    target.addEventListener("blur", hideTooltip);
}

// --- Data tables -----------------------------------------------------------

function renderTable(container, headers, rows, numericCols = []) {
    const table = document.createElement("table");
    table.className = "report-table insights-table";
    const thead = document.createElement("thead");
    const htr = document.createElement("tr");
    headers.forEach((h, i) => {
        const th = document.createElement("th");
        th.textContent = h;
        if (numericCols.includes(i)) th.className = "amount-cell";
        htr.appendChild(th);
    });
    thead.appendChild(htr);
    const tbody = document.createElement("tbody");
    rows.forEach((cells) => {
        const tr = document.createElement("tr");
        cells.forEach((c, i) => {
            const td = document.createElement("td");
            td.textContent = c;
            if (numericCols.includes(i)) td.className = "amount-cell";
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.append(thead, tbody);
    container.replaceChildren(table);
}

function emptyState(container, text) {
    const p = document.createElement("p");
    p.className = "chart-empty";
    p.textContent = text;
    container.replaceChildren(p);
}

// --- KPI tiles -------------------------------------------------------------

function renderKpis() {
    const t = data.totals;
    const p = data.previous_totals;
    const tiles = [
        { label: "Transactions", value: intFmt.format(t.transactions), cur: t.transactions, prev: p.transactions, upGood: true },
        { label: "Service income", value: money(t.service_income), cur: t.service_income, prev: p.service_income, upGood: true },
        { label: "Bills paid", value: money(t.bill_total), cur: t.bill_total, prev: p.bill_total, upGood: true },
        { label: "Customers", value: intFmt.format(t.customers), cur: t.customers, prev: p.customers, upGood: true },
        { label: "Average bill", value: money(t.avg_bill), cur: t.avg_bill, prev: p.avg_bill, upGood: true },
        { label: "Late charges", value: money(t.late_charges), cur: t.late_charges, prev: p.late_charges, upGood: null },
    ];
    const prevRange = `${data.previous_range.from} to ${data.previous_range.to}`;
    els.kpis.replaceChildren(
        ...tiles.map((tile) => {
            const card = document.createElement("article");
            card.className = "kpi-card";
            const label = document.createElement("p");
            label.className = "kpi-label";
            label.textContent = tile.label;
            const value = document.createElement("p");
            value.className = "kpi-value";
            value.textContent = tile.value;
            const delta = document.createElement("p");
            delta.className = "kpi-delta";
            delta.title = `Compared with ${prevRange}`;
            if (!p.transactions) {
                delta.textContent = "No earlier data to compare";
            } else if (!tile.prev) {
                delta.textContent = "New vs previous period";
            } else {
                const change = (tile.cur - tile.prev) / tile.prev;
                const arrow = change > 0.0005 ? "▲" : change < -0.0005 ? "▼" : "■";
                delta.textContent = `${arrow} ${change > 0 ? "+" : ""}${(change * 100).toFixed(1)}% vs previous period`;
                if (tile.upGood !== null && Math.abs(change) > 0.0005) {
                    delta.classList.add((change > 0) === tile.upGood ? "is-good" : "is-bad");
                }
            }
            card.append(label, value, delta);
            return card;
        }),
    );
}

// --- Column chart (trend) --------------------------------------------------

function renderTrend() {
    const box = document.getElementById("trendChart");
    const info = MEASURES[measure];
    const unit = data.granularity === "month" ? "month" : "day";
    document.getElementById("trendTitle").textContent = `${info.label} by ${unit}`;
    const points = data.trend;
    if (!data.totals.transactions) {
        emptyState(box, "No records in this range.");
        document.getElementById("trendTable").replaceChildren();
        return;
    }

    const width = Math.max(box.clientWidth, 320);
    const height = 260;
    const m = { top: 16, right: 12, bottom: 34, left: 56 };
    const plotW = width - m.left - m.right;
    const plotH = height - m.top - m.bottom;
    const maxVal = niceMax(Math.max(...points.map((p) => p[measure])));
    const band = plotW / points.length;
    const barW = Math.max(2, Math.min(24, band - 2));

    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "chart-svg", role: "img", "aria-label": `${info.label} by ${unit}` });
    for (let i = 0; i <= 4; i += 1) {
        const v = (maxVal / 4) * i;
        const y = m.top + plotH - (v / maxVal) * plotH;
        svg.appendChild(svgEl("line", { x1: m.left, x2: width - m.right, y1: y, y2: y, class: "chart-grid" }));
        svg.appendChild(svgEl("text", { x: m.left - 8, y: y + 4, "text-anchor": "end", class: "chart-tick" }, compact(v, info.money)));
    }

    const labelEvery = Math.ceil(points.length / Math.max(1, Math.floor(plotW / 64)));
    let peak = points[0];
    points.forEach((p) => { if (p[measure] > peak[measure]) peak = p; });

    points.forEach((p, i) => {
        const cx = m.left + band * i + band / 2;
        const h = (p[measure] / maxVal) * plotH;
        const x = cx - barW / 2;
        const y = m.top + plotH - h;
        svg.appendChild(svgEl("path", { d: barPath(x, y, barW, h, false), class: "chart-bar" }));
        if (i % labelEvery === 0) {
            svg.appendChild(svgEl("text", { x: cx, y: height - m.bottom + 18, "text-anchor": "middle", class: "chart-tick" }, periodLabel(p.period, data.granularity)));
        }
        if (p === peak && p[measure] > 0) {
            svg.appendChild(svgEl("text", { x: cx, y: y - 5, "text-anchor": "middle", class: "chart-value" }, compact(p[measure], info.money)));
        }
        const hit = svgEl("rect", { x: m.left + band * i, y: m.top, width: band, height: plotH, class: "chart-hit", tabindex: 0 });
        attachHover(hit, () => [
            periodLabel(p.period, data.granularity),
            `Transactions: ${intFmt.format(p.transactions)}`,
            `Service income: ${money(p.service_income)}`,
            `Bills paid: ${money(p.bill_total)}`,
        ]);
        svg.appendChild(hit);
    });
    svg.appendChild(svgEl("line", { x1: m.left, x2: width - m.right, y1: m.top + plotH, y2: m.top + plotH, class: "chart-axis" }));
    box.replaceChildren(svg);

    renderTable(
        document.getElementById("trendTable"),
        [data.granularity === "month" ? "Month" : "Day", "Transactions", "Service income", "Bills paid"],
        points.map((p) => [periodLabel(p.period, data.granularity), intFmt.format(p.transactions), money(p.service_income), money(p.bill_total)]),
        [1, 2, 3],
    );
}

// --- Horizontal bar chart --------------------------------------------------

function renderHBars(box, items, valueOf, labelOf, valueText, tooltipLines, ariaLabel) {
    if (!items.length) {
        emptyState(box, "No records in this range.");
        return;
    }
    const width = Math.max(box.clientWidth, 300);
    const rowH = 30;
    const labelW = Math.min(150, width * 0.38);
    const valueW = 72;
    const height = items.length * rowH + 8;
    const plotW = width - labelW - valueW;
    const maxVal = Math.max(...items.map(valueOf), 0) || 1;
    const barH = 16;

    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "chart-svg", role: "img", "aria-label": ariaLabel });
    items.forEach((item, i) => {
        const y = i * rowH + 4;
        const w = (valueOf(item) / maxVal) * plotW;
        svg.appendChild(svgEl("text", { x: labelW - 8, y: y + rowH / 2 + 4, "text-anchor": "end", class: "chart-label" }, labelOf(item)));
        svg.appendChild(svgEl("path", { d: barPath(labelW, y + (rowH - barH) / 2, Math.max(w, 0.5), barH, true), class: "chart-bar" }));
        svg.appendChild(svgEl("text", { x: labelW + w + 6, y: y + rowH / 2 + 4, class: "chart-value" }, valueText(item)));
        const hit = svgEl("rect", { x: 0, y, width, height: rowH, class: "chart-hit", tabindex: 0 });
        attachHover(hit, () => tooltipLines(item));
        svg.appendChild(hit);
    });
    svg.appendChild(svgEl("line", { x1: labelW, x2: labelW, y1: 0, y2: height, class: "chart-axis" }));
    box.replaceChildren(svg);
}

// Largest first, with the folded "OTHER" bucket always last.
function sortBillers(list, valueOf) {
    return [...list].sort((a, b) => (a.biller === "OTHER") - (b.biller === "OTHER") || valueOf(b) - valueOf(a));
}

function billerTooltip(b) {
    return [
        b.biller,
        `Transactions: ${intFmt.format(b.transactions)}`,
        `Service income: ${money(b.service_income)}`,
        `Bills paid: ${money(b.bill_total)}`,
        `Paid after due date: ${pct(b.late_rate)}`,
    ];
}

function renderBillers() {
    const info = MEASURES[measure];
    document.getElementById("billerTitle").textContent = `${info.label} by biller`;
    const items = sortBillers(data.billers, (b) => b[measure]);
    const total = items.reduce((s, b) => s + b[measure], 0) || 1;
    renderHBars(
        document.getElementById("billerChart"),
        items,
        (b) => b[measure],
        (b) => b.biller,
        (b) => `${compact(b[measure], info.money)} · ${Math.round((b[measure] / total) * 100)}%`,
        billerTooltip,
        `${info.label} by biller`,
    );
    renderTable(
        document.getElementById("billerTable"),
        ["Biller", "Transactions", "Service income", "Bills paid", "Paid late"],
        items.map((b) => [b.biller, intFmt.format(b.transactions), money(b.service_income), money(b.bill_total), pct(b.late_rate)]),
        [1, 2, 3, 4],
    );
}

function renderLate() {
    const items = sortBillers(data.billers.filter((b) => b.with_due > 0), (b) => b.late_rate);
    document.getElementById("lateNote").textContent = data.totals.transactions
        ? `${pct(data.totals.late_rate)} of payments came in after the bill's due date.`
        : "";
    renderHBars(
        document.getElementById("lateChart"),
        items,
        (b) => b.late_rate,
        (b) => b.biller,
        (b) => pct(b.late_rate),
        (b) => [b.biller, `Paid late: ${intFmt.format(b.late)} of ${intFmt.format(b.with_due)}`, `Rate: ${pct(b.late_rate)}`],
        "Share of payments made after due date, by biller",
    );
    renderTable(
        document.getElementById("lateTable"),
        ["Biller", "Paid late", "With due date", "Rate"],
        items.map((b) => [b.biller, intFmt.format(b.late), intFmt.format(b.with_due), pct(b.late_rate)]),
        [1, 2, 3],
    );
}

// --- Heatmap (weekday x hour) ----------------------------------------------

function heatColor(value, max) {
    if (!value) return null;
    const t = max <= 1 ? 1 : (value - 1) / (max - 1);
    return HEAT_RAMP[Math.min(HEAT_RAMP.length - 1, Math.round(t * (HEAT_RAMP.length - 1)))];
}

function hourLabel(h) {
    const suffix = h < 12 ? "am" : "pm";
    const hr = h % 12 === 0 ? 12 : h % 12;
    return `${hr}${suffix}`;
}

function renderHeatmap() {
    const box = document.getElementById("heatChart");
    const note = document.getElementById("heatNote");
    const grid = data.heatmap;
    const total = data.totals.transactions;
    if (!total) {
        note.textContent = "";
        emptyState(box, "No records in this range.");
        document.getElementById("heatTable").replaceChildren();
        return;
    }

    const dayTotals = grid.map((row) => row.reduce((s, v) => s + v, 0));
    const hourTotals = Array.from({ length: 24 }, (_, h) => grid.reduce((s, row) => s + row[h], 0));
    const busiestDay = dayTotals.indexOf(Math.max(...dayTotals));

    if (!data.has_times) {
        note.textContent = `Busiest day: ${WEEKDAYS[busiestDay]}. These records have no time of day, so only days are shown.`;
    } else {
        const busiestHour = hourTotals.indexOf(Math.max(...hourTotals));
        note.textContent = `Busiest day: ${WEEKDAYS[busiestDay]}. Busiest hour: ${hourLabel(busiestHour)}–${hourLabel((busiestHour + 1) % 24)}.`;
    }

    // Show the active part of the day: trim edge hours holding under 0.5% of transactions.
    let hours = [0];
    if (data.has_times) {
        const minCount = Math.max(1, total * 0.005);
        let first = hourTotals.findIndex((v) => v >= minCount);
        let last = 23 - [...hourTotals].reverse().findIndex((v) => v >= minCount);
        if (first < 0) {
            first = 0;
            last = 23;
        }
        hours = Array.from({ length: last - first + 1 }, (_, i) => first + i);
    }

    const width = Math.max(box.clientWidth, 320);
    const m = { top: 22, left: 40, right: 60 };
    const cellGap = 2;
    const cellW = Math.max(14, (width - m.left - m.right) / hours.length);
    const cellH = 26;
    const plotW = cellW * hours.length;
    const height = m.top + cellH * 7 + 8;
    const max = Math.max(...grid.flat());

    const svg = svgEl("svg", { viewBox: `0 0 ${m.left + plotW + m.right} ${height}`, width: m.left + plotW + m.right, height, class: "chart-svg", role: "img", "aria-label": "Transactions by weekday and hour" });
    const labelEvery = Math.ceil(hours.length / Math.max(1, Math.floor(plotW / 40)));
    hours.forEach((h, i) => {
        if (data.has_times && i % labelEvery === 0) {
            svg.appendChild(svgEl("text", { x: m.left + cellW * i + cellW / 2, y: 14, "text-anchor": "middle", class: "chart-tick" }, hourLabel(h)));
        }
    });
    WEEKDAYS.forEach((day, d) => {
        const y = m.top + d * cellH;
        svg.appendChild(svgEl("text", { x: m.left - 8, y: y + cellH / 2 + 4, "text-anchor": "end", class: "chart-tick" }, day));
        hours.forEach((h, i) => {
            const value = data.has_times ? grid[d][h] : dayTotals[d];
            const fill = heatColor(value, data.has_times ? max : Math.max(...dayTotals));
            const cell = svgEl("rect", {
                x: m.left + cellW * i + cellGap / 2,
                y: y + cellGap / 2,
                width: cellW - cellGap,
                height: cellH - cellGap,
                rx: 3,
                class: fill ? "heat-cell" : "heat-cell heat-empty",
                tabindex: 0,
            });
            if (fill) cell.setAttribute("fill", fill);
            attachHover(cell, () => [
                data.has_times ? `${day} ${hourLabel(h)}–${hourLabel((h + 1) % 24)}` : day,
                `Transactions: ${intFmt.format(value)}`,
            ]);
            svg.appendChild(cell);
        });
        svg.appendChild(svgEl("text", { x: m.left + plotW + 8, y: y + cellH / 2 + 4, class: "chart-value" }, intFmt.format(dayTotals[d])));
    });
    box.replaceChildren(svg);

    const headers = ["Day", ...(data.has_times ? hours.map(hourLabel) : []), "Total"];
    renderTable(
        document.getElementById("heatTable"),
        headers,
        WEEKDAYS.map((day, d) => [day, ...(data.has_times ? hours.map((h) => intFmt.format(grid[d][h])) : []), intFmt.format(dayTotals[d])]),
        headers.map((_, i) => i).slice(1),
    );
}

// --- Day of month ----------------------------------------------------------

function ordinal(n) {
    const tens = n % 100;
    if (tens >= 11 && tens <= 13) return `${n}th`;
    return `${n}${{ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"}`;
}

function renderDayOfMonth() {
    const box = document.getElementById("domChart");
    const note = document.getElementById("domNote");
    const days = data.day_of_month.filter((d) => d.occurrences > 0);
    if (!data.totals.transactions || !days.length) {
        note.textContent = "";
        emptyState(box, "No records in this range.");
        document.getElementById("domTable").replaceChildren();
        return;
    }

    const multiMonth = days.some((d) => d.occurrences > 1);
    const valueOf = (d) => (multiMonth ? d.avg : d.transactions);
    const ranked = [...days].sort((a, b) => valueOf(b) - valueOf(a));
    const quietest = [...days].sort((a, b) => valueOf(a) - valueOf(b))[0];
    const fmtVal = (v) => (multiMonth ? v.toFixed(1) : intFmt.format(v));
    note.textContent =
        `Busiest: ${ranked.slice(0, 3).map((d) => ordinal(d.day)).join(", ")}. Quietest: ${ordinal(quietest.day)}.` +
        (multiMonth ? " Bars show the average number of transactions on that day per month." : "");

    const width = Math.max(box.clientWidth, 320);
    const height = 240;
    const m = { top: 18, right: 12, bottom: 30, left: 44 };
    const plotW = width - m.left - m.right;
    const plotH = height - m.top - m.bottom;
    const maxVal = niceMax(Math.max(...days.map(valueOf)));
    const band = plotW / days.length;
    const barW = Math.max(2, Math.min(24, band - 2));

    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "chart-svg", role: "img", "aria-label": "Transactions by day of the month" });
    for (let i = 0; i <= 4; i += 1) {
        const v = (maxVal / 4) * i;
        const y = m.top + plotH - (v / maxVal) * plotH;
        svg.appendChild(svgEl("line", { x1: m.left, x2: width - m.right, y1: y, y2: y, class: "chart-grid" }));
        svg.appendChild(svgEl("text", { x: m.left - 8, y: y + 4, "text-anchor": "end", class: "chart-tick" }, multiMonth ? (v % 1 ? v.toFixed(1) : v) : compact(v, false)));
    }
    const labelEvery = band >= 18 ? 1 : band >= 9 ? 2 : 5;
    days.forEach((d, i) => {
        const cx = m.left + band * i + band / 2;
        const h = (valueOf(d) / maxVal) * plotH;
        const y = m.top + plotH - h;
        svg.appendChild(svgEl("path", { d: barPath(cx - barW / 2, y, barW, h, false), class: "chart-bar" }));
        if ((d.day - 1) % labelEvery === 0) {
            svg.appendChild(svgEl("text", { x: cx, y: height - m.bottom + 16, "text-anchor": "middle", class: "chart-tick" }, d.day));
        }
        if (d === ranked[0] && valueOf(d) > 0) {
            svg.appendChild(svgEl("text", { x: cx, y: y - 5, "text-anchor": "middle", class: "chart-value" }, fmtVal(valueOf(d))));
        }
        const hit = svgEl("rect", { x: m.left + band * i, y: m.top, width: band, height: plotH, class: "chart-hit", tabindex: 0 });
        attachHover(hit, () => {
            const lines = [`${ordinal(d.day)} of the month`];
            if (multiMonth) lines.push(`Average: ${d.avg.toFixed(1)} per month`);
            lines.push(`Total: ${intFmt.format(d.transactions)} transactions`);
            if (d.top_biller) lines.push(`Mostly ${d.top_biller} (${Math.round((d.top_biller_transactions / d.transactions) * 100)}%)`);
            return lines;
        });
        svg.appendChild(hit);
    });
    svg.appendChild(svgEl("line", { x1: m.left, x2: width - m.right, y1: m.top + plotH, y2: m.top + plotH, class: "chart-axis" }));
    box.replaceChildren(svg);

    renderTable(
        document.getElementById("domTable"),
        ["Day", "Transactions", "Times in range", "Average per month", "Top biller"],
        days.map((d) => [ordinal(d.day), intFmt.format(d.transactions), intFmt.format(d.occurrences), d.avg.toFixed(1), d.top_biller || "—"]),
        [1, 2, 3],
    );
}

// --- Customers -------------------------------------------------------------

function customerRows(list, withDays) {
    return list.map((c) => [
        c.name,
        c.account,
        c.billers.join(", "),
        intFmt.format(c.visits),
        money(c.bill_total),
        withDays ? `${c.last_visit} (${c.days_since}d ago)` : c.last_visit,
    ]);
}

function renderCustomers() {
    const c = data.customers;
    document.getElementById("customerNote").textContent = c.total
        ? `${intFmt.format(c.repeat)} of ${intFmt.format(c.total)} customers (${pct(c.repeat_rate)}) paid more than once in this range.`
        : "";
    const top = document.getElementById("topCustomers");
    if (c.top.length) {
        renderTable(top, ["Name", "Account", "Biller", "Visits", "Bills paid", "Last visit"], customerRows(c.top, false), [3, 4]);
    } else {
        emptyState(top, "No customers in this range.");
    }

    const rule = c.lapsed_rule;
    document.getElementById("lapsedNote").textContent =
        `Paid ${rule.min_visits}+ times but not in the last ${rule.after_days} days of this range` +
        (c.lapsed_total ? ` — ${intFmt.format(c.lapsed_total)} customers${c.lapsed_total > c.lapsed.length ? `, top ${c.lapsed.length} shown` : ""}.` : ".");
    const lapsed = document.getElementById("lapsedCustomers");
    if (c.lapsed.length) {
        renderTable(lapsed, ["Name", "Account", "Biller", "Visits", "Bills paid", "Last visit"], customerRows(c.lapsed, true), [3, 4]);
    } else {
        emptyState(lapsed, "No lapsed regulars in this range.");
    }
}

// --- Loading ---------------------------------------------------------------

function renderAll() {
    if (!data) return;
    renderKpis();
    renderTrend();
    renderBillers();
    renderLate();
    renderHeatmap();
    renderDayOfMonth();
    renderCustomers();
}

async function loadInsights() {
    const params = new URLSearchParams();
    if (els.from.value) params.set("from_date", els.from.value);
    if (els.to.value) params.set("to_date", els.to.value);
    if (els.biller.value) params.set("biller", els.biller.value);
    els.status.textContent = "Loading...";
    try {
        const response = await fetch(`/api/admin/insights?${params}`);
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            els.status.textContent = error.detail || "Could not load insights";
            return;
        }
        data = await response.json();
        const scope = data.range.biller ? ` for ${data.range.biller}` : "";
        els.status.textContent = `Showing ${data.range.from} to ${data.range.to}${scope}.`;
        renderAll();
    } catch (err) {
        els.status.textContent = "Could not load insights";
    }
}

function applyPreset(value) {
    const today = new Date();
    let from;
    let to = today;
    if (value === "ytd") from = new Date(today.getFullYear(), 0, 1);
    else if (value === "30" || value === "90") from = new Date(today.getTime() - (Number(value) - 1) * 86400000);
    else if (value === "month") from = new Date(today.getFullYear(), today.getMonth(), 1);
    else if (value === "lastmonth") {
        from = new Date(today.getFullYear(), today.getMonth() - 1, 1);
        to = new Date(today.getFullYear(), today.getMonth(), 0);
    } else return;
    els.from.value = isoDate(from);
    els.to.value = isoDate(to);
}

document.querySelectorAll(".seg-btn[data-measure]").forEach((btn) => {
    btn.addEventListener("click", () => {
        measure = btn.dataset.measure;
        document.querySelectorAll(".seg-btn[data-measure]").forEach((b) => b.classList.toggle("is-active", b === btn));
        renderTrend();
        renderBillers();
    });
});

els.preset.addEventListener("change", () => {
    applyPreset(els.preset.value);
    loadInsights();
});
[els.from, els.to].forEach((input) => input.addEventListener("change", () => {
    els.preset.value = "";
    loadInsights();
}));
els.biller.addEventListener("change", loadInsights);

let resizeTimer;
window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderAll, 150);
});

applyPreset("ytd");
loadInsights();
