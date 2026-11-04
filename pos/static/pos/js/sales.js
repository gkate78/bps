(() => {
    const dialog = document.getElementById("voidDialog");
    const errorBox = document.getElementById("voidError");
    let target = null;

    document.querySelectorAll("[data-void-id]").forEach((btn) => {
        btn.addEventListener("click", () => {
            target = { type: btn.dataset.voidType, id: btn.dataset.voidId };
            document.getElementById("voidNo").textContent = btn.dataset.voidNo;
            document.getElementById("voidReason").value = "";
            document.getElementById("voidPin").value = "";
            errorBox.hidden = true;
            dialog.showModal();
            document.getElementById("voidReason").focus();
        });
    });

    document.getElementById("voidCancel").addEventListener("click", () => dialog.close());

    document.getElementById("voidForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!target) return;
        const paths = { sale: "sales", wallet: "wallet-txns", payment: "payments" };
        const url = `/pos/api/${paths[target.type]}/${target.id}/void`;
        try {
            await postJson(url, {
                reason: document.getElementById("voidReason").value,
                admin_pin: document.getElementById("voidPin").value,
            });
            window.location.reload();
        } catch (err) {
            errorBox.textContent = err.message;
            errorBox.hidden = false;
        }
    });
})();
