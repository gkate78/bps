// Shared helpers (same input conventions as BPS: phone fields digits only, text uppercase).
function sanitizePhoneInput(el) {
    const digits = String(el.value || "").replace(/\D/g, "").slice(0, 11);
    if (el.value !== digits) el.value = digits;
}

function uppercaseTextInput(el) {
    const upper = String(el.value || "").toUpperCase();
    if (el.value !== upper) el.value = upper;
}

document.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;
    if (target instanceof HTMLInputElement && target.type === "tel") {
        sanitizePhoneInput(target);
        return;
    }
    if (target instanceof HTMLTextAreaElement || target.type === "text") {
        if (target.inputMode === "decimal" || target.inputMode === "numeric") return;
        uppercaseTextInput(target);
    }
});

// "1,234.50" -> 123450 centavos; null when blank or not a valid amount.
function toCents(text) {
    const cleaned = String(text || "").replace(/[,₱\s]/g, "");
    if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
    const [whole, frac = ""] = cleaned.split(".");
    return Number(whole) * 100 + Number((frac + "00").slice(0, 2));
}

function peso(cents) {
    const sign = cents < 0 ? "-" : "";
    const value = Math.abs(cents) / 100;
    return `${sign}₱${value.toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

async function postJson(url, body) {
    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    let data = {};
    try {
        data = await response.json();
    } catch (_) {
        // non-JSON error page
    }
    if (!response.ok) {
        let detail = data.detail;
        if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
        if (response.status === 401) detail = "Your session ended. Please sign in again.";
        throw new Error(detail || `Request failed (${response.status})`);
    }
    return data;
}

async function getJson(url) {
    const response = await fetch(url);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
}

// Type-ahead list under an input. fetchItems(query) -> items; render(item) -> html; onPick(item).
// Arrow keys move, Enter picks the highlighted item (otherwise Enter works as usual), Esc closes.
function attachSuggest(input, { fetchItems, render, onPick, minChars = 0 }) {
    const box = document.createElement("ul");
    box.className = "suggest";
    box.hidden = true;
    input.parentElement.classList.add("has-suggest");
    input.insertAdjacentElement("afterend", box);
    input.setAttribute("autocomplete", "off");
    let items = [];
    let active = -1;
    let seq = 0;
    let timer;

    function close() {
        box.hidden = true;
        active = -1;
    }

    function highlight(index) {
        active = index;
        box.querySelectorAll("li").forEach((li, i) => li.classList.toggle("on", i === active));
    }

    async function refresh() {
        const query = input.value.trim();
        if (query.length < minChars) return close();
        const mine = ++seq;
        try {
            const found = await fetchItems(query);
            if (mine !== seq || document.activeElement !== input) return;
            items = found;
            if (!items.length) return close();
            box.innerHTML = items.map((item, i) => `<li data-i="${i}">${render(item)}</li>`).join("");
            box.hidden = false;
            highlight(-1);
        } catch (_) {
            close();
        }
    }

    function pick(index) {
        const item = items[index];
        close();
        if (item) onPick(item);
    }

    input.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(refresh, 150);
    });
    input.addEventListener("focus", refresh);
    input.addEventListener("blur", () => setTimeout(close, 120));
    input.addEventListener("keydown", (event) => {
        if (box.hidden) return;
        if (event.key === "ArrowDown") {
            event.preventDefault();
            highlight(Math.min(active + 1, items.length - 1));
        } else if (event.key === "ArrowUp") {
            event.preventDefault();
            highlight(Math.max(active - 1, -1));
        } else if (event.key === "Enter" && active >= 0) {
            event.preventDefault();
            pick(active);
        } else if (event.key === "Escape") {
            close();
        }
    });
    box.addEventListener("mousedown", (event) => {
        const li = event.target.closest("li");
        if (!li) return;
        event.preventDefault();
        pick(Number(li.dataset.i));
    });
    return { close };
}

// Opens the receipt window during the click (so popup blockers allow it), then points it at the receipt.
function openReceiptWindow() {
    return window.open("about:blank", "receipt", "width=420,height=720");
}

function showReceipt(win, url) {
    if (win && !win.closed) {
        win.location = url;
        return true;
    }
    return false;
}

// Check a GCash/Maya reference no. while it's typed: warn(message) when it was used before,
// ok() when it's free or blank. The server refuses a used one again on save.
function warnIfReferenceUsed(input, warn, ok = () => {}) {
    let timer;
    async function check() {
        const reference = input.value.trim();
        if (!reference) return ok();
        try {
            const r = await getJson(`/pos/api/wallet-txns/claimed?reference=${encodeURIComponent(reference)}`);
            if (input.value.trim() !== reference) return; // typed on since; the next check decides
            if (r.claimed) warn(r.message);
            else ok();
        } catch (err) {
            /* checked again when saving */
        }
    }
    input.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(check, 400);
    });
    input.addEventListener("change", check);
}
