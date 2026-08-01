/* First-party click metrics (owner scope, expanded 2026-08-01): share-card,
   trade-analyzer, outbound-link, watch, and unwatch clicks only. Same-origin beacon, so the
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
    /* Central share-surface recognition (review F4): any internal link to a
       /share-card page or PNG, a /player-card page or PNG, or a /share/ PNG
       counts as a share_card click without per-template tagging. */
    var SHARE_PATH = /(\/share-card(\.png)?$)|(\/player-card\/)|(^\/share\/)/;
    document.addEventListener("click", function (ev) {
        if (!ev.target || !ev.target.closest) { return; }
        var tagged = ev.target.closest("[data-metric]");
        if (tagged) {
            send(tagged.getAttribute("data-metric"), tagged.hostname || null);
            return;
        }
        var link = ev.target.closest("a[href]");
        if (!link || !link.hostname) { return; }
        if (link.hostname === window.location.hostname) {
            if (SHARE_PATH.test(link.pathname)) {
                send("share_card", null);
            }
            return;
        }
        if (link.protocol === "http:" || link.protocol === "https:") {
            send("outbound", link.hostname);
        }
    }, true);
})();
