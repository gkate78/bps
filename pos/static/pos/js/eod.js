(() => {
    const form = document.getElementById("eodForm");
    const day = form.dataset.day;
    const notice = document.getElementById("notice");

    function say(message, kind) {
        notice.className = `alert alert-${kind}`;
        notice.textContent = message;
        notice.hidden = false;
        notice.scrollIntoView({ block: "nearest" });
    }

    // Expected = opening + the day's change; difference = counted - expected.
    // Encoders' tables have no opening input (data-opening holds it) and the cash table has no expected cell.
    function recompute(table) {
        if (!table.querySelector("[data-expected]")) return;
        const openingInput = table.querySelector('input[name="opening_cash"], input[name="opening"]');
        const opening = openingInput ? toCents(openingInput.value) || 0 : Number(table.dataset.opening || 0);
        const expected = opening + Number(table.dataset.change);
        table.querySelector("[data-expected]").textContent = peso(expected);
        const countedText = table.querySelector('input[name="counted_cash"], input[name="counted"]').value;
        const counted = toCents(countedText);
        const cell = table.querySelector("[data-difference]");
        cell.classList.remove("neg", "pos");
        if (counted === null) {
            cell.textContent = countedText.trim() ? "check the amount" : "—";
            return;
        }
        const diff = counted - expected;
        if (diff === 0) cell.textContent = "Balanced";
        else cell.textContent = diff > 0 ? `Over ${peso(diff)}` : `Short ${peso(-diff)}`;
        if (diff !== 0) cell.classList.add(diff > 0 ? "pos" : "neg");
    }

    const tables = [...document.querySelectorAll("table.eod")];
    tables.forEach((table) => {
        recompute(table);
        table.querySelectorAll("input").forEach((input) => input.addEventListener("input", () => recompute(table)));
    });

    function readCounts() {
        const cash = document.querySelector('table.eod[data-target="cash"]');
        return {
            opening_cash: cash.querySelector('input[name="opening_cash"]')?.value,
            counted_cash: cash.querySelector('input[name="counted_cash"]').value,
            notes: form.querySelector('input[name="notes"]').value,
            wallets: [...document.querySelectorAll("table.eod[data-wallet]")].map((t) => ({
                wallet_id: Number(t.dataset.wallet),
                opening: t.querySelector('input[name="opening"]')?.value,
                counted: t.querySelector('input[name="counted"]').value,
            })),
        };
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            await postJson(`/pos/api/eod/${day}`, readCounts());
            window.location.reload();
        } catch (err) {
            say(err.message, "error");
        }
    });

    const handOver = document.getElementById("handOver");
    if (handOver) {
        handOver.addEventListener("click", async () => {
            const body = readCounts();
            const counted = toCents(body.counted_cash || "");
            if (counted === null) return say("Count the cash in the drawer before handing it over", "error");
            if (!confirm(`Hand over the drawer with ${peso(counted)} counted? The next cashier starts from this amount.`)) return;
            try {
                await postJson(`/pos/api/eod/${day}/handover`, body);
                window.location.reload();
            } catch (err) {
                say(err.message, "error");
            }
        });
    }

    document.querySelectorAll("[data-remove-handover]").forEach((btn) => {
        btn.addEventListener("click", async () => {
            if (!confirm("Remove this handover? Its two shifts become one again.")) return;
            try {
                await postJson(`/pos/api/handovers/${btn.dataset.removeHandover}/void`, {});
                window.location.reload();
            } catch (err) {
                say(err.message, "error");
            }
        });
    });

    const kind = document.getElementById("mvKind");
    kind.addEventListener("change", () => {
        document.getElementById("mvWalletLabel").hidden = !["to_wallet", "from_wallet"].includes(kind.value);
    });
    document.getElementById("mvAdd").addEventListener("click", async () => {
        try {
            await postJson(`/pos/api/eod/${day}/movements`, {
                kind: kind.value,
                amount: document.getElementById("mvAmount").value,
                reason: document.getElementById("mvReason").value,
                wallet_id: Number(document.getElementById("mvWallet").value),
            });
            window.location.reload();
        } catch (err) {
            say(err.message, "error");
        }
    });

    document.querySelectorAll("[data-remove-movement]").forEach((btn) => {
        btn.addEventListener("click", async () => {
            if (!confirm("Remove this cash movement?")) return;
            try {
                await postJson(`/pos/api/cash-movements/${btn.dataset.removeMovement}/void`, {});
                window.location.reload();
            } catch (err) {
                say(err.message, "error");
            }
        });
    });
})();
