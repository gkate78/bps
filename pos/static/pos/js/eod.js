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
    function recompute(table) {
        const opening = toCents(table.querySelector('input[name="opening_cash"], input[name="opening"]').value) || 0;
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

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const cash = document.querySelector('table.eod[data-target="cash"]');
        const body = {
            opening_cash: cash.querySelector('input[name="opening_cash"]').value,
            counted_cash: cash.querySelector('input[name="counted_cash"]').value,
            notes: form.querySelector('input[name="notes"]').value,
            wallets: [...document.querySelectorAll("table.eod[data-wallet]")].map((t) => ({
                wallet_id: Number(t.dataset.wallet),
                opening: t.querySelector('input[name="opening"]').value,
                counted: t.querySelector('input[name="counted"]').value,
            })),
        };
        try {
            await postJson(`/pos/api/eod/${day}`, body);
            window.location.reload();
        } catch (err) {
            say(err.message, "error");
        }
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
