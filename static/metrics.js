/* First-party click metrics (owner scope, 2026-07-30): share-card,
   trade-analyzer, and outbound-link clicks only. Same-origin beacon, so the
   site's CSP is untouched. No identifiers are read or sent from here — the
   server manages the anonymous vc_vid cookie; this file never touches it. */
(function () {
    "use strict";
    function send(metric, target) {
        try {
            var body = JSON.stringify({ metric: metric, target: target || null });
            if (navigator.sendBeacon) {
                navigator.sendBeacon(
                    "/metrics/event",
                    new Blob([body], { type: "application/json" })
                );
            }
        } catch (e) { /* metrics must never break the page */ }
    }
    document.addEventListener("click", function (ev) {
        if (!ev.target || !ev.target.closest) { return; }
        var tagged = ev.target.closest("[data-metric]");
        if (tagged) {
            send(tagged.getAttribute("data-metric"), tagged.hostname || null);
            return;
        }
        var link = ev.target.closest("a[href]");
        if (
            link && link.hostname &&
            link.hostname !== window.location.hostname &&
            (link.protocol === "http:" || link.protocol === "https:")
        ) {
            send("outbound", link.hostname);
        }
    }, true);
})();
