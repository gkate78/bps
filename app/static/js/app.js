function sanitizePhoneInput(el) {
    if (!el) {
        return;
    }
    const digits = String(el.value || "").replace(/\D/g, "").slice(0, 11);
    if (el.value !== digits) {
        el.value = digits;
    }
}

function uppercaseTextInput(el) {
    if (!el) {
        return;
    }
    const upper = String(el.value || "").toUpperCase();
    if (el.value !== upper) {
        el.value = upper;
    }
}

document.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) {
        return;
    }

    if (target instanceof HTMLInputElement && target.type === "tel") {
        sanitizePhoneInput(target);
        return;
    }

    if (target instanceof HTMLTextAreaElement || target.type === "text" || target.type === "email") {
        uppercaseTextInput(target);
    }
});
