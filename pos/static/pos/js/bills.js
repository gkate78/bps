// Bills payment tab: several bills (any billers and accounts) paid together in one payment.
// Each bill is saved to the bills records like one from the entry form and prints its own receipt.
// register.js uses window.registerBills for tabs and parking.
(() => {
    const $ = (id) => document.getElementById(id);
    if (!$("tab-bills")) return;
    const notice = $("notice");
    const bills = [];
    let editingIndex = null;

    function say(message, kind = "success", html = false) {
        notice.className = `alert alert-${kind}`;
        if (html) notice.innerHTML = message;
        else notice.textContent = message;
        notice.hidden = false;
        if (kind === "error") notice.scrollIntoView({ block: "nearest" });
    }
    const hush = () => (notice.hidden = true);
    const escapeHtml = (text) =>
        String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
    const upper = (value) => String(value || "").trim().toUpperCase();
    const radio = (name) => document.querySelector(`input[name="${name}"]:checked`)?.value ?? "";
    const setRadio = (name, value) => {
        const el = document.querySelector(`input[name="${name}"][value="${CSS.escape(String(value ?? ""))}"]`);
        if (el) el.checked = true;
    };

    // Admin's own bills: "" (no), "paid" (no service charge) or "shop" (from shop funds, nothing collected).
    const personal = () => radio("b_personal");
    const payMethod = () => radio("b_pay") || "CASH";
    const METHOD_NAMES = { CASH: "Cash", GCASH: "GCash", MAYA: "Maya", BDO: "BDO", BPI: "BPI" };

    // ---------- One bill: charges from the server (same rules as the entry form) ----------
    let quoteSeq = 0;
    async function fetchQuote(bill, { openRule = false } = {}) {
        const params = new URLSearchParams({
            biller: bill.biller,
            account: bill.account,
            amount: bill.amount,
            personal: String(!!personal()),
        });
        if (bill.due_date) params.set("due_date", bill.due_date);
        const q = await getJson(`/pos/api/quote/bill?${params}`);
        if (q.needs_rule) {
            if (openRule) openRuleDialog(q.biller);
            throw new Error(`${q.biller} has no biller rule yet. Add its charges to continue.`);
        }
        return q;
    }

    function quoteText(q) {
        const parts = [`Bill ${peso(q.bill_cents)}`];
        if (q.late_charge_cents) parts.push(`late charge ${peso(q.late_charge_cents)}`);
        parts.push(q.charge_cents ? `service charge ${peso(q.charge_cents)}` : "no service charge");
        return `${escapeHtml(parts.join(" + "))} = <strong>${escapeHtml(peso(q.total_cents))}</strong>`;
    }

    function editorBill() {
        return {
            account: upper($("bAccount").value),
            biller: upper($("bBiller").value),
            customer_name: upper($("bName").value),
            cp_number: $("bPhone").value.trim(),
            due_date: $("bDue").value,
            amount: $("bAmount").value.trim(),
            payment_reference: upper($("bPayRef").value),
        };
    }

    async function updateQuote() {
        const bill = editorBill();
        const box = $("billQuote");
        if (!bill.biller || !bill.amount) {
            box.classList.remove("error");
            box.textContent = "Enter the biller and bill amount.";
            return;
        }
        const mine = ++quoteSeq;
        try {
            const q = await fetchQuote(bill);
            if (mine !== quoteSeq) return;
            box.classList.remove("error");
            box.innerHTML = quoteText(q);
        } catch (err) {
            if (mine !== quoteSeq) return;
            box.classList.add("error");
            box.textContent = err.message;
        }
    }
    let quoteTimer;
    const scheduleQuote = () => {
        clearTimeout(quoteTimer);
        quoteTimer = setTimeout(updateQuote, 250);
    };
    ["bBiller", "bAmount", "bDue", "bAccount"].forEach((id) => {
        $(id).addEventListener("input", scheduleQuote);
        $(id).addEventListener("change", scheduleQuote);
    });

    // ---------- Customer lookup (same as the entry form) ----------
    let accountsAbort = null;
    async function fetchKnownAccounts() {
        const biller = upper($("bBiller").value);
        const list = $("billAccountOptions");
        if (!biller) return list.replaceChildren();
        if (accountsAbort) accountsAbort.abort();
        accountsAbort = new AbortController();
        const params = new URLSearchParams({ biller, limit: "50" });
        if ($("bAccount").value.trim()) params.set("query", $("bAccount").value.trim());
        try {
            const response = await fetch(`/api/customers?${params}`, { signal: accountsAbort.signal });
            if (!response.ok) return;
            const data = await response.json();
            list.replaceChildren(
                ...(data.items || []).map((item) => {
                    const option = document.createElement("option");
                    option.value = item.account || "";
                    option.label = [item.customer_name, item.phone].filter(Boolean).join(" | ");
                    return option;
                }),
            );
        } catch (err) {
            /* suggestions only */
        }
    }
    let accountsTimer;
    ["bAccount", "bBiller"].forEach((id) =>
        $(id).addEventListener("input", () => {
            clearTimeout(accountsTimer);
            accountsTimer = setTimeout(fetchKnownAccounts, 250);
        }),
    );

    // Leaving the account field: a known account fills in its biller, name and phone.
    let lookedUp = "";
    $("bAccount").addEventListener("blur", async () => {
        const account = upper($("bAccount").value);
        if (!account || account === lookedUp) return;
        lookedUp = account;
        try {
            const response = await fetch(`/api/customers/lookup?${new URLSearchParams({ account })}`);
            if (!response.ok || upper($("bAccount").value) !== account) return;
            const data = await response.json();
            if (data.biller) $("bBiller").value = upper(data.biller);
            if (data.customer_name) $("bName").value = upper(data.customer_name);
            if (data.phone) $("bPhone").value = String(data.phone).replace(/\D/g, "").slice(0, 11);
            fetchKnownAccounts();
            updateQuote();
            if (!$("bDue").value) $("bDue").focus();
        } catch (err) {
            /* the cashier types the details */
        }
    });

    // ---------- List of bills ----------
    const billTotal = (bill) => bill.quote?.total_cents || 0;
    const listTotal = () => bills.reduce((sum, bill) => sum + billTotal(bill), 0);
    // Cash is collected to the whole peso per bill, as on the entry form and in End of day.
    const cashToCollect = () => bills.reduce((sum, bill) => sum + cashDue(billTotal(bill)), 0);

    function renderBills() {
        const body = $("billsBody");
        if (!bills.length) {
            body.innerHTML = '<tr class="empty"><td colspan="3">No bills yet. Add each bill on the left.</td></tr>';
        } else {
            body.innerHTML = bills
                .map((bill, i) => {
                    const q = bill.quote;
                    const charges = [
                        q.late_charge_cents ? `late ${peso(q.late_charge_cents)}` : "",
                        q.charge_cents ? `service ${peso(q.charge_cents)}` : "",
                    ].filter(Boolean);
                    const sub = `${bill.customer_name} · bill ${peso(q.bill_cents)}${charges.length ? ` + ${charges.join(" + ")}` : ""} · due ${bill.due_date}`;
                    return `<tr class="${i === editingIndex ? "editing" : ""}">
                        <td><strong>${escapeHtml(bill.biller)}</strong> ${escapeHtml(bill.account)}<div class="muted small">${escapeHtml(sub)}</div>${i === editingIndex ? '<div class="muted small">Editing…</div>' : ""}</td>
                        <td class="num">${escapeHtml(peso(q.total_cents))}</td>
                        <td class="line-actions"><button type="button" class="btn btn-ghost btn-small" data-edit="${i}" title="Edit" aria-label="Edit ${escapeHtml(bill.biller)}">✎</button><button type="button" class="btn btn-ghost btn-small" data-remove="${i}" title="Remove" aria-label="Remove ${escapeHtml(bill.biller)}">✕</button></td>
                    </tr>`;
                })
                .join("");
        }
        $("billsTotal").textContent = peso(listTotal());
        updatePayment();
    }

    function setEditing(index) {
        editingIndex = index;
        $("billSubmit").textContent = index === null ? "Add bill" : "Update bill";
        $("billCancel").hidden = index === null;
    }

    // Ready for the next bill; the same customer often pays several, so name and phone stay.
    function resetEditor({ keepCustomer = true } = {}) {
        ["bAccount", "bBiller", "bDue", "bAmount", "bPayRef"].forEach((id) => ($(id).value = ""));
        if (!keepCustomer) ["bName", "bPhone"].forEach((id) => ($(id).value = ""));
        lookedUp = "";
        $("billQuote").classList.remove("error");
        $("billQuote").textContent = "Enter the biller and bill amount.";
    }

    $("billEditor").addEventListener("submit", async (event) => {
        event.preventDefault();
        const bill = editorBill();
        if (!bill.account || !bill.biller || !bill.customer_name) return say("Enter the account, biller and customer name", "error");
        if (bill.cp_number && !/^\d{11}$/.test(bill.cp_number)) return say("CP number must be exactly 11 digits", "error");
        if (!bill.due_date) return say("Enter the due date", "error");
        if (!toCents(bill.amount)) return say("Enter the bill amount", "error");
        // Same account and amount is a duplicate (also against bills entered earlier this month, checked by the server).
        const twice = bills.findIndex((b, i) => i !== editingIndex && b.account === bill.account && toCents(b.amount) === toCents(bill.amount));
        if (twice >= 0) return say(`Duplicate: account ${bill.account} for ${peso(toCents(bill.amount))} is already in the list`, "error");
        $("billSubmit").disabled = true;
        try {
            bill.quote = await fetchQuote(bill, { openRule: true });
        } catch (err) {
            $("billQuote").classList.add("error");
            $("billQuote").textContent = err.message;
            return say(err.message, "error");
        } finally {
            $("billSubmit").disabled = false;
        }
        hush();
        if (editingIndex !== null) bills.splice(editingIndex, 1, bill);
        else bills.push(bill);
        setEditing(null);
        resetEditor();
        renderBills();
        $("bAccount").focus();
    });

    function editBill(index) {
        const bill = bills[index];
        hush();
        setEditing(index);
        $("bAccount").value = bill.account;
        $("bBiller").value = bill.biller;
        $("bName").value = bill.customer_name;
        $("bPhone").value = bill.cp_number;
        $("bDue").value = bill.due_date;
        $("bAmount").value = bill.amount;
        $("bPayRef").value = bill.payment_reference || "";
        lookedUp = bill.account; // don't overwrite the name typed for this bill
        updateQuote();
        renderBills();
        $("bAmount").focus();
    }
    $("billCancel").addEventListener("click", () => {
        setEditing(null);
        resetEditor();
        renderBills();
    });

    $("billsBody").addEventListener("click", (event) => {
        const edit = event.target.closest("[data-edit]");
        if (edit) return editBill(Number(edit.dataset.edit));
        const remove = event.target.closest("[data-remove]");
        if (!remove) return;
        const index = Number(remove.dataset.remove);
        if (index === editingIndex) {
            setEditing(null);
            resetEditor();
        } else if (editingIndex !== null && index < editingIndex) {
            editingIndex -= 1;
        }
        bills.splice(index, 1);
        if (!bills.length) return clear();
        renderBills();
    });

    // Enter moves to the next field (as on the entry form); on the last one it adds the bill.
    const EDITOR_ORDER = ["bAccount", "bBiller", "bName", "bPhone", "bDue", "bAmount", "bPayRef"];
    EDITOR_ORDER.forEach((id, i) =>
        $(id).addEventListener("keydown", (event) => {
            if (event.key !== "Enter" || i === EDITOR_ORDER.length - 1) return;
            event.preventDefault();
            $(EDITOR_ORDER[i + 1]).focus();
        }),
    );

    // Personal changes the service charge on every bill in the list.
    async function requoteAll() {
        for (const bill of bills) {
            try {
                bill.quote = await fetchQuote(bill);
            } catch (err) {
                say(`${bill.biller} ${bill.account}: ${err.message}`, "error");
            }
        }
        renderBills();
        updateQuote();
    }
    document.querySelectorAll('input[name="b_personal"]').forEach((el) => el.addEventListener("change", requoteAll));

    // ---------- Payment ----------
    function updatePayment() {
        const fromShop = personal() === "shop";
        const method = payMethod();
        const byCash = method === "CASH";
        $("billsPayField").hidden = fromShop;
        $("billsShopNote").hidden = !fromShop;
        $("billsCashBlock").hidden = fromShop || !byCash;
        $("billsRefBlock").hidden = fromShop || byCash;
        $("billsRefOptional").hidden = method === "GCASH" || method === "MAYA";
        if (!byCash) {
            $("billsRefHint").innerHTML =
                `Check that <strong>${escapeHtml(peso(listTotal()))}</strong> arrived in ${escapeHtml(METHOD_NAMES[method])}, then enter its reference no.`;
        }
        const due = cashToCollect();
        $("billsDue").textContent = peso(due);
        const cash = toCents($("bCash").value);
        const el = $("billsChange");
        if (cash === null || !due) {
            el.textContent = "₱0.00";
            el.classList.remove("short");
        } else {
            el.textContent = cash >= due ? peso(cash - due) : `Short ${peso(due - cash)}`;
            el.classList.toggle("short", cash < due);
        }
    }
    $("bCash").addEventListener("input", updatePayment);
    document.querySelectorAll('input[name="b_pay"]').forEach((el) =>
        el.addEventListener("change", () => {
            updatePayment();
            (payMethod() === "CASH" ? $("bCash") : $("bRef")).focus();
        }),
    );
    document.querySelectorAll('input[name="b_personal"]').forEach((el) => el.addEventListener("change", updatePayment));
    warnIfReferenceUsed($("bRef"), (message) => {
        if (payMethod() === "GCASH" || payMethod() === "MAYA") say(message, "error");
    });

    function clear() {
        bills.length = 0;
        setEditing(null);
        resetEditor({ keepCustomer: false });
        ["bCash", "bRef"].forEach((id) => ($(id).value = ""));
        setRadio("b_pay", "CASH");
        setRadio("b_personal", "");
        renderBills();
    }

    let saving = false;
    $("billsCheckout").addEventListener("submit", async (event) => {
        event.preventDefault();
        if (saving) return;
        if (editingIndex !== null) return say("Finish editing the bill first (Update bill or Cancel edit)", "error");
        if (!bills.length) return say("Add at least one bill", "error");
        const fromShop = personal() === "shop";
        const method = payMethod();
        if (!fromShop && method === "CASH") {
            const cash = toCents($("bCash").value);
            if (cash === null) return say("Enter the cash received", "error");
            if (cash < cashToCollect()) return say(`Cash received is less than the total (${peso(cashToCollect())})`, "error");
        }
        if (!fromShop && (method === "GCASH" || method === "MAYA") && !$("bRef").value.trim()) {
            return say(`Enter the ${METHOD_NAMES[method]} reference no.`, "error");
        }
        saving = true;
        $("saveBills").disabled = true;
        const win = openReceiptWindow();
        try {
            const result = await postJson("/pos/api/bills", {
                bills: bills.map(({ quote, amount, ...bill }) => ({ ...bill, bill_amt: amount })),
                payment_method: method,
                reference: method === "CASH" ? null : $("bRef").value,
                cash: method === "CASH" && !fromShop ? $("bCash").value : null,
                personal: personal() || null,
            });
            const url = `/api/receipts/bills?ids=${result.ids.join(",")}&autoprint=1`;
            const opened = showReceipt(win, url);
            const paid = fromShop
                ? "Personal, from shop funds."
                : method === "CASH"
                  ? `Change: <strong>${escapeHtml(peso(result.change_cents))}</strong>`
                  : `Paid via ${escapeHtml(METHOD_NAMES[method])}.`;
            say(
                `Saved ${result.count} bill${result.count === 1 ? "" : "s"} (${escapeHtml(result.references.join(", "))}). ${paid}` +
                    (opened ? "" : ` · <a href="${url}" target="receipt">Print receipts</a>`) +
                    ` · <button type="button" class="btn btn-secondary btn-small" id="billsShopSale">Shop sale for ${escapeHtml(result.customer_name)}</button>`,
                "success",
                true,
            );
            const customer = { name: result.customer_name, phone: result.cp_number };
            $("billsShopSale").addEventListener("click", () => {
                window.dispatchEvent(new CustomEvent("pos:shop-sale-for", { detail: customer }));
            });
            clear();
            loadMyBills();
        } catch (err) {
            if (win) win.close();
            say(err.message, "error");
        } finally {
            saving = false;
            $("saveBills").disabled = false;
        }
    });

    // ---------- Bills I entered today (reprint) ----------
    function timeOf(iso) {
        const at = new Date(iso);
        return Number.isNaN(at.getTime()) ? "" : at.toLocaleTimeString("en-PH", { hour: "numeric", minute: "2-digit" });
    }
    async function loadMyBills() {
        try {
            const data = await getJson("/api/records/mine");
            $("myBillsStatus").textContent = data.count
                ? `${data.count} bill${data.count === 1 ? "" : "s"}, ₱${Number(data.total).toLocaleString("en-PH", { minimumFractionDigits: 2 })} collected` +
                  (data.truncated ? ` (latest ${data.items.length} shown)` : "")
                : "None yet today.";
            $("myBillsBody").innerHTML = data.items
                .map(
                    (r) => `<tr>
                        <td>${escapeHtml(timeOf(r.txn_datetime))}</td>
                        <td><strong>${escapeHtml(r.biller)}</strong> ${escapeHtml(r.account)}<div class="muted small">${escapeHtml(r.reference || "")}</div></td>
                        <td>${escapeHtml(r.customer_name)}</td>
                        <td>${escapeHtml(r.payment_method || "-")}</td>
                        <td class="num">${escapeHtml(peso(Math.round(Number(r.total || 0) * 100)))}</td>
                        <td class="line-actions"><a class="btn btn-secondary btn-small" href="/api/records/${r.id}/receipt?copies=1" target="receipt">Reprint</a></td>
                    </tr>`,
                )
                .join("");
        } catch (err) {
            $("myBillsStatus").textContent = err.message;
        }
    }
    $("myBillsRefresh").addEventListener("click", loadMyBills);

    // ---------- New biller: add its rule without leaving the register ----------
    const ruleDialog = $("billerRuleDialog");
    let dismissedRule = "";
    function openRuleDialog(biller) {
        if (ruleDialog.open || biller === dismissedRule) return;
        $("ruleBiller").value = biller;
        $("ruleServiceCharge").value = "15";
        $("ruleLateCharge").value = "0";
        $("ruleAccountDigits").value = "";
        const typed = upper($("bAccount").value);
        $("ruleAccountFormat").value = /[A-Z]/.test(typed) ? "ALPHANUMERIC" : "NUMERIC";
        $("ruleAccountDigits").placeholder = typed ? `e.g. ${typed.length}` : "";
        $("billerRuleIntro").textContent = `${biller} has no rule yet. Add its charges to continue.`;
        $("billerRuleStatus").textContent = "";
        ruleDialog.showModal();
        $("ruleServiceCharge").select();
    }
    function closeRuleDialog() {
        dismissedRule = upper($("ruleBiller").value);
        ruleDialog.close();
    }
    $("billerRuleCancel").addEventListener("click", closeRuleDialog);
    ruleDialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        closeRuleDialog();
    });
    // Offer the rule as soon as an unknown biller is entered.
    $("bBiller").addEventListener("change", async () => {
        const biller = upper($("bBiller").value);
        if (!biller) return;
        try {
            const q = await getJson(`/pos/api/quote/bill?${new URLSearchParams({ biller, amount: "1" })}`);
            if (q.needs_rule && upper($("bBiller").value) === biller) openRuleDialog(biller);
        } catch (err) {
            /* shown by the quote */
        }
    });
    $("billerRuleForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        const biller = upper($("ruleBiller").value);
        const service = toCents($("ruleServiceCharge").value);
        const late = $("ruleLateCharge").value.trim() ? toCents($("ruleLateCharge").value) : 0;
        const digits = $("ruleAccountDigits").value.trim();
        if (!biller) return ($("billerRuleStatus").textContent = "Enter the biller name.");
        if (service === null || late === null) return ($("billerRuleStatus").textContent = "Charges must be zero or more.");
        if (digits && !/^[1-9]\d*$/.test(digits)) return ($("billerRuleStatus").textContent = "Account length must be a whole number above zero.");
        $("billerRuleSave").disabled = true;
        $("billerRuleStatus").textContent = "Saving…";
        try {
            const rule = await postJson("/api/biller-rules", {
                biller,
                service_charge: service / 100,
                late_charge: late / 100,
                account_digits: digits ? Number(digits) : null,
                account_format: $("ruleAccountFormat").value,
            });
            const list = $("billerOptions");
            if (![...list.options].some((o) => o.value === rule.biller)) {
                const option = document.createElement("option");
                option.value = rule.biller;
                list.appendChild(option);
            }
            $("bBiller").value = rule.biller;
            dismissedRule = "";
            ruleDialog.close();
            say(`Rule for ${rule.biller} saved.`);
            updateQuote();
            ($("bName").value ? $("bDue") : $("bName")).focus();
        } catch (err) {
            $("billerRuleStatus").textContent = err.message;
        } finally {
            $("billerRuleSave").disabled = false;
        }
    });

    // ---------- Parking (used by register.js) ----------
    const FIELDS = ["bCash", "bRef"];
    window.registerBills = {
        inProgress: () => bills.length > 0,
        parking() {
            const billers = [...new Set(bills.map((b) => b.biller))];
            return {
                kind: "bills",
                label: bills[0]?.customer_name || "",
                summary: `${bills.length} bill${bills.length === 1 ? "" : "s"}: ${billers.join(", ")}`,
                total_cents: listTotal(),
                data: {
                    bills: bills.slice(),
                    fields: Object.fromEntries(FIELDS.map((id) => [id, $(id).value])),
                    pay: payMethod(),
                    personal: personal(),
                },
            };
        },
        async restore(data) {
            clear();
            bills.push(...(data.bills || []));
            Object.entries(data.fields || {}).forEach(([id, value]) => $(id) && ($(id).value = value ?? ""));
            setRadio("b_pay", data.pay || "CASH");
            if (data.personal) setRadio("b_personal", data.personal);
            renderBills();
            if ($("bRef").value) $("bRef").dispatchEvent(new Event("change")); // a resumed reference is checked too
            // Charges may have changed since it was parked (a new day, an updated rule).
            await requoteAll();
        },
        clear,
        focus: () => $("bAccount").focus(),
        shown: loadMyBills,
    };

    renderBills();
})();
