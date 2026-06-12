# ValuCast Launch Polish — 2026-06-12

Owner feedback pass before the public launch post. Six tasks. Repo:
`C:/Users/Alex/Documents/Codex/2026-05-18/league-values`, branch `master`, base = current
HEAD (`e7f1259` or later). Flask app, Jinja templates, vanilla JS/CSS only.

## Hard constraints (all tasks)

1. **Honesty.** Never invent composite numbers or unverifiable claims. Every displayed
   number must trace to a committed artifact or the engine. Label data sources and as-of
   dates where new surfaces appear. Never wording like "most accurate".
2. **Mobile first.** Every new/changed surface must work at 390px width. No horizontal
   overflow, touch targets ≥ 40px.
3. **Tests.** Every behavior change gets a test. Full suite (`PYTHONDONTWRITEBYTECODE=1
   PYTHONPATH=src:. python -m unittest discover -s tests`) must stay green (770 now).
4. **No runtime network calls.** The web app reads committed artifacts only. Fetch
   scripts are manual dev-machine tools.
5. **URL contract.** All existing query params keep working. New params are additive and
   shareable (state lives in the URL, like teams/budget/cats today).
6. **Perf.** Render free tier, ~30s request ceiling, cold starts. No chart libraries, no
   per-tile backdrop-filter. Anything computed per-request for the board must add
   < 300ms (cache by param tuple where needed — the feed is static per process).
7. **Two-way safety.** Player matching between the DD feed and projection stores MUST go
   through the existing safe matcher in `web/season_outlook.py` (name+team guarded).
   Never raw-name dict lookups (same-name collisions: the two Max Muncys are both in the
   feed).
8. **Don't touch:** `_shots*.py`, `_qa/`, `HANDOFF.md`, `.tmp-tests/` (untracked QA
   tooling); `data/dd/dd_dynasty_feed.json` (produced by another repo); deploy scripts.

---

## Task 1 — Statcast bars show raw values ("K% 22.1" not just a percentile circle)

Today `data/statcast/percentiles.json` stores only Savant percentiles
(`{"batters": {mlbam: {metric: pct}}, "pitchers": {...}}`) and
`templates/partials/_statcast_bars.html` renders label + percentile circle only.

