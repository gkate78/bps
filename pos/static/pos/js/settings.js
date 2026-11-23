// Rename a service or network: ask for the new name, then submit its form.
document.querySelectorAll("form[data-rename]").forEach((form) => {
    form.addEventListener("submit", (event) => {
        const name = prompt(`New name for ${form.dataset.rename}:`, form.dataset.rename);
        if (!name || !name.trim() || name.trim().toUpperCase() === form.dataset.rename) {
            event.preventDefault();
            return;
        }
        form.elements.name.value = name.trim().toUpperCase();
    });
});

// Google Sheets: copy the Apps Script; show that a backup is running (it can take a minute).
document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
        const box = document.getElementById(btn.dataset.copy);
        box.select();
        try {
            await navigator.clipboard.writeText(box.value);
        } catch (_) {
            document.execCommand("copy");
        }
        btn.textContent = "Copied";
    });
});
document.querySelectorAll("form[data-busy]").forEach((form) => {
    form.addEventListener("submit", () => {
        const btn = form.querySelector("button");
        btn.disabled = true;
        btn.textContent = form.dataset.busy;
    });
});
