(function () {
    "use strict";

    const button = document.getElementById("install-app-button");
    const dialog = document.getElementById("install-app-dialog");
    if (!button) return;

    const installed =
        window.matchMedia("(display-mode: standalone)").matches ||
        window.navigator.standalone === true;
    if (installed) return;

    const navigator = window.navigator;
    const isiPhoneOrIPad =
        /iphone|ipad|ipod/i.test(navigator.userAgent) ||
        (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    let installPrompt = null;

    if (isiPhoneOrIPad && dialog && typeof dialog.showModal === "function") {
        button.hidden = false;
    }

    window.addEventListener("beforeinstallprompt", function (event) {
        event.preventDefault();
        installPrompt = event;
        button.hidden = false;
    });

    button.addEventListener("click", async function () {
        if (installPrompt) {
            const prompt = installPrompt;
            installPrompt = null;
            button.hidden = true;
            await prompt.prompt();
            return;
        }
        if (isiPhoneOrIPad && dialog && typeof dialog.showModal === "function") {
            dialog.showModal();
        }
    });

    window.addEventListener("appinstalled", function () {
        installPrompt = null;
        button.hidden = true;
        if (dialog && dialog.open) dialog.close();
    });
}());