a. **Extend `scripts/fetch_statcast_percentiles.py`** to also fetch raw metric values
   from Savant's custom leaderboard CSV:
   `https://baseballsavant.mlb.com/leaderboard/custom?year={Y}&type={batter|pitcher}&min=1&selections={comma-ids}&csv=true`
   (`min=1` so small samples — called-up prospects — are included). Map artifact metric
   keys → custom-leaderboard column ids. **Verified against the live endpoint 6/12 (do
   not re-probe):** batter ids `xwoba, xba, xslg, exit_velocity_avg,
   barrel_batted_rate, hard_hit_percent, k_percent, bb_percent, whiff_percent,
   oz_swing_percent (chase), sprint_speed` all return populated raw columns; pitcher
   adds `xera` and uses `fastball_avg_speed, fastball_avg_spin, curveball_avg_spin` —
   the percentile-CSV names `fb_velocity`/`fb_spin`/`curve_spin` come back EMPTY on the
   custom endpoint, so map them explicitly. For `xiso`/`xobp`/`oaa` try the literal ids;
   metrics whose column is missing or empty are simply omitted from raws (graceful).
   Write artifact v2:
   ```json
   {"source": ..., "year": ..., "as_of": ...,
    "batters": {"660271": {"xwoba": {"pct": 98, "raw": 0.412}, ...}}, "pitchers": {...}}
   ```
   Keep the refusal guard (don't write empty). DO NOT run the fetch against the network
   yourself — develop against a small fixture; the reviewer runs the real fetch.
b. **`web/statcast_store.py`** must read BOTH shapes (v1 int percentile, v2 dict) — the
   committed artifact stays v1 until the reviewer regenerates it, and tests cover both.
   `display_groups()` metric dicts gain `"raw"` (may be None) and `"display"` — a
   formatted string: 3-decimal leading-dot for xba/xwoba/xslg/xobp/xiso (".412"), one
   decimal + "%" for rate metrics ("22.1%"), one decimal + " mph" for velocity/EV, int
   + " rpm" for spin, one decimal + " ft/s" for sprint speed, signed int for OAA.
c. **`_statcast_bars.html`**: render the raw value right-aligned next to the metric
   label (e.g. "K % · 22.1%"), percentile circle unchanged. When raw is None, render
   exactly as today. Keep the existing CSS classes; add a `.pct-raw` class, muted color,
   `font-variant-numeric: tabular-nums`.
d. Tests: v1-shape artifact renders unchanged; v2-shape renders raw values; formatting
   table covered; missing-raw fallback covered.

## Task 2 — Statcast on prospect cards (called-up prospects have Savant data)

`app.py` `/player/<id>` prospect branch (`if dd_row.is_prospect:` around line 936) never
calls `_card_extras`, so prospect cards never get `statcast_groups`. Bolte (703607) IS in
the committed percentiles artifact — Savant includes non-qualifiers.

a. In the prospect branch, also run `find_outlook_projections(dd_row, store.get_all())`
   and, when a safe match with an mlbam id exists, build `extras = _card_extras(...)`
   exactly like the MLB branch. No match / no statcast → card renders exactly as today.
b. In `player_detail_dynasty.html`, render the statcast bars block for prospects AFTER
   the existing MiLB stats section, under a heading **"MLB Statcast"** with the
   artifact's as-of date and the caption "vs MLB league percentiles". Reuse
   `_statcast_bars.html` unchanged.
c. This must compose with Task 1 (raw values show here too).
d. Tests: prospect with statcast fixture → block renders with heading; prospect without
   → no block, no errors; the existing prospect-card tests stay green.

## Task 3 — Two-way (Ohtani) stat blocks: split Hitting / Pitching

Ohtani's dynasty card already merges hitting+pitching into single grids ("2026 Season
Outlook" shows PA…OPS and IP…K/9 interleaved). Pitching is present but visually buried.

a. In `web/season_outlook.py`, alongside the merged dict, expose the split: outlook /
   actuals / ROS each as `{"hitting": {...} | None, "pitching": {...} | None}` (presence
   = that pool matched). Don't break existing callers.
b. `player_detail_dynasty.html`: when BOTH hitting and pitching are present for a stat
   section, render two labeled sub-blocks ("Hitting", "Pitching") instead of one merged
   grid. Single-pool players render exactly as today (no visual change).
c. Redraft card (`partials/player_detail.html`): for a two-way player (both pools match
   by the shared base id — see `_merge_two_way_players` / season_outlook matching),
   render the other pool's projection line in a second labeled block.
d. Tests: Ohtani-like two-way fixture renders both sub-blocks in dynasty + redraft
   cards; single-pool fixtures unchanged.

## Task 4 — Dynasty mode: choose your scoring categories

The engine is already category-parameterizable (`web/category_registry.py` 26 cats,
`web/config_builder.py` parses `cats`/`pcats`, `src/league_values/engine.py` z-scores any
set). Dynasty mode bypasses it entirely and shows feed `dynasty_value` only.

Semantics (honesty constraint): we CANNOT re-derive dynasty_value for custom categories —
it's precomputed upstream. What we add is a **this-season value in YOUR categories**
alongside the dynasty value, never a fake "adjusted dynasty value".

a. **Setup UI** (`templates/partials/setup_dynasty.html`): add a "Scoring categories"
   section — preset chips (5x5 default, 6x6) + the hitting/pitching checklists, reusing
   the registry + the same form/param names as redraft (`cats`, `pcats`). Skip
   per-category weights in dynasty v1. Collapsed by default behind a "Customize
   categories" disclosure so the panel stays compact.
b. **Backend** (`app.py` `_build_dynasty_context`): when `cats`/`pcats` present and
   non-default, build a `LeagueConfig` via the existing builder (teams/budget from the
   dynasty LeagueSettings), run `engine.value_players` over the active projection store
   (same `_valuation_players` pool redraft uses), and map results onto MLB feed rows.
   **Batch the matching**: build the season_outlook match index ONCE per request (add a
   batch helper there if only a per-row function exists today), not per row. Cache the
   computed mapping per (cats, pcats, teams, budget) tuple with a small LRU — the stores
   are static per process.
c. **Board**: new column **"Now $"** (this-season auction $ in your categories) after
   the dynasty "$" column, only when custom cats are active. Prospects and unmatched
   players show "—". Sort toggle: "Rank by Dynasty $ / Now $" (URL param, default
   dynasty). Column header tooltip: "This season only, in your categories — Steamer".
d. **League summary line** (the URL-driven summary) includes the custom cats when
   active, e.g. "6x6 (OBP, QS)".
e. Tests: default = no Now $ column and zero engine calls; custom cats → column renders,
   values match an engine run with the same config; prospects show "—"; sort toggle
   orders by Now $; URL params round-trip; the cache returns the same object for
   repeated identical requests.

## Task 5 — Liquid glass: make it visible

Current `.glass` (style.css ~1025): `rgba(26,27,46,.72)`, `blur(14px) saturate(140%)`,
border `rgba(255,255,255,.06)`. Verdict from the owner: "almost too subtle". Root cause:
the page background is flat near-black, so the blur has nothing to refract.

a. **Ambient background field**: a fixed, non-interactive layer behind all content
   (e.g. `body::before`) with 3 large soft radial-gradients — blue (top-left), violet
   (right), teal (bottom) — each alpha ≤ 0.14 against the dark base so text contrast is
   unaffected. Pure CSS gradients (no images, no filter blur on the layer itself),
   `pointer-events: none`, behind everything, `transform: translateZ(0)`.
b. **Stronger glass tokens**: background alpha .72 → ~.58, blur 14 → 20px, saturate 140
   → 170%, border → `rgba(255,255,255,.12)`, add inset top highlight
   (`inset 0 1px 0 rgba(255,255,255,.08)`) and a soft drop shadow
   (`0 8px 32px rgba(0,0,0,.35)`). Keep the `@supports not (backdrop-filter…)` opaque
   fallbacks in sync.
c. **Readability gate**: sticky table headers and toolbars must stay readable with rows
   scrolling beneath — if contrast suffers at .58, raise that surface's alpha
   individually rather than reverting the whole effect. Never apply glass per-tile
   (existing perf rule).
d. Tests: existing glass-class assertions stay green; add one asserting the ambient
   layer CSS exists (cheap regression pin: selector present in compiled stylesheet
   response or static file).

## Task 6 — Value Map (market landscape)

New page: dynasty value vs age scatter — the "where is the market" picture. (DD's
"value map" is a team-pair trade heatmap; ValuCast has no multi-team rosters, so the
correct analog is the player landscape. Trends/history = separate future spec; do NOT
build snapshot infrastructure.)

a. **Route `/map`** (full page, shares base layout/nav): server embeds a slim JSON
   (id, name, age, dynasty_value, primary position group, player_type, prospect_rank)
   for all feed rows with age + value present; client renders an **SVG scatter** with
   vanilla JS. X = age, Y = dynasty value. Color by group: hitters blue, SP violet, RP
   teal, prospects green. Radius ~3px desktop / 4px mobile; top-12-by-value labeled
   directly (collision-nudged or it gets messy — cap labels, never overlap).
b. **Interactions**: hover (desktop) / tap (mobile) → glass tooltip with name, pos, age,
   value; tap-again or tooltip link navigates to the right board with `search=<name>`.
   Filter chips: All / MLB / Prospects + the position dropdown (same options as boards).
   No libraries, no canvas, no zoom — keep it simple and fast (~1.5k circles is fine in
   SVG).
c. **Navigation**: "Map" link in the dynasty + prospects toolbars (and map links back).
   Subtitle: "Dynasty value vs age · {N} players · updated {feed generated_at date}".
d. Mobile: full-width, height ~70vh, axis labels legible, tooltip never clipped at
   edges.
e. Tests: route 200 + embeds N players matching the store; JSON slimming drops
   null-age/value rows; toolbar link present in dynasty/prospects board responses.

## Task 7 — Shareable card links (small)

`/player/<id>` hit directly (no `HX-Request` header) returns a bare unstyled partial.
Redirect non-htmx GETs 302 → `/?mode={mode}&search={player name}` so deep links land on
the styled board with the player findable. htmx behavior unchanged. Test both paths.

---

## Self-verify before returning

- Full suite green; list any new test files.
- `python -m py_compile` on every touched .py.
- Grep your diff for: raw-name dict lookups against feed names (forbidden — Task 7
  constraint), `Date.now`-style nondeterminism in JS you add (fine to use, just no test
  reliance), chart library imports (forbidden).
- Summarize per task: files touched, behavior, tests added.
