(function () {
    "use strict";

    const cfg = window.CUSTOMER_DASHBOARD_FILTERS || {};
    const accountBillerMap = cfg.accountBillerMap || {};
    const accountSelect = document.getElementById("accountFilter");
    const billerSelect = document.getElementById("billerFilter");
    const form = accountSelect?.closest("form");

    if (!accountSelect || !billerSelect || !form) {
        return;
    }

    function allAccounts() {
        return Object.keys(accountBillerMap).sort();
    }

    function allBillers() {
        const unique = new Set();
        Object.values(accountBillerMap).forEach((arr) => {
            (arr || []).forEach((value) => unique.add(value));
        });
        return Array.from(unique).sort();
    }

    function accountsForBiller(billerValue) {
        const biller = String(billerValue || "").trim().toUpperCase();
        if (!biller) {
            return allAccounts();
        }
        return allAccounts().filter((account) => {
            const billers = accountBillerMap[account] || [];
            return billers.includes(biller);
        });
    }

    function billersForAccount(accountValue) {
        const account = String(accountValue || "").trim().toUpperCase();
        if (!account) {
            return allBillers();
        }
        return (accountBillerMap[account] || []).slice().sort();
    }

    function setOptions(selectEl, values, defaultLabel, currentValue) {
        const current = String(currentValue || "").trim().toUpperCase();
        selectEl.innerHTML = "";
        const defaultOpt = document.createElement("option");
        defaultOpt.value = "";
        defaultOpt.textContent = defaultLabel;
        selectEl.appendChild(defaultOpt);

        values.forEach((value) => {
            const opt = document.createElement("option");
            opt.value = value;
            opt.textContent = value;
            if (value === current) {
                opt.selected = true;
            }
            selectEl.appendChild(opt);
        });

        if (current && !values.includes(current)) {
            selectEl.value = "";
        }
    }

    function rebuildBillerOptions(accountValue) {
        const billers = billersForAccount(accountValue);
        setOptions(
            billerSelect,
            billers,
            "All billers",
            billerSelect.value
        );
    }

    function rebuildAccountOptions(billerValue) {
        const accounts = accountsForBiller(billerValue);
        setOptions(
            accountSelect,
            accounts,
            "All accounts under this phone",
            accountSelect.value
        );
    }

    function synchronizeOnInit() {
        const selectedAccount = String(cfg.selectedAccount || "").trim().toUpperCase();
        const selectedBiller = String(cfg.selectedBiller || "").trim().toUpperCase();

        // Start with full options, then narrow according to active selection.
        setOptions(accountSelect, allAccounts(), "All accounts under this phone", selectedAccount);
        setOptions(billerSelect, allBillers(), "All billers", selectedBiller);

        if (selectedBiller) {
            rebuildAccountOptions(selectedBiller);
        }
        if (selectedAccount) {
            rebuildBillerOptions(selectedAccount);
        } else {
            // If account is not selected, keep billers aligned with selected biller/account domain.
            rebuildBillerOptions(accountSelect.value);
        }
    }

    accountSelect.addEventListener("change", () => {
        rebuildBillerOptions(accountSelect.value);
        form.requestSubmit();
    });

    billerSelect.addEventListener("change", () => {
        rebuildAccountOptions(billerSelect.value);
        form.requestSubmit();
    });

    synchronizeOnInit();
})();
