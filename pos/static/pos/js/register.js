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
    document.querySelectorAll(".tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t === tab));
            $("tab-shop").hidden = tab.dataset.tab !== "shop";
            $("tab-wallet").hidden = tab.dataset.tab !== "wallet";
            hush();
            if (tab.dataset.tab === "wallet") $("wAmount").focus();
        });
    });

    // ---------- Shop sale ----------
    let currentService = null;

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
        if (!price) return say("Enter the price", "error");
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
            const q = await getJson(`/pos/api/quote/load?amount=${encodeURIComponent(amount)}&promo=${promo}`);
            const base = q.priced_cents !== q.load_cents ? `${peso(q.load_cents)} promo → ${peso(q.priced_cents)}` : peso(q.load_cents);
            $("loadQuote").innerHTML = `${escapeHtml(base)} + ${escapeHtml(peso(q.fee_cents))} fee = <strong>${escapeHtml(peso(q.total_cents))}</strong>`;
            return q;
        } catch (err) {
            $("loadQuote").textContent = err.message;
            return null;
        }
    }
    const updateLoadQuote = debounce(fetchLoadQuote);
    $("loadAmount").addEventListener("input", updateLoadQuote);
    $("loadPromo").addEventListener("change", updateLoadQuote);

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
            reference: $("loadRef").value.trim(),
            total_cents: q.total_cents,
            detail: `${mobile} · ${peso(q.load_cents)}${$("loadPromo").checked ? " promo" : ""} + ${peso(q.fee_cents)} fee via ${wallet.dataset.name}`,
        });
        renderCart();
        ["loadMobile", "loadAmount", "loadDesc", "loadRef"].forEach((id) => ($(id).value = ""));
        $("loadPromo").checked = false;
        $("loadQuote").textContent = "Enter the load amount.";
        $("loadMobile").focus();
    });

    function cartTotal() {
        return cart.reduce((sum, line) => sum + line.total_cents, 0);
    }

    function renderCart() {
        const body = $("cartBody");
        if (!cart.length) {
            body.innerHTML = '<tr class="empty"><td colspan="4">No items yet. Tap a service or LOAD.</td></tr>';
        } else {
            body.innerHTML = cart
                .map((line, i) => {
                    const sub = line.kind === "load" ? line.detail : line.qty > 1 ? `${peso(toCents(line.unit_price))} each` : "";
                    const desc = line.description ? ` · ${line.description}` : "";
                    return `<tr>
                        <td><strong>${escapeHtml(line.name)}</strong>${escapeHtml(desc)}${sub ? `<div class="muted small">${escapeHtml(sub)}</div>` : ""}</td>
                        <td class="num">${line.qty}</td>
                        <td class="num">${escapeHtml(peso(line.total_cents))}</td>
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
        $("cashBlock").hidden = byWallet;
        $("walletPayBlock").hidden = !byWallet;
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

    function clearSale() {
        cart.length = 0;
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
        const byWallet = pay.value !== "cash";
        if (isJob()) {
            if (cart.some((line) => line.kind === "load")) return say("Load can't be in a job order. Ring it up as a separate sale.", "error");
            if (!$("custName").value.trim()) return say("Enter the customer's name for a job order", "error");
            const down = toCents($("downPayment").value);
            if (!down || down >= cartTotal()) return say("Down payment must be more than zero and less than the total", "error");
        }
        if (byWallet) {
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
                lines: cart.map(({ total_cents, name, detail, wallet_name, ...line }) => line),
                payment_method: byWallet ? "wallet" : "cash",
                pay_wallet_id: byWallet ? Number(pay.value) : null,
                payment_reference: byWallet ? $("payRef").value : null,
                cash: byWallet ? null : $("cashIn").value,
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
                    (byWallet
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

    async function fetchWalletQuote() {
        const kind = walletKind();
        $("feeModeField").hidden = kind !== "cash_out";
        const amount = $("wAmount").value.trim();
        walletQuote = null;
        if (!amount) {
            $("walletQuote").textContent = "Enter the amount.";
            updateWalletChange();
            return null;
        }
        try {
            const q = await getJson(
                `/pos/api/quote/wallet?kind=${kind}&amount=${encodeURIComponent(amount)}&fee_mode=${feeMode()}`,
            );
            walletQuote = q;
            const wallet = walletChoice()?.parentElement.textContent.trim() || "";
            const mobile = $("wMobile").value || "the customer";
            let steps;
            if (kind === "cash_in") {
                steps = [
                    `Collect <strong>${peso(q.collect_cents)}</strong> cash (${peso(q.amount_cents)} + ${peso(q.fee_cents)} fee)`,
                    `Send <strong>${peso(q.amount_cents)}</strong> from ${escapeHtml(wallet)} to ${escapeHtml(mobile)}`,
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
    document.querySelectorAll('input[name="kind"], input[name="fee_mode"], input[name="wallet"]').forEach((el) =>
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
