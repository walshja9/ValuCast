(function () {
    "use strict";

    var STORAGE_KEY = "vc-watchlist-v1";
    var MAX_ITEMS = 50;
    var KEY_RE = /^[1-9]\d{0,9}_(hitter|pitcher)$/;
    var refreshToken = 0;
    var enabled = false;

    function panel() { return document.getElementById("my-players"); }

    function validKeys(raw) {
        var seen = Object.create(null);
        var keys = [];
        if (!Array.isArray(raw)) { return keys; }
        raw.forEach(function (key) {
            if (typeof key !== "string" || !KEY_RE.test(key) || seen[key] || keys.length >= MAX_ITEMS) { return; }
            seen[key] = true;
            keys.push(key);
        });
        return keys;
    }

    function readKeys() {
        try { return validKeys(JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]")); }
        catch (error) { return []; }
    }

    function writeKeys(keys) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(validKeys(keys))); return true; }
        catch (error) { return false; }
    }

    function syncControls() {
        if (!enabled) { return; }
        var followed = Object.create(null);
        readKeys().forEach(function (key) { followed[key] = true; });
        document.querySelectorAll(".watch-toggle[data-watch-key]").forEach(function (button) {
            var key = button.getAttribute("data-watch-key");
            var active = !!followed[key];
            var name = button.getAttribute("data-watch-name") || "player";
            button.textContent = active ? "★" : "☆";
            button.setAttribute("aria-pressed", active ? "true" : "false");
            button.setAttribute("aria-label", (active ? "Unfollow " : "Follow ") + name + (active ? " from" : " in") + " My Players");
            button.setAttribute("data-metric", active ? "unwatch_player" : "watch_player");
            button.hidden = false;
        });
    }

    function announceLimit() {
        var target = panel();
        if (!target) { return; }
        target.innerHTML = '<div class="my-players-card glass"><p>My Players is limited to 50 players on this device.</p></div>';
        target.hidden = false;
    }

    function refreshPanel() {
        var target = panel();
        if (!enabled || !target) { return; }
        var keys = readKeys();
        var token = ++refreshToken;
        if (!keys.length) {
            target.innerHTML = "";
            target.hidden = true;
            return;
        }
        var params = new URLSearchParams(window.location.search);
        params.delete("pool");
        params.delete("position");
        params.delete("search");
        params.delete("callups");
        params.delete("display");
        params.delete("watch");
        keys.forEach(function (key) { params.append("watch", key); });
        fetch("/my-players?" + params.toString(), {
            headers: { "HX-Request": "true" },
            credentials: "same-origin"
        }).then(function (response) {
            if (!response.ok) { throw new Error("watchlist response"); }
            return response.text();
        }).then(function (markup) {
            if (token !== refreshToken) { return; }
            target.innerHTML = markup;
            target.hidden = !markup.trim();
            syncControls();
        }).catch(function () {
            if (token !== refreshToken || target.innerHTML.trim()) { return; }
            target.hidden = true;
        });
    }

    function handleClick(event) {
        var button = event.target && event.target.closest ? event.target.closest(".watch-toggle[data-watch-key]") : null;
        if (!button || !enabled) { return; }
        event.preventDefault();
        event.stopPropagation();
        var key = button.getAttribute("data-watch-key");
        var keys = readKeys();
        var index = keys.indexOf(key);
        if (index >= 0) { keys.splice(index, 1); }
        else if (keys.length >= MAX_ITEMS) { announceLimit(); return; }
        else { keys.push(key); }
        if (!writeKeys(keys)) { return; }
        syncControls();
        refreshPanel();
    }

    function start() {
        try {
            var probe = STORAGE_KEY + "-probe";
            localStorage.setItem(probe, "1");
            localStorage.removeItem(probe);
            enabled = true;
        } catch (error) { return; }
        syncControls();
        refreshPanel();
    }

    // Ranking rows are themselves clickable. Capture the star first so a
    // follow/unfollow never also toggles the row detail underneath it.
    document.addEventListener("click", handleClick, true);
    document.addEventListener("DOMContentLoaded", start);
    document.addEventListener("htmx:afterSwap", function () { syncControls(); refreshPanel(); });
    window.addEventListener("storage", function (event) {
        if (event.key !== STORAGE_KEY) { return; }
        syncControls();
        refreshPanel();
    });
}());
