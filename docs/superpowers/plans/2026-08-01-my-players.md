# My Players Implementation Plan

> **For Codex:** Execute this plan with the executing-plans skill in the
> isolated codex/my-players worktree. Follow RED/GREEN order and stop at review
> checkpoints. Do not merge without owner approval.

**Goal:** Add a manual, browser-local watchlist that shows a compact **My
Players** panel above the active Redraft, Dynasty, or Prospects board using the
same current settings and validated data as that board.

**Architecture:** Store at most 50 canonical mlbam_id_role keys in
localStorage. A small static controller synchronizes accessible star buttons
and requests a same-origin Flask HTML partial. The server validates keys,
builds the existing board context with display filters removed, and renders
followed players available in that board's current top-200 result set. Other
valid identities stay followed with an honest alternate-board link or
unavailable state. No watchlist data is persisted server-side.

**Tech stack:** Python 3.10+, Flask, Jinja, vanilla JavaScript, htmx lifecycle
events, existing CSS, pytest, and Playwright for final browser verification.

**Frozen boundaries:** No edits to models, ranks, values, projection inputs,
committed data artifacts, quality governors, publication gates, workflows,
Role Watch, Buy signals, Movers, the failed-decay flag, or the pitcher
publication veto.

---

## Task 1: Lock the server-side watchlist contract

**Files:**

- Create: tests/test_my_players.py
- Modify: app.py
- Create: templates/partials/my_players.html

### Step 1: Write the failing identity-parser tests

In tests/test_my_players.py, add focused tests for a pure helper named
_parse_watch_keys:

- accepts repeated watch=682634_hitter and watch=682634_pitcher values;
- preserves input order and keeps the two roles separate;
- removes exact duplicates without reordering;
- rejects missing IDs, zero/negative IDs, names, unknown roles, extra suffixes,
  and overlong numeric IDs;
- caps the accepted list at 50.

Use a plain list of raw strings rather than constructing request globals.

Run:

~~~powershell
python -m pytest tests/test_my_players.py -q
~~~

Expected: FAIL because _parse_watch_keys does not exist.

### Step 2: Implement the smallest strict parser

In app.py:

- add a compiled full-match pattern for ^[1-9]\d{0,9}_(hitter|pitcher)$;
- add _parse_watch_keys(values, limit=50);
- deduplicate with a seen set while keeping a list for order;
- stop after 50 accepted unique identities.

Do not introduce a new identity class or module. Continue using the repository's
existing MLBAM-plus-role convention.

Run the targeted test again.

Expected: parser tests PASS.

### Step 3: Write failing fragment-route tests

Add tests for GET /my-players with HX-Request: true covering:

1. no watch values returns an empty partial without an error;
2. a valid Redraft identity renders name, current overall rank, current value,
   team, positions, and an Unfollow control;
3. the same identity resolves in Dynasty and Prospects when present there;
4. hitter and pitcher identities sharing one MLBAM ID do not collapse;
5. pool, position, search, callups, and display do not hide a followed player,
   while scoring and league parameters remain active;
6. a valid identity absent from the active top 200 remains followed with a
   neutral "Not available on this board" state and an alternate Dynasty or
   Prospects search link when another current store identifies it;
7. an identity absent from all stores renders "Player no longer available"
   with Unfollow, never a fabricated name, rank, or value;
8. a browser-direct HTML visit redirects to /.

For league-context parity, select a committed player and compare the rank/value
shown in /my-players with the same row from /rankings under the same query. Do
not assert a hand-authored value.

Run:

~~~powershell
python -m pytest tests/test_my_players.py -q
~~~

Expected: route tests FAIL with 404.

### Step 4: Build a uniform display-row adapter and fragment route

In app.py:

- add a Redraft role helper: starter, reliever, and pitcher pools map to
  pitcher; other eligible rows map to hitter;
- add a helper that copies request arguments and removes only display filters:
  pool, position, search, callups, and display;
- add a private identity lookup over dd_store.get_all() and the active
  projection store for honest fallback names and alternate-board links;
- add _my_players_context(args, watch_keys) that:
  - calls _build_context for Redraft or _build_dynasty_context plus
    _apply_prospect_board_context for Prospects;
  - indexes only the resulting top-200 board rows by canonical identity;
  - reuses existing row/result values, ranks, teams, positions, status, and
    movement context instead of recalculating or synthesizing them;
  - sorts resolved rows by current displayed board order and appends unresolved
    keys in stored order;
  - produces plain template dictionaries with key, resolved, name, rank_label,
    value_label, team, positions, status_label, movement_label, detail_url, and
    optional alternate_url;
- add GET /my-players:
  - redirect browser-direct HTML requests with _redirect_home;
  - read repeated keys with request.args.getlist("watch");
  - validate with _parse_watch_keys;
  - render templates/partials/my_players.html;
  - set Cache-Control: private, no-store.

In templates/partials/my_players.html:

