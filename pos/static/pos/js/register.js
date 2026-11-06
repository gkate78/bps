(() => {
    const $ = (id) => document.getElementById(id);
    const notice = $("notice");
    const cart = [];

    function say(message, kind = "success", html = false) {
        notice.className = `alert alert-${kind}`;
        if (html) notice.innerHTML = message;
        else notice.textContent = message;
        notice.hidden = false;
        if (kind === "error") notice.scrollIntoView({ block: "nearest" });
    }

    function hush() {
        notice.hidden = true;
    }

    function escapeHtml(text) {
        return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
    }

    function debounce(fn, ms = 200) {
        let timer;
        return (...args) => {
            clearTimeout(timer);
            timer = setTimeout(() => fn(...args), ms);
        };
    }

    // ---------- Tabs ----------
    function showTab(name) {
        document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === name));
        $("tab-shop").hidden = name !== "shop";
        $("tab-wallet").hidden = name !== "wallet";
    }
    document.querySelectorAll(".tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            showTab(tab.dataset.tab);
            hush();
            if (tab.dataset.tab === "wallet") $("wAmount").focus();
        });
    });

    // ---------- Shop sale ----------
    let currentService = null;

    // Admin's own sale: "" (no), "paid" or "shop" (from shop funds). Loads have no fee; no job order.
    const personal = () => document.querySelector('input[name="personal"]:checked')?.value || "";

    function showEditor(which) {
        $("serviceEditor").hidden = which !== "service";
        $("loadEditor").hidden = which !== "load";
        document.querySelectorAll(".svc-btn").forEach((b) => b.classList.remove("on"));
    }

    document.querySelectorAll(".svc-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            hush();
            if (btn.dataset.load) {
                showEditor("load");
                btn.classList.add("on");
                const checked = document.querySelector('input[name="network"]:checked');
                (checked ? $("loadMobile") : document.querySelector('input[name="network"]'))?.focus();
                return;
            }
            currentService = { id: Number(btn.dataset.serviceId), name: btn.dataset.name };
            showEditor("service");
            btn.classList.add("on");
            $("serviceEditorTitle").textContent = currentService.name;
            $("svcDesc").value = "";
            $("svcQty").value = "1";
            $("svcPrice").value = "";
            $("svcDesc").focus();
        });
    });

    $("serviceEditor").addEventListener("submit", (event) => {
        event.preventDefault();
        if (!currentService) return;
        const qty = Number($("svcQty").value);
        const price = toCents($("svcPrice").value);
        if (!Number.isInteger(qty) || qty < 1 || qty > 10000) return say("Quantity must be a whole number from 1 to 10,000", "error");
        if (price === null || (!price && !personal())) return say("Enter the price", "error");
        hush();
        cart.push({
            kind: "service",
            service_id: currentService.id,
            name: currentService.name,
            description: $("svcDesc").value.trim(),
            qty,
            unit_price: $("svcPrice").value,
            total_cents: price * qty,
        });
        renderCart();
        $("svcDesc").value = "";
        $("svcQty").value = "1";
        $("svcPrice").value = "";
        $("svcDesc").focus();
    });

    async function fetchLoadQuote() {
        const amount = $("loadAmount").value.trim();
        if (!amount) {
            $("loadQuote").textContent = "Enter the load amount.";
            return null;
        }
        try {
            const promo = $("loadPromo").checked;
            const wallet = document.querySelector('input[name="load_wallet"]:checked');
            const q = await getJson(
                `/pos/api/quote/load?amount=${encodeURIComponent(amount)}&promo=${promo}&personal=${!!personal()}` +
                    (wallet ? `&wallet_id=${wallet.value}` : ""),
            );
            const base = q.priced_cents !== q.load_cents ? `${peso(q.load_cents)} promo → ${peso(q.priced_cents)}` : peso(q.load_cents);
            const deducts = wallet && q.cost_cents !== q.load_cents ? ` · ${wallet.dataset.name} deducts about ${peso(q.cost_cents)}` : "";
            $("loadQuote").innerHTML =
                `${escapeHtml(base)} + ${escapeHtml(peso(q.fee_cents))} fee = <strong>${escapeHtml(peso(q.total_cents))}</strong>` +
                `<span class="muted">${escapeHtml(deducts)}</span>`;
            $("loadDeducted").placeholder = (q.cost_cents / 100).toFixed(2);
            return q;
        } catch (err) {
            $("loadQuote").textContent = err.message;
            return null;
        }
    }
    const updateLoadQuote = debounce(fetchLoadQuote);
    $("loadAmount").addEventListener("input", updateLoadQuote);
    $("loadPromo").addEventListener("change", updateLoadQuote);
    document.querySelectorAll('input[name="load_wallet"]').forEach((el) => el.addEventListener("change", updateLoadQuote));

    $("loadEditor").addEventListener("submit", async (event) => {
        event.preventDefault();
        const network = document.querySelector('input[name="network"]:checked');
        const wallet = document.querySelector('input[name="load_wallet"]:checked');
        const mobile = $("loadMobile").value;
        if (!network) return say("Choose the network", "error");
        if (!wallet) return say("Choose where the load is sent from", "error");
        if (!/^09\d{9}$/.test(mobile)) return say("Mobile no. must be 11 digits starting with 09", "error");
        const q = await fetchLoadQuote();
        if (!q) return say($("loadQuote").textContent || "Check the load amount", "error");
        const deducted = $("loadDeducted").value.trim() ? toCents($("loadDeducted").value) : null;
        if ($("loadDeducted").value.trim() && (!deducted || deducted > q.load_cents)) {
            return say(`Amount ${wallet.dataset.name} deducted must be more than zero and not more than the load`, "error");
        }
        hush();
        cart.push({
            kind: "load",
            name: `LOAD ${network.dataset.name}`,
            description: $("loadDesc").value.trim(),
            qty: 1,
            network_id: Number(network.value),
            wallet_id: Number(wallet.value),
            wallet_name: wallet.dataset.name,
            mobile_no: mobile,
            amount: $("loadAmount").value,
            is_promo: $("loadPromo").checked,
            deducted: $("loadDeducted").value.trim(),
            reference: $("loadRef").value.trim(),
            total_cents: q.total_cents,
            load_cents: q.load_cents,
            cost_cents: deducted ?? q.cost_cents,
        });
        renderCart();
        ["loadMobile", "loadAmount", "loadDesc", "loadRef", "loadDeducted"].forEach((id) => ($(id).value = ""));
        $("loadDeducted").placeholder = "";
        $("loadPromo").checked = false;
        $("loadQuote").textContent = "Enter the load amount.";
        $("loadMobile").focus();
    });

    // A personal sale's load costs only the load amount; the server prices it the same way.
    function lineTotal(line) {
        return line.kind === "load" && personal() && line.load_cents ? line.load_cents : line.total_cents;
    }

    function loadDetail(line) {
        if (!line.load_cents) return line.detail || ""; // parked before personal sales existed
        const fee = lineTotal(line) - line.load_cents;
        const promo = line.is_promo && !personal() ? " promo" : "";
        return (
            `${line.mobile_no} · ${peso(line.load_cents)}${promo}${fee ? ` + ${peso(fee)} fee` : personal() ? ", no fee" : ""}` +
            ` via ${line.wallet_name} (deducts ${peso(line.cost_cents)})`
        );
    }

    function cartTotal() {
        return cart.reduce((sum, line) => sum + lineTotal(line), 0);
    }

    function renderCart() {
        const body = $("cartBody");
        if (!cart.length) {
            body.innerHTML = '<tr class="empty"><td colspan="4">No items yet. Tap a service or LOAD.</td></tr>';
        } else {
            body.innerHTML = cart
                .map((line, i) => {
                    const sub = line.kind === "load" ? loadDetail(line) : line.qty > 1 ? `${peso(toCents(line.unit_price))} each` : "";
                    const desc = line.description ? ` · ${line.description}` : "";
                    return `<tr>
                        <td><strong>${escapeHtml(line.name)}</strong>${escapeHtml(desc)}${sub ? `<div class="muted small">${escapeHtml(sub)}</div>` : ""}</td>
                        <td class="num">${line.qty}</td>
                        <td class="num">${escapeHtml(peso(lineTotal(line)))}</td>
                        <td><button type="button" class="btn btn-ghost btn-small" data-remove="${i}" aria-label="Remove">✕</button></td>
                    </tr>`;
                })
                .join("");
        }
        $("cartTotal").textContent = peso(cartTotal());
        updateJob();
        updateChange();
        updatePayment();
    }

    $("cartBody").addEventListener("click", (event) => {
        const btn = event.target.closest("[data-remove]");
        if (!btn) return;
        cart.splice(Number(btn.dataset.remove), 1);
        renderCart();
    });

    // What the customer pays now: the total, or only the down payment for a job order.
    const isJob = () => $("isJob").checked;
    function dueNow() {
        if (!isJob()) return cartTotal();
        return toCents($("downPayment").value) || 0;
    }

    function updateJob() {
        $("jobBlock").hidden = !isJob();
        const down = toCents($("downPayment").value) || 0;
        $("jobBalance").textContent = peso(Math.max(cartTotal() - down, 0));
    }
    $("isJob").addEventListener("change", () => {
        updateJob();
        renderCart();
        if (isJob()) {
            document.querySelector("#checkoutForm details").open = true;
            ($("custName").value ? $("downPayment") : $("custName")).focus();
        }
    });
    $("downPayment").addEventListener("input", () => {
        updateJob();
        updateChange();
        updatePayment();
    });

    function updateChange() {
        const cash = toCents($("cashIn").value);
        const total = dueNow();
        const el = $("cartChange");
        if (cash === null || !total) {
            el.textContent = "₱0.00";
            el.classList.remove("short");
            return;
        }
        el.textContent = cash >= total ? peso(cash - total) : `Short ${peso(total - cash)}`;
        el.classList.toggle("short", cash < total);
    }
    $("cashIn").addEventListener("input", updateChange);

    // Paid with: cash (cash received/change) or the shop's GCash/Maya (reference no., no change).
    const payChoice = () => document.querySelector('input[name="pay"]:checked');

    function updatePayment() {
        const choice = payChoice();
        const byWallet = choice.value !== "cash";
        const fromShop = personal() === "shop";
        $("payField").hidden = fromShop;
        $("shopFundsNote").hidden = !fromShop;
        $("cashBlock").hidden = byWallet || fromShop;
        $("walletPayBlock").hidden = !byWallet || fromShop;
        if (byWallet) {
            $("walletPayHint").innerHTML =
                `Check that <strong>${escapeHtml(peso(dueNow()))}</strong> arrived in ${escapeHtml(choice.dataset.name)}, then enter its reference no.`;
        }
    }
    document.querySelectorAll('input[name="pay"]').forEach((el) =>
        el.addEventListener("change", () => {
            updatePayment();
            (payChoice().value === "cash" ? $("cashIn") : $("payRef")).focus();
        }),
    );

    function updatePersonal() {
        if (personal()) $("isJob").checked = false;
        $("jobField").hidden = !!personal();
        renderCart();
        if ($("loadAmount").value.trim()) updateLoadQuote();
    }
    document.querySelectorAll('input[name="personal"]').forEach((el) => el.addEventListener("change", updatePersonal));

    function clearSale() {
        cart.length = 0;
        setRadio("personal", "");
        if ($("jobField")) $("jobField").hidden = false;
        ["cashIn", "payRef", "custName", "custPhone", "birNo", "downPayment", "promisedDate"].forEach((id) => ($(id).value = ""));
        document.querySelector('input[name="pay"][value="cash"]').checked = true;
        $("isJob").checked = false;
        renderCart();
    }
    $("clearSale").addEventListener("click", () => {
        if (cart.length && !confirm("Clear this sale?")) return;
        clearSale();
        hush();
    });

    let saving = false;
    $("checkoutForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        if (saving) return;
        if (!cart.length) return say("Add at least one item", "error");
        const pay = payChoice();
        const fromShop = personal() === "shop";
        const byWallet = pay.value !== "cash" && !fromShop;
        if (isJob()) {
            if (cart.some((line) => line.kind === "load")) return say("Load can't be in a job order. Ring it up as a separate sale.", "error");
            if (!$("custName").value.trim()) return say("Enter the customer's name for a job order", "error");
            const down = toCents($("downPayment").value);
            if (!down || down >= cartTotal()) return say("Down payment must be more than zero and less than the total", "error");
        }
        if (fromShop) {
            // Nothing to collect.
        } else if (byWallet) {
            if (!$("payRef").value.trim()) return say(`Enter the ${pay.dataset.name} reference no.`, "error");
        } else {
            const cash = toCents($("cashIn").value);
            if (cash === null) return say("Enter the cash received", "error");
            if (cash < dueNow()) return say(`Cash received is less than ${isJob() ? "the down payment" : "the total"}`, "error");
        }
        saving = true;
        $("saveSale").disabled = true;
        const win = openReceiptWindow();
        try {
            const result = await postJson("/pos/api/sales", {
                lines: cart.map(({ total_cents, name, detail, wallet_name, load_cents, cost_cents, ...line }) => line),
                payment_method: byWallet ? "wallet" : "cash",
                pay_wallet_id: byWallet ? Number(pay.value) : null,
                payment_reference: byWallet ? $("payRef").value : null,
                cash: byWallet || fromShop ? null : $("cashIn").value,
                personal: personal() || null,
                customer_name: $("custName").value,
                customer_phone: $("custPhone").value,
                bir_invoice_no: $("birNo").value,
                is_job_order: isJob(),
                down_payment: isJob() ? $("downPayment").value : null,
                promised_date: isJob() && $("promisedDate").value ? $("promisedDate").value : null,
            });
            const url = `/pos/receipt/sale/${result.id}?autoprint=1`;
            const opened = showReceipt(win, url);
            say(
                `Saved ${escapeHtml(result.sale_no)}${result.balance_cents ? ` (job order, balance ${escapeHtml(peso(result.balance_cents))})` : ""}. ` +
                    (fromShop
                        ? "Personal, from shop funds."
                        : byWallet
                          ? `Paid via ${escapeHtml(pay.dataset.name)}.`
                          : `Change: <strong>${escapeHtml(peso(result.change_cents))}</strong>`) +
                    (opened ? "" : ` · <a href="${url}" target="receipt">Print receipt</a>`),
                "success",
                true,
            );
            clearSale();
            showEditor(null);
        } catch (err) {
            if (win) win.close();
            say(err.message, "error");
        } finally {
            saving = false;
            $("saveSale").disabled = false;
        }
    });

    // ---------- GCash / Maya ----------
    let walletQuote = null;

    const walletKind = () => document.querySelector('input[name="kind"]:checked').value;
    const feeMode = () => document.querySelector('input[name="fee_mode"]:checked').value;
    const walletChoice = () => document.querySelector('input[name="wallet"]:checked');
    const wPersonal = () => document.querySelector('input[name="w_personal"]:checked')?.value || "";

    async function fetchWalletQuote() {
        const kind = walletKind();
        $("feeModeField").hidden = kind !== "cash_out" || !!wPersonal();
        const amount = $("wAmount").value.trim();
        walletQuote = null;
        if (!amount) {
            $("walletQuote").textContent = "Enter the amount.";
            updateWalletChange();
            return null;
        }
        try {
            const q = await getJson(
                `/pos/api/quote/wallet?kind=${kind}&amount=${encodeURIComponent(amount)}&fee_mode=${feeMode()}&personal=${wPersonal()}`,
            );
            walletQuote = q;
            const wallet = walletChoice()?.parentElement.textContent.trim() || "";
            const mobile = $("wMobile").value || "the customer";
            let steps;
            if (wPersonal() && kind === "cash_in") {
                steps = [
                    q.collect_cents
                        ? `Collect <strong>${peso(q.collect_cents)}</strong> cash (personal, no fee)`
                        : "Nothing to collect: personal, from shop funds",
                    `Send <strong>${peso(q.amount_cents)}</strong> from ${escapeHtml(wallet)} to ${escapeHtml(mobile)}`,
                ];
            } else if (wPersonal()) {
                steps = [
                    `Confirm <strong>${peso(q.amount_cents)}</strong> received in ${escapeHtml(wallet)}`,
                    `Give <strong>${peso(q.give_cents)}</strong> cash (personal, no fee)`,
                ];
            } else if (kind === "cash_in") {
                steps = [
                    `Collect <strong>${peso(q.collect_cents)}</strong> cash (${peso(q.amount_cents)} + ${peso(q.fee_cents)} fee)`,
                    `Send <strong>${peso(q.amount_cents)}</strong> from ${escapeHtml(wallet)} to ${escapeHtml(mobile)}`,
                ];
            } else if (feeMode() === "included") {
                steps = [
                    `Confirm <strong>${peso(q.amount_cents)}</strong> received in ${escapeHtml(wallet)}`,
                    `Give <strong>${peso(q.give_cents)}</strong> cash (fee ${peso(q.fee_cents)} included in what was sent)`,
                ];
            } else if (feeMode() === "paid_in_cash") {
                steps = [
                    `Confirm <strong>${peso(q.amount_cents)}</strong> received in ${escapeHtml(wallet)}`,
                    `Collect <strong>${peso(q.fee_cents)}</strong> fee in cash`,
                    `Give <strong>${peso(q.give_cents)}</strong> cash`,
                ];
            } else {
                steps = [
                    `Confirm <strong>${peso(q.amount_cents)}</strong> received in ${escapeHtml(wallet)}`,
                    `Give <strong>${peso(q.give_cents)}</strong> cash (${peso(q.amount_cents)} − ${peso(q.fee_cents)} fee)`,
                ];
            }
            $("walletQuote").innerHTML = `<ol>${steps.map((s) => `<li>${s}</li>`).join("")}</ol>`;
        } catch (err) {
            $("walletQuote").textContent = err.message;
        }
        updateWalletChange();
        return walletQuote;
    }
    const updateWalletQuote = debounce(fetchWalletQuote);
    $("wAmount").addEventListener("input", updateWalletQuote);
    $("wMobile").addEventListener("input", updateWalletQuote);
    document.querySelectorAll('input[name="kind"], input[name="fee_mode"], input[name="wallet"], input[name="w_personal"]').forEach((el) =>
        el.addEventListener("change", fetchWalletQuote),
    );

    function updateWalletChange() {
        const collect = walletQuote ? walletQuote.collect_cents : 0;
        $("wCashBlock").hidden = !!walletQuote && collect === 0;
        const tendered = toCents($("wTendered").value);
        const el = $("wChange");
        if (!walletQuote || tendered === null) {
            el.textContent = "₱0.00";
            el.classList.remove("short");
            return;
        }
        el.textContent = tendered >= collect ? peso(tendered - collect) : `Short ${peso(collect - tendered)}`;
        el.classList.toggle("short", tendered < collect);
    }
    $("wTendered").addEventListener("input", updateWalletChange);

    function clearWallet() {
        ["wAmount", "wMobile", "wRef", "wName", "wTendered"].forEach((id) => ($(id).value = ""));
        setRadio("w_personal", "");
        walletQuote = null;
        $("walletQuote").textContent = "Enter the amount.";
        updateWalletChange();
    }
    $("clearWallet").addEventListener("click", () => {
        clearWallet();
        hush();
    });

    let savingWallet = false;
    $("saveWallet").addEventListener("click", async () => {
        if (savingWallet) return;
        const q = await fetchWalletQuote();
        if (!q) return say($("walletQuote").textContent || "Check the amount", "error");
        if (!/^09\d{9}$/.test($("wMobile").value)) return say("Customer mobile no. must be 11 digits starting with 09", "error");
        if (!$("wRef").value.trim()) return say("Enter the reference no.", "error");
        savingWallet = true;
        $("saveWallet").disabled = true;
        const win = openReceiptWindow();
        try {
            const result = await postJson("/pos/api/wallet-txns", {
                kind: walletKind(),
                wallet_id: Number(walletChoice().value),
                amount: $("wAmount").value,
                fee_mode: feeMode(),
                customer_mobile: $("wMobile").value,
                customer_name: $("wName").value,
                reference: $("wRef").value,
                tendered: $("wTendered").value,
                personal: wPersonal() || null,
            });
            const url = `/pos/receipt/wallet/${result.id}?autoprint=1`;
            const opened = showReceipt(win, url);
            const parts = [`Saved ${escapeHtml(result.txn_no)}.`];
            if (result.give_cents) parts.push(`Give: <strong>${escapeHtml(peso(result.give_cents))}</strong>`);
            if (result.change_cents) parts.push(`Change: <strong>${escapeHtml(peso(result.change_cents))}</strong>`);
            if (!opened) parts.push(`<a href="${url}" target="receipt">Print receipt</a>`);
            say(parts.join(" · "), "success", true);
            clearWallet();
        } catch (err) {
            if (win) win.close();
            say(err.message, "error");
        } finally {
            savingWallet = false;
            $("saveWallet").disabled = false;
        }
    });

    $("wRef").addEventListener("keydown", (event) => {
        if (event.key === "Enter") $("saveWallet").click();
    });
    $("walletForm").addEventListener("submit", (event) => event.preventDefault());

    // ---------- Parked: on hold, not paid, while another customer is served ----------
    const SALE_FIELDS = ["custName", "custPhone", "birNo", "downPayment", "promisedDate", "cashIn", "payRef"];
    const WALLET_FIELDS = ["wAmount", "wMobile", "wRef", "wName", "wTendered"];
    const radio = (name) => document.querySelector(`input[name="${name}"]:checked`)?.value ?? null;
    const setRadio = (name, value) => {
        const el = value !== null && document.querySelector(`input[name="${name}"][value="${CSS.escape(String(value))}"]`);
        if (el) el.checked = true;
    };
    const readFields = (ids) => Object.fromEntries(ids.map((id) => [id, $(id).value]));
    const fillFields = (values) => Object.entries(values || {}).forEach(([id, value]) => $(id) && ($(id).value = value ?? ""));

    const saleInProgress = () => cart.length > 0;
    const walletInProgress = () => WALLET_FIELDS.some((id) => $(id).value.trim());

    function saleParking() {
        const names = {};
        cart.forEach((line) => (names[line.name] = (names[line.name] || 0) + line.qty));
        return {
            kind: "sale",
            label: $("custName").value.trim(),
            summary: Object.entries(names).map(([name, qty]) => (qty > 1 ? `${name} ×${qty}` : name)).join(", "),
            total_cents: cartTotal(),
            data: { cart: cart.slice(), fields: readFields(SALE_FIELDS), isJob: isJob(), pay: radio("pay"), personal: personal() },
        };
    }

    function walletParking() {
        const wallet = walletChoice()?.parentElement.textContent.trim() || "";
        const kind = walletKind() === "cash_in" ? "CASH-IN" : "CASH-OUT";
        return {
            kind: "wallet",
            label: $("wName").value.trim() || $("wMobile").value,
            summary: `${wallet} ${kind}${$("wName").value.trim() && $("wMobile").value ? ` · ${$("wMobile").value}` : ""}`,
            total_cents: toCents($("wAmount").value) || 0,
            data: { fields: readFields(WALLET_FIELDS), kind: walletKind(), wallet: radio("wallet"), fee_mode: feeMode(), personal: wPersonal() },
        };
    }

    function restore(item) {
        const data = item.data || {};
        if (item.kind === "sale") {
            clearSale();
            showEditor(null);
            cart.push(...(data.cart || []));
            fillFields(data.fields);
            $("isJob").checked = !!data.isJob;
            setRadio("pay", data.pay);
            if (data.personal) {
                setRadio("personal", data.personal);
                $("jobField").hidden = true;
            }
            if (data.fields?.custName || data.fields?.custPhone || data.fields?.birNo || data.isJob) {
                document.querySelector("#checkoutForm details").open = true;
            }
            renderCart();
            showTab("shop");
        } else {
            clearWallet();
            setRadio("kind", data.kind);
            setRadio("wallet", data.wallet);
            setRadio("fee_mode", data.fee_mode);
            if (data.personal) setRadio("w_personal", data.personal);
            fillFields(data.fields);
            showTab("wallet");
            fetchWalletQuote();
        }
    }

    function parkedTime(iso) {
        const at = new Date(iso);
        const time = at.toLocaleTimeString("en-PH", { hour: "numeric", minute: "2-digit" });
        return at.toDateString() === new Date().toDateString() ? time : `${at.toLocaleDateString("en-PH", { month: "short", day: "numeric" })} ${time}`;
    }

    async function loadParked() {
        let items;
        try {
            items = await getJson("/pos/api/parked");
        } catch (_) {
            return;
        }
        $("parkedBar").hidden = !items.length;
        $("parkedList").innerHTML = items
            .map(
                (p) => `<li>
                    <span class="who"><strong>${escapeHtml(p.label)}</strong><span class="muted small">${escapeHtml(p.summary)} · ${escapeHtml(parkedTime(p.parked_at))}</span></span>
                    <span class="amt">${escapeHtml(peso(p.total_cents))}</span>
                    <button type="button" class="btn btn-primary btn-small" data-resume="${p.id}" data-kind="${p.kind}">Resume</button>
                    <button type="button" class="btn btn-ghost btn-small" data-discard="${p.id}" data-label="${escapeHtml(p.label)}" aria-label="Discard">✕</button>
                </li>`,
            )
            .join("");
    }

    async function park(which) {
        const body = which === "sale" ? saleParking() : walletParking();
        const result = await postJson("/pos/api/parked", body);
        if (which === "sale") {
            clearSale();
            showEditor(null);
        } else {
            clearWallet();
        }
        return result;
    }

    $("parkSale").addEventListener("click", async () => {
        if (!saleInProgress()) return say("Nothing to park yet. Add an item first.", "error");
        try {
            const result = await park("sale");
            say(`Parked ${result.label}. Ready for the next customer.`);
        } catch (err) {
            say(err.message, "error");
        }
        loadParked();
    });

    $("parkWallet").addEventListener("click", async () => {
        if (!walletInProgress()) return say("Nothing to park yet. Enter the amount first.", "error");
        try {
            const result = await park("wallet");
            say(`Parked ${result.label}. Ready for the next customer.`);
        } catch (err) {
            say(err.message, "error");
        }
        loadParked();
    });

    $("parkedList").addEventListener("click", async (event) => {
        const resume = event.target.closest("[data-resume]");
        const discard = event.target.closest("[data-discard]");
        if (discard) {
            if (!confirm(`Discard the parked transaction for ${discard.dataset.label}? It was not paid.`)) return;
            await postJson(`/pos/api/parked/${discard.dataset.discard}/discard`, {}).catch((err) => say(err.message, "error"));
            return loadParked();
        }
        if (!resume) return;
        resume.disabled = true;
        try {
            // Whatever is on the screen of the same kind goes on hold in its place.
            const { resume: id, kind } = resume.dataset;
            let swapped = null;
            if (kind === "sale" && saleInProgress()) swapped = await park("sale");
            if (kind === "wallet" && walletInProgress()) swapped = await park("wallet");
            const item = await postJson(`/pos/api/parked/${id}/resume`, {});
            restore(item);
            say(`Resumed ${item.label}.${swapped ? ` ${swapped.label} was parked.` : ""}`);
        } catch (err) {
            say(err.message, "error");
        }
        loadParked();
    });

    loadParked();
    window.addEventListener("focus", loadParked);
    setInterval(loadParked, 30000);

    // Coming from a bill ("Next: Shop sale"): fill in the customer, nothing else.
    const fromBill = new URLSearchParams(window.location.search);
    if (fromBill.get("customer_name") || fromBill.get("customer_phone")) {
        $("custName").value = (fromBill.get("customer_name") || "").toUpperCase();
        $("custPhone").value = (fromBill.get("customer_phone") || "").replace(/\D/g, "").slice(0, 11);
        document.querySelector("#checkoutForm details").open = true;
        history.replaceState(null, "", "/pos");
    }

    // ---------- Suggestions from past transactions ----------
    const pesoInput = (cents) => (cents % 100 ? (cents / 100).toFixed(2) : String(cents / 100));
    const networkNames = {};
    document.querySelectorAll('input[name="network"]').forEach((el) => (networkNames[el.value] = el.dataset.name));

    attachSuggest($("svcDesc"), {
        fetchItems: (q) => getJson(`/pos/api/suggest/service?service_id=${currentService.id}&q=${encodeURIComponent(q)}`),
        render: (s) => `<strong>${escapeHtml(s.description)}</strong><span class="muted">${escapeHtml(peso(s.price_cents))}</span>`,
        onPick: (s) => {
            $("svcDesc").value = s.description;
            $("svcPrice").value = pesoInput(s.price_cents);
            $("svcQty").focus();
            $("svcQty").select();
        },
    });

    const mobileFetch = (q) => getJson(`/pos/api/suggest/mobile?q=${encodeURIComponent(q)}`);
    const mobileRender = (m) => {
        const extra = [m.name, networkNames[m.network_id]].filter(Boolean).join(" · ");
        return `<strong>${escapeHtml(m.mobile)}</strong><span class="muted">${escapeHtml(extra)}</span>`;
    };

    attachSuggest($("loadMobile"), {
        minChars: 3,
        fetchItems: mobileFetch,
        render: mobileRender,
        onPick: (m) => {
            $("loadMobile").value = m.mobile;
            const network = m.network_id && document.querySelector(`input[name="network"][value="${m.network_id}"]`);
            if (network) network.checked = true;
            $("loadAmount").focus();
        },
    });

    attachSuggest($("wMobile"), {
        minChars: 3,
        fetchItems: mobileFetch,
        render: mobileRender,
        onPick: (m) => {
            $("wMobile").value = m.mobile;
            if (m.name && !$("wName").value) $("wName").value = m.name;
            fetchWalletQuote();
            $("wRef").focus();
        },
    });

    attachSuggest($("custPhone"), {
        minChars: 3,
        fetchItems: mobileFetch,
        render: mobileRender,
        onPick: (m) => {
            $("custPhone").value = m.mobile;
            if (m.name && !$("custName").value) $("custName").value = m.name;
        },
    });
})();
