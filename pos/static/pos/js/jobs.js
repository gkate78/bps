(() => {
    const $ = (id) => document.getElementById(id);
    const dialog = $("collectDialog");
    let job = null;

    const payChoice = () => document.querySelector('input[name="cpay"]:checked');
    const amountDue = () => {
        const typed = toCents($("collectAmount").value);
        return typed === null ? job.balance : typed;
    };

    function showError(message) {
        $("collectError").textContent = message;
        $("collectError").hidden = !message;
    }

    function updateForm() {
        const byWallet = payChoice().value !== "cash";
        $("collectCash").hidden = byWallet;
        $("collectRefLabel").hidden = !byWallet;
        const cash = toCents($("collectCashIn").value);
        const due = amountDue();
        const el = $("collectChange");
        if (cash === null) {
            el.textContent = "₱0.00";
            el.classList.remove("short");
        } else {
            el.textContent = cash >= due ? peso(cash - due) : `Short ${peso(due - cash)}`;
            el.classList.toggle("short", cash < due);
        }
    }

    document.querySelectorAll("[data-collect]").forEach((btn) => {
        btn.addEventListener("click", () => {
            job = { id: btn.dataset.collect, balance: Number(btn.dataset.balance) };
            $("collectNo").textContent = btn.dataset.no;
            $("collectCustomer").textContent = btn.dataset.customer;
            $("collectBalance").textContent = peso(job.balance);
            $("collectAmount").value = "";
            $("collectAmount").placeholder = `${(job.balance / 100).toFixed(2)} (full balance)`;
            $("collectCashIn").value = "";
            $("collectRef").value = "";
            document.querySelector('input[name="cpay"][value="cash"]').checked = true;
            showError("");
            updateForm();
            dialog.showModal();
            $("collectCashIn").focus();
        });
    });

    ["collectAmount", "collectCashIn"].forEach((id) => $(id).addEventListener("input", updateForm));
    document.querySelectorAll('input[name="cpay"]').forEach((el) => el.addEventListener("change", updateForm));
    $("collectCancel").addEventListener("click", () => dialog.close());

    let saving = false;
    $("collectForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        if (saving || !job) return;
        const pay = payChoice();
        const byWallet = pay.value !== "cash";
        const due = amountDue();
        if (due <= 0 || due > job.balance) return showError(`Amount must be more than zero and at most ${peso(job.balance)}`);
        if (byWallet && !$("collectRef").value.trim()) return showError(`Enter the ${pay.dataset.name} reference no.`);
        if (!byWallet) {
            const cash = toCents($("collectCashIn").value);
            if (cash === null) return showError("Enter the cash received");
            if (cash < due) return showError("Cash received is less than the amount");
        }
        saving = true;
        $("collectSave").disabled = true;
        const win = openReceiptWindow();
        try {
            const result = await postJson(`/pos/api/sales/${job.id}/payments`, {
                amount: $("collectAmount").value,
                payment_method: byWallet ? "wallet" : "cash",
                pay_wallet_id: byWallet ? Number(pay.value) : null,
                payment_reference: byWallet ? $("collectRef").value : null,
                cash: byWallet ? null : $("collectCashIn").value,
            });
            showReceipt(win, `/pos/receipt/payment/${result.id}?autoprint=1`);
            window.location.reload();
        } catch (err) {
            if (win) win.close();
            showError(err.message);
        } finally {
            saving = false;
            $("collectSave").disabled = false;
        }
    });

    document.querySelectorAll("[data-status]").forEach((btn) => {
        btn.addEventListener("click", async () => {
            try {
                await postJson(`/pos/api/sales/${btn.dataset.id}/job-status`, { status: btn.dataset.status });
                window.location.reload();
            } catch (err) {
                const notice = $("notice");
                notice.className = "alert alert-error";
                notice.textContent = err.message;
                notice.hidden = false;
            }
        });
    });
})();