- render no panel content for an empty accepted list;
- use a semantic heading and compact list otherwise;
- link resolved names to the existing detail surface;
- label unresolved rows neutrally and show no placeholder numeric values;
- include an Unfollow button with data-watch-key, aria-pressed=true, and
  data-metric=unwatch_player;
- state "Saved on this device."

Run the targeted file again.

Expected: server and partial tests PASS.

### Step 5: Commit the server slice

~~~powershell
git add app.py templates/partials/my_players.html tests/test_my_players.py
git commit -m "Add My Players fragment contract"
~~~

Review checkpoint: confirm there is still no production state, scoring change,
or public JSON change.

---

## Task 2: Add progressive-enhancement watch controls

**Files:**

- Modify: tests/test_my_players.py
- Modify: templates/index.html
- Modify: templates/partials/rankings_table.html
- Modify: templates/partials/rankings_table_dynasty.html
- Create: static/watchlist.js
- Modify: templates/base.html

### Step 1: Write failing markup and controller contract tests

Add tests asserting:

- index.html contains a hidden live-region panel immediately above
  #rankings-container;
- eligible Redraft, Dynasty, and Prospect rows expose a hidden button with a
  canonical data-watch-key, aria-pressed=false, and accessible Follow label;
- rows without a usable MLBAM-plus-role identity expose no watch button;
- the button is next to the name, not a new table column;
- base.html loads /static/watchlist.js with defer;
- the controller contains vc-watchlist-v1, a 50-item cap, click delegation,
  htmx:afterSwap, and a storage-failure fail-soft path;
- the partial request sends HX-Request: true and repeated watch parameters;
- the request removes only the five display filters and retains scoring/league
  parameters;
- a monotonically increasing token ignores stale responses;
- no player ID or name is attached to a metric payload.

Run:

~~~powershell
python -m pytest tests/test_my_players.py -q
~~~

Expected: markup/controller tests FAIL.

### Step 2: Add dormant server-rendered hooks

In templates/index.html, insert immediately before #rankings-container:

~~~html
<section id="my-players" class="my-players" aria-live="polite" hidden></section>
~~~

In both rankings tables, render a hidden progressive-enhancement button next to
the name only when a valid identity exists. Use the same server helpers used by
the fragment route. Initial state:

- text ☆;
- aria-pressed=false;
- aria-label="Follow PLAYER in My Players";
- data-metric=watch_player;
- hidden, so a script failure never leaves a dead control.

Do not change row handlers, detail toggles, Compare behavior, column counts, or
sorting indexes.

### Step 3: Implement static/watchlist.js

Use one dependency-free IIFE:

- probe localStorage in try/catch; on failure leave controls and panel hidden;
- read vc-watchlist-v1 as JSON, keep only canonical keys, deduplicate, and cap
  at 50 before each use;
- synchronize every data-watch-key button:
  - followed: ★, aria-pressed=true, Unfollow label,
    data-metric=unwatch_player;
  - not followed: ☆, aria-pressed=false, Follow label,
    data-metric=watch_player;
  - remove hidden after synchronization;
- handle clicks with document delegation, preventDefault and stopPropagation,
  update storage, synchronize, then refresh;
- when already at 50, do not mutate and announce the limit in the live region;
- build the query from window.location.search, remove only pool, position,
  search, callups, and display, then append repeated watch parameters;
- fetch /my-players with HX-Request: true so analytics does not count a
  fragment as a pageview;
- hide and empty the panel when the list is empty;
- on current successful response, replace panel HTML and unhide;
- on error retain a prior panel, otherwise hide it, and never alter the board;
- listen for DOMContentLoaded, htmx:afterSwap, and storage;
- use an incrementing refresh token to ignore older responses.

Do not add a service worker, dependency, package, build step, or inline script.

### Step 4: Load the controller and verify CSP

Add the deferred script to templates/base.html beside existing first-party
controllers. Do not alter the CSP.

Run:

~~~powershell
python -m pytest tests/test_my_players.py tests/test_ui_htmx_csp.py -q
~~~

Expected: PASS.

### Step 5: Commit the browser behavior

~~~powershell
git add templates/index.html templates/base.html static/watchlist.js
git add templates/partials/rankings_table.html
git add templates/partials/rankings_table_dynasty.html tests/test_my_players.py
git commit -m "Add local My Players controls"
~~~

Review checkpoint: stars must not open details or toggle Compare, and the same
list must survive switching among all three boards.

---

## Task 3: Style the panel and extend aggregate analytics

**Files:**

- Modify: static/style.css
- Modify: app.py
- Modify: tests/test_my_players.py
- Modify: tests/test_site_metrics.py
- Modify: static/metrics.js only to correct its event-scope comment

### Step 1: Write failing presentation and metric tests

Add tests that assert:

- watch_player and unwatch_player are allowlisted by /metrics/event and appear
  only as aggregate click counts;
- unknown metrics still return 204 and record nothing;
- watch event targets are null, so no player key, name, route, or settings reach
  the metric store;
