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