- fetching /my-players with HX-Request does not increase pageviews;
- CSS contains panel, row, value, unavailable, toggle, focus-visible, and mobile
  states;
- the toggle's interactive size is at least 44 by 44 pixels;
- narrow layouts do not require horizontal scrolling.

Run:

~~~powershell
python -m pytest tests/test_my_players.py tests/test_site_metrics.py -q
~~~

Expected: the new analytics/style tests FAIL.

### Step 2: Extend the current metric allowlist only

In app.py, add watch_player and unwatch_player to
_METRICS_CLICK_ALLOWED. Reuse the current data-metric capture in metrics.js;
watchlist.js changes the button metric before a click. Do not add an endpoint,
schema, event payload, visitor field, target, or identity field.

Correct comments/tests from "three named click events" to five without
weakening the privacy refusals.

### Step 3: Add minimum responsive CSS

In static/style.css:

- align the panel with the existing glass/card system;
- keep the heading and local-device note concise;
- use a compact row with truncation for long names;
- keep rank/value legible without creating a second rankings table;
- render unresolved rows neutrally;
- make toggles at least 44px in both axes with hover and focus-visible states;
- at the existing mobile breakpoint, stack context beneath the name and avoid
  horizontal overflow.

Run:

~~~powershell
python -m pytest tests/test_my_players.py tests/test_site_metrics.py
python -m pytest tests/test_ui_a11y.py tests/test_ui_toolbar.py tests/test_ui_htmx_csp.py
~~~

Expected: PASS.

### Step 4: Commit the finished UI slice

~~~powershell
git add app.py static/style.css static/metrics.js
git add tests/test_my_players.py tests/test_site_metrics.py
git commit -m "Polish and measure My Players"
~~~

---

## Task 4: Browser verification and regression proof

**Files:** Modify only if a verified defect is found in files already listed.

### Step 1: Run the focused suite

~~~powershell
python -m pytest tests/test_my_players.py tests/test_site_metrics.py
python -m pytest tests/test_app.py tests/test_dynasty_customization.py
python -m pytest tests/test_ui_a11y.py tests/test_ui_toolbar.py tests/test_ui_htmx_csp.py
~~~

Expected: all focused tests PASS.

### Step 2: Run the full suite

~~~powershell
python -m pytest -q
~~~

Expected: full suite passes with only documented skips. Record exact totals.

### Step 3: Verify the real flow in Chromium

Start the app with the repository's current development command and use
Playwright at desktop and mobile widths:

1. empty storage: panel absent, stars visible;
2. follow one hitter and pitcher: panel appears with board-parity rank/value;
3. detail and Compare still work independently;
4. switch Redraft → Dynasty → Prospects: list persists and rows re-resolve or
   show neutral unavailability;
5. customize league settings: panel refreshes after rankings swap;
6. filter/search the board: watched players stay in the panel;
7. reload and use another tab: storage persists and synchronizes;
8. unfollow in the panel: matching board star updates;
9. deny localStorage: feature hides while board remains usable;
10. mobile: no overflow and 44px tap targets.

Capture one desktop and one mobile screenshot for PR review. Do not commit them
unless a repository review-artifact location already exists.

### Step 4: Verify frozen boundaries and diff hygiene

~~~powershell
git diff --name-only origin/master...HEAD
git diff --check origin/master...HEAD
git status --short
~~~

Expected scope: approved docs, app.py, board/index/base templates, the new
partial and controller, style.css, and tests. No model, artifact, workflow,
governor, publication, or scoring file.

Inspect the frozen contracts without editing them:

~~~powershell
rg -n "BUCKET_CALIBRATION_VERSION|failed.decay|pitcher.*veto" prospects quality docs data/models -g "*.py" -g "*.md" -g "*.json"
~~~

### Step 5: Request code review

Use requesting-code-review against origin/master...HEAD. Require review of:

- identity and role separation;
- strict input validation and no server-side watchlist persistence;
- current-board parity and missing-player honesty;
- htmx lifecycle and stale-response handling;
- localStorage failure behavior;
- analytics privacy and pageview non-inflation;
- detail/Compare interaction isolation;
- mobile accessibility;
- frozen-boundary scope.

Fix verified findings test-first and rerun focused and full suites.

---

## Task 5: Prepare a draft PR for owner review

### Step 1: Final verification

~~~powershell
python -m pytest -q
git diff --check origin/master...HEAD
git status --short
~~~

Expected: full suite green, clean diff, clean worktree.

### Step 2: Push and open a draft PR

~~~powershell
git push -u origin codex/my-players
gh pr create --draft --base master --head codex/my-players --title "Add a browser-local My Players watchlist"
~~~

The PR body must include outcome, non-goals, exact test totals, browser results,
screenshots, analytics privacy, frozen-boundary confirmation, and the
local-only/cross-device limitation.

Stop with the draft PR open. Do not merge or deploy without owner approval.
