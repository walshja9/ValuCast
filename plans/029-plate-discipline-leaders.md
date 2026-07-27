# Plan 029: Plate-Discipline Leaders — a public, server-rendered per-level leaders board over the shipped pitch-discipline artifact ("lowest chase rate in AA, min 300 pitches"), rankable metrics only, est./measured honesty carried through, season-to-date V1

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> ```
> git log -1 --format=%h    # baseline for this plan is 32b9b265
> git diff --stat 32b9b265..HEAD -- app.py web/pitch_discipline_store.py templates/partials/_footer_provenance.html templates/methodology.html templates/cards.html static/style.css data/models/valucast_pitch_discipline.json
> git status --short
> ```
> This plan was written against `32b9b265` (2026-07-12). All "Current state"
> line refs are accurate to that commit. If any in-scope file changed since,
> re-read the cited excerpt against the live code before proceeding; on a
> mismatch with an excerpt, treat it as a STOP condition. In particular the
> store (`web/pitch_discipline_store.py` — the whole file is a reuse surface),
> the PNG cache-key config (`_PNG_CACHE_PARAMS`, app.py:154-162 +
> `_png_cache_key`, app.py:192-202), the param-validation idiom
> (`_parse_spark_window`, app.py:8083-8088), and the footer/gallery surfaces
> (`_footer_provenance.html`, `cards_gallery()` app.py:8009-8072) are the
> load-bearing reuse surfaces — re-verify them at HEAD.
>
> **This is a NEW-FEATURE / new-read-surface plan.** It adds ONE new route, a
> THIN extension to an existing fail-soft store, ONE server-rendered template,
> footer/gallery linkage, and (cut-candidate) ONE PNG share card. It writes NO
> new build script and NO new committed artifact — it reads the artifact plan
> 023 already ships daily. Nothing here is frozen-file-blocked. Master
> auto-deploys valucast.app via Render, so do NOT push; the reviewer gates the
> push.

## Status

- **Implementation update (2026-07-27)**: implemented on
  `codex/discipline-leaders`; review is pending. Launch verification reproduced
  an existing operational defect: the daily workflow never restored the raw
  pitch-event cache, so the builder cold-skipped and left this board stale.
  The branch therefore makes one explicit deviation from the original
  "NO YAML change" constraint: a pinned `actions/cache` restore/bootstrap/save
  sequence that preserves resumable partial backfills and marks the cache ready
  only after a successful full build. This does not change model, rank, value,
  or publication logic.
- **Priority**: P3 (discretionary product/social surface — not a correctness or
  honesty leak; runs AFTER the current post-7/13 stack). Competitive origin:
  ProspectsLive shipped a generic stat-leaders view on 7/12. The generic version
  is commodity (Savant/FanGraphs territory) — but **discipline leaders below AAA
  are renderable by NOBODY else**: no public pitch-level discipline data exists
  at AA/A+/A except the artifact plan 023 built. The page's second job is a
  self-refreshing stream of social post material ("lowest chase rate in AA,
  min 300 pitches").
- **Effort**: **S–M**. The artifact already holds everything a board needs
  (rates + cohort percentiles + qualifies flags + orientation metadata) — the
  work is a store extension (~2 methods), one route + context builder, one
  template reusing existing board/pill/est-tag CSS, footer links, a methodology
  sentence, and tests. The **cut-to-S lever is the PNG share card** (Step 5):
  the board page stands alone; the PNG (+ its `_PNG_CACHE_PARAMS` entry + its
  cache-key tests + the cards-gallery tile, which travel together) can be
  dropped or deferred without touching the core. **The PNG is the social
  payload, so prefer shipping it** — but it cuts cleanly.
- **Risk**: LOW. Serving stays network-free (reads the committed artifact via
  the existing fail-soft store contract). The sharp edges are all honesty/
  invariant edges, not correctness: (a) **floor honesty** — only `qualifies`
  buckets may rank (the artifact carries the flag; a naive iteration over
  `players` would rank 394 sub-floor buckets alongside qualified ones);
  (b) **orientation honesty** — only the 4 artifact-oriented metrics get
  "leader" framing; the 3 contextual metrics are NOT leaderboards; (c) **the
  est./measured split** — per-bucket `zone_estimated`, not per-metric hardcode
  (AAA zone metrics are MEASURED in the live artifact); (d) **the PNG cache
  key** — if the PNG ships, `level`/`metric` MUST enter `_PNG_CACHE_PARAMS`
  (plan 007/022 invariant; the trade-page cache-poisoning history is the
  cautionary tale).
- **Depends on**: **plan 023 (SHIPPED 7/10, live)** — the committed artifact
  `data/models/valucast_pitch_discipline.json` (1,322 players, per-level
  buckets) and `web/pitch_discipline_store.py`. This is the "leaderboard
  fast-follow" 023's Non-goals section explicitly anticipated ("a board is a
  natural fast-follow once the artifact is proven"). The artifact is now
  proven. Coordinates with nothing frozen. No conflict with 028 (model
  surgery touches the rank artifact, never the discipline artifact) or 027
  (glossary reads `pitch_discipline_store._DEFAULT_LABELS` — this plan must
  not rename it).
- **Category**: feature (product — public leaders board + social share surface).
- **Planned at**: commit `32b9b265`, 2026-07-12.
- **Execution window**: **post-7/13, after the current stack** (016/017, 028,
  and the other authored batch-3 plans take precedence). Discretionary — slot
  it into a spare half-session.

## Why this matters

Plan 023 built the only public pitch-level discipline dataset below AAA and put
it on individual player cards. A card answers "how disciplined is THIS guy?" —
a leaders board answers "who are the MOST disciplined guys at this level?",
which is (a) the shape prospect Twitter actually argues in, and (b) the exact
view a generic stat-leaders page (ProspectsLive, 7/12) cannot render below AAA
because the underlying data does not publicly exist. Every daily artifact
refresh mints a new set of postable claims ("lowest chase rate in AA, min 300
pitches") with zero manual work — the page IS the receipts for those posts.

The honesty bar is inherited from 023 and this plan carries every piece of it
through to the board surface:

1. **Only qualifying buckets rank.** The 300-pitch floor is already in the
   artifact (`qualifies` flag, `cohorts.min_pitches`); the board states it
   on-page and below-floor players NEVER appear.
2. **Only metrics with a defensible quality direction get "leader" framing.**
   The artifact itself makes this call (`cohorts.lower_is_better` /
   `higher_is_better` cover exactly 4 of 7 metrics); Swing%, Zone%, Z-Swing%
   are contextual and are NOT boards.
3. **est. vs measured carries through per bucket, not per metric.** AA/A+/A
   zone metrics are pixel-calibration estimates (tagged "est." + methodology
   link, exactly like the cards); AAA zone metrics are measured from real
   pX/pZ (`zone_estimated: false` in the live artifact) and must NOT be
   over-hedged with a false est. tag.
4. **Per-level, never blended.** Cohort size shown, as-of date shown,
   provenance line shown.
5. **Observe-only stands.** No value/rank implication, no wiring into scoring —
   the same `milb_translation` precedent as the parent plan. The board shows
   discipline numbers and links to cards; it never shows a dynasty value/rank
   column.

## Current state

Verified against the live files/artifact at `32b9b265`. Read each cited line
yourself before building on it.

### The artifact — everything a board needs is already committed

`data/models/valucast_pitch_discipline.json` (as_of `2026-07-10`,
schema_version 1, season 2026, source `mlb_statsapi_play_by_play`):

- **Top-level keys**: `artifact`, `as_of`, `cohorts`, `estimated_metrics`,
  `exact_metrics`, `generated_at`, `metric_labels`, `players`,
  `schema_version`, `season`, `source`, `source_policy`.
- **`players`**: 1,322 entries keyed by **stringified mlbam id**. Each entry is
  a dict of level → bucket ONLY — **there is NO name/team field anywhere in
  the artifact** (verified: entry keysets are pure level-key tuples like
  `("AA","AAA")`). A public board therefore needs a serve-time mlbam → name
  join (see "Name resolution" below).
- **Bucket shape** (one canonical schema across all 1,740 buckets, verified by
  full scan): `counts` (11 raw ints), `rates` (all 7 keys always present:
  `chase_pct, swing_pct, swstr_pct, whiff_pct, z_contact_pct, z_swing_pct,
  zone_pct` — floats rounded to 1dp), `percentiles` (either `{}` or exactly
  `{chase_pct, swstr_pct, whiff_pct, z_contact_pct}`), `pitches` (int),
  `qualifies` (bool), `zone_estimated` (bool).
- **The floor is enforced in the data**: `qualifies=false` on 394/1,740 buckets
  (22.6%) and in EVERY one of those `percentiles == {}` (verified, 0
  mismatches) — but `rates`/`counts` are still populated on sub-floor buckets,
  so **a board iterating `players` MUST filter on `qualifies` explicitly** or
  it will rank sub-floor players.
- **`cohorts`** (the block the board's honesty copy reads):
  `min_pitches: 300`; `cohort_sizes: {"A": 439, "A+": 418, "AA": 339,
  "AAA": 150}`; **`lower_is_better: ["chase_pct","swstr_pct","whiff_pct"]`**;
  **`higher_is_better: ["z_contact_pct"]`**; `zone_metrics_shipped: true`;
  `calibration: {a,b,c,d, fit_r2 0.9427, held_out_agreement_pct 97.3,
  n_pairs 514193, passes_quality_gate true, ...}`.
- **The rankable set is exactly 4 metrics** — the union of the two orientation
  lists — and it coincides exactly with the set that ever gets a `percentiles`
  entry. `swing_pct`, `z_swing_pct`, `zone_pct` have NO percentile and NO
  orientation anywhere in the file: the artifact deliberately declined to
  judge them. **The board must inherit that refusal** (constraint: contextual
  metrics are not leaderboards).
- **`zone_estimated` is per-bucket and level-dependent in practice**: AAA
  buckets carry `zone_estimated: false` (real tracked pX/pZ), AA/A+/A carry
  `true` (pixel calibration). So a Chase% board at AA is estimated ("est."
  tag) while the same metric at AAA is measured (no tag) — exactly the
  graduation path 023's maintenance notes describe.
- **`metric_labels`** (top-level): `{chase_pct: "Chase%", swing_pct: "Swing%",
  swstr_pct: "SwStr%", whiff_pct: "Whiff%", z_contact_pct: "Z-Contact%",
  z_swing_pct: "Z-Swing%", zone_pct: "Zone%"}`.
- **`source_policy`**: `{observe_only: true, feeds_rank: false, feeds_value:
  false, exit_velocity: false}` — declarative, not code-enforced; this plan
  must honor it manually (no value/rank framing on the board).
- **Percentiles are quality-oriented** (023 Step 4): higher pct = better for
  every rankable metric (e.g. AAA sample: chase 24.6% → pct 76). So on a
  correctly-ordered board the #1 row carries the highest cohort percentile —
  a useful cross-check assertion for the tests.

### The store — fail-soft but per-player-only; the board needs a thin extension

`web/pitch_discipline_store.py`:

- **`PitchDisciplineStore`** (line 46), instantiated once at app.py:414
  (`pitch_discipline_store = PitchDisciplineStore()`). Keyed by
  `str(mlbam_id)` (line 96). Fail-soft `_ensure_loaded` (lines 56-77):
  `(OSError, ValueError)` → empty store; wrong-shaped JSON degrades key by
  key. `as_of` property (lines 78-81).
- **`groups_for(mlbam_id)` (line 83) is the ONLY accessor** — a single-player
  lookup returning card-ready per-level groups. Its `_metric_row` builds
  `{key, label, raw, display, pct, estimated, color}` per metric — **read it
  and mirror its `estimated` derivation** (metric-in-estimated-set AND the
  bucket's `zone_estimated`) so the board and the cards can never disagree
  about what is an estimate.
- **Two gaps the board must fill, both as THIN extensions to this store**
  (constraint 6: "the existing PitchDisciplineStore or a thin extension"):
  1. **No cross-player iteration** — `_players` is private with no enumerator.
     Bypassing the store to read the raw JSON in app.py would fork the
     fail-soft contract; extend the store instead.
  2. **The store drops `cohorts` on load** — `_ensure_loaded` reads only
     `players`/`metric_labels`/`as_of`. The board needs `min_pitches`,
     `cohort_sizes`, and the orientation lists; the extension must load and
     expose the `cohorts` block.
- **`_DEFAULT_LABELS` (lines 35-39)** is labels-only (no orientation) and is a
  named import surface in authored plan 027's coverage union — extend around
  it, do NOT rename it.
- Existing call sites (do not disturb): app.py:2907
  (`_prospect_player_card_png` discipline strip via
  `_prospect_discipline_card_rows`, app.py:2846, metric subset at :2843) and
  app.py:8582 (card context `plate_discipline`, observe-only comment at
  :8579-8581).

### The param-validation precedent — `_parse_spark_window`, and the `A+` URL trap

- **The exact shape to copy for `?level=` / `?metric=`** is the Movers window
  param (app.py:8083-8088):
  ```python
  def _parse_spark_window(raw) -> int | None:
      try:
          value = int(raw)
      except (TypeError, ValueError):
          return None
      return value if value in SPARK_WINDOW_CHOICES else None
  ```
  with `SPARK_WINDOW_CHOICES = (7, 14, 21, 30)` (app.py:8077),
  `DEFAULT_MOVER_WINDOW = 14` (app.py:8080), and the route applying
  `_parse_spark_window(request.args.get("window")) or DEFAULT` (app.py:7430-
  7434). Parse → membership in a small fixed vocabulary → `None` on miss →
  default. Junk input can never 500 and never reaches a file path or a
  template unvalidated. This is the injection/path-traversal discipline
  constraint 8 asks for: **the raw query value is only ever used as a dict
  key against a hardcoded allowlist mapping** — the artifact-level string the
  code actually uses comes from OUR map, never from the request.
- **The `A+` trap (load-bearing)**: the artifact's level keys are `"AA"`,
  `"A+"`, `"A"`, `"AAA"`. A literal `?level=A+` in a URL form-decodes the `+`
  as a SPACE — the server receives `"A "` and the allowlist misses. **Use
  URL-safe slugs in the query string** (`aa`, `a-plus`, `a`, `aaa`) mapped to
  artifact keys server-side. Same treatment for metrics (`chase`, `whiff`,
  `swstr`, `z-contact` → `*_pct` keys) for symmetric, clean, shareable URLs.
- **The URL-driven pill toggle precedent** is the Movers window pills
  (templates/movers.html:36-41): plain server-rendered `<a>` links with
  `class="bf-pill{% if active %} is-active{% endif %}"` inside
  `<nav class="bf-filter-pills ledger-pills">` — no JS, state entirely in the
  URL (`.bf-pill` CSS at static/style.css:4530-4547). This is exactly the
  shareable-URL pattern for the level row and the metric row.

### Name resolution — the artifact has no names; `dd_store` has the join

- `PublicSnapshotRow.mlbam_id: str | None` (web/public_snapshot_models.py:74,
  coerced to str at :742). The card context already joins on it
  (app.py:8582 uses `getattr(dd_row, "mlbam_id", None)`).
- **The memoization precedent to copy** is `_VALUE_MAP_CACHE` /
  `_value_map_payload()` (app.py:6754-6772): a module-level
  `(generation_key, payload)` tuple swapped atomically, keyed on
  `dd_store.generated_at`, rebuilt only on a daily refresh. Build the
  mlbam → row map the same way (iterate `dd_store.get_all()` once per
  generation; do NOT scan per request-row).
- **Deep-link target**: `/player/<player_id>` (route at app.py:8640) where
  `player_id` is the dd_store row id — the template-context helper
  `player_detail_url` (app.py:5972) is the URL grammar reference
  (`f"/player/{quote(str(player_id), safe='')}?mode=prospects"`).
- **The join can miss** (a player graduated/dropped from the universe between
  artifact build and serving). The leaders claim ("lowest chase rate in AA")
  is only honest over the FULL qualifying cohort — **never silently drop an
  unresolved row from the ranking**. Render it with the fallback label
  `MLBAM <id>` and no link; if any are present, a fineprint line discloses
  the count. Expected to be rare (the artifact is built FROM the tracked
  universe).

### The PNG cache invariant — plan 007/022, with the test pattern to mirror

- `_PNG_CACHE_PARAMS` (app.py:154-162) is the fixed frozenset allowlist;
  `_png_cache_key()` (app.py:192-202) keys on `(generation, path,
  allowlisted-params-only)`. **Any param not in the allowlist is silently
  dropped from the key** — if the leaders PNG ships reading `level`/`metric`
  without adding them, every level/metric combination collapses to ONE cache
  key and the first-rendered card is served to everyone (the exact cross-user
  poisoning plan 007 documents and plan 022 had to guard for `give`/`get`).
  The `give`/`get` entry at app.py:158-161 carries the comment convention to
  follow (`# plan 029: ...`).
- **The three-test pattern to mirror** is in tests/test_app.py:
  `test_trade_png_cache_key_distinguishes_trades` (:1703-1712 — different
  params → different keys), `test_trade_png_cache_key_stable_for_same_trade`
  (:1714-1720 — same params → same key), and
  `test_give_get_in_png_cache_vocabulary` (:1722-1725 — the literal
  allowlist membership). Write the same trio for `level`/`metric` IF the PNG
  ships.
- **Side note (flag, don't fix)**: `window` is NOT in `_PNG_CACHE_PARAMS`
  today — if the movers PNG ever reads it, that is a separate pre-existing
  gap; out of scope here. Also note: adding `level`/`metric` to the global
  allowlist means stray `level`/`metric` params on OTHER PNG routes now enter
  their cache keys — harmless key fragmentation, not poisoning (same
  situation as `give`/`get`).
- **PNG construction precedents** (if Step 5 ships): 1080x1350 RGB Pillow,
  `_graphic_fill_background` → `_graphic_header(...)` (app.py:2198 signature)
  → panels → `_graphic_footer(...)` (app.py:2222, SHARED — never change its
  signature) → `img.save(..., "PNG", optimize=True)`;
  `_receipts_share_card_png` / `_movers_share_card_png` are the list-layout
  exemplars; **every drawn string ASCII-only** (`" - "`, never em-dashes /
  middot — app.py:7246-7247 documents why); route return pattern =
  `make_response(png)` + `Content-Type: image/png` + inline
  `Content-Disposition` (no manual `Cache-Control` — `_maybe_cache_png`
  injects it).

### Nav, gallery, design tokens, methodology, empty state — all precedents live

- **Footer (the primary linkage)**: `templates/partials/_footer_provenance.html`
  (included at base.html:44) — a conditional chain of ~4 page-mode branches,
  each a dash-joined link list (e.g. line 22: `Back to board - Intelligence
  Hub - The Ledger - ... - The Second Opinion`). Add the leaders link to ALL
  branches (the file deliberately duplicates per mode — match it, don't
  refactor it).
- **Cards gallery**: `cards_gallery()` (app.py:8009-8072) builds an `entries`
  list of dicts (`title`, `caption`, `page_url`, `png_url`, `board_url`,
  `generated_at`) rendered as `.card-tile.glass` articles
  (templates/cards.html:22-33). **A gallery tile requires a `png_url`** — so
  the gallery entry ships WITH the PNG (Step 5) and is cut with it.
- **NOT a primary-nav tab**: `templates/partials/_board_nav.html`
  (`horizon-tabs` macro) already runs 11 tabs and has a documented mobile
  overflow patch (style.css ~4210-4236). Nav diet precedent (plan 022): do
  NOT add a tab; footer + gallery only. Promoting it is Alex's call — flag,
  don't do.
- **Design tokens**: board table = `.rankings-table` + `col-*` column classes
  (static/style.css:856-912, markup precedent
  templates/partials/rankings_table.html:6); section wrapper = `.glass`
  (style.css:2139-2148 — floating surfaces only, never per-tile); pills =
  `.bf-pill` / `.ledger-pills` (style.css:4530-4547); **the est. tag already
  exists as `.pd-est-tag` / `.pd-est-inline`** (style.css:1636-1645, built by
  plan 023 for the cards) — reuse it, do not invent a new class.
- **Methodology anchor confirmed**: `templates/methodology.html:364-366` has
  `<section id="plate-discipline">`. The board's est. tags and methodology
  link point at `/methodology#plate-discipline`, same as the cards.
- **Empty-state precedent**: templates/gaps.html:36-40 gated by a
  server-computed `gaps_available` bool (app.py:7617, `bool(higher or lower)`)
  rendering an honest `.glass` "unavailable — populates after the next daily
  build" section instead of a blank table or a 500. Copy the shape
  (`leaders_available`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Store tests (incl. new leaders methods) | `python -m pytest -q tests/test_pitch_discipline_store.py` | all pass |
| App/route tests | `python -m pytest -q tests/test_app.py -k "discipline or leaders"` | all pass |
| Store leaders smoke | `python -c "import app; s=app.pitch_discipline_store; b=s.leaders('AA','chase_pct'); print(bool(b), b['cohort_size'] if b else None, len(b['rows']) if b else 0)"` | `True 339 25` (numbers per live artifact) |
| Cohort meta smoke | `python -c "import app; print(app.pitch_discipline_store.cohort_meta().get('min_pitches'))"` | `300` |
| Page renders (default AA chase) | `python -c "import app; c=app.app.test_client(); r=c.get('/discipline-leaders'); print(r.status_code, b'Chase%' in r.data, b'min 300' in r.data or b'300 pitches' in r.data)"` | `200 True True` |
| Slugged params validate | `python -c "import app; c=app.app.test_client(); print(c.get('/discipline-leaders?level=a-plus&metric=whiff').status_code, c.get('/discipline-leaders?level=../etc&metric=DROP').status_code)"` | `200 200` (junk falls back to defaults, never 500) |
| est. split renders honestly | `python -c "import app; c=app.app.test_client(); aa=c.get('/discipline-leaders?level=aa&metric=chase').data; aaa=c.get('/discipline-leaders?level=aaa&metric=chase').data; print(b'est.' in aa, b'est.' in aaa)"` | `True False` (AA estimated, AAA measured) |
| Template smoke | `python -c "import jinja2; jinja2.Environment(loader=jinja2.FileSystemLoader('templates')).get_template('discipline_leaders.html')"` | no exception |
| PNG renders (only if Step 5 ships) | `python -c "import app; png=app._discipline_leaders_share_card_png('AA','chase_pct'); print(len(png))"` | non-zero byte count, no exception |
| PNG cache vocabulary (only if Step 5 ships) | `python -c "import app; print('level' in app._PNG_CACHE_PARAMS, 'metric' in app._PNG_CACHE_PARAMS)"` | `True True` |
| Full suite (final gate) | `python -m pytest -q` | all pass, 0 fail (>= the count at HEAD; plans 022/023 gated ~1,871+); then restore the byproduct (below) |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | file back to HEAD (pytest dirties it — NEVER commit it) |

## Scope

**In scope** (the only files you create or modify):

- **`web/pitch_discipline_store.py`** — thin, additive extension of
  `PitchDisciplineStore`: load the `cohorts` block in `_ensure_loaded`
  (currently dropped), add `cohort_meta()` and `leaders(level, metric,
  limit=25)` (Step 1). NO change to `groups_for`/`_metric_row` behavior; do
  NOT rename `_DEFAULT_LABELS` (plan 027 imports it).
- **`app.py`** — (i) slug allowlist constants + parse helpers (Step 2);
  (ii) `_discipline_leaders_context(args)` + the `/discipline-leaders` route;
  (iii) the generation-keyed mlbam → dd_store-row map (mirroring
  `_VALUE_MAP_CACHE`); (iv) IF Step 5 ships:
  `_discipline_leaders_share_card_png(...)`, the
  `/discipline-leaders/share-card.png` (+ HTML preview) routes, the
  `"level", "metric"` add to `_PNG_CACHE_PARAMS`, and one `entries` dict in
  `cards_gallery()`. No cache/scoring region touched beyond that one
  allowlist line.
- **NEW `templates/discipline_leaders.html`** — the board page (extends
  base.html; gaps/movers skeleton).
- **`templates/partials/_footer_provenance.html`** — the leaders link added to
  each page-mode branch.
- **`templates/methodology.html`** — 2-3 sentences appended INSIDE the
  existing `#plate-discipline` section (no new anchor needed).
- **`static/style.css`** — minimal additions only; reuse `.rankings-table`,
  `.glass`, `.bf-pill`/`.ledger-pills`, `.pd-est-tag`/`.pd-est-inline`.
- **Tests**: additions to `tests/test_pitch_discipline_store.py` (leaders +
  cohort_meta against a fixture artifact) and `tests/test_app.py` (route,
  params, est. split, empty state; PNG cache-key trio if Step 5 ships).

**Cut line to hold Effort at S (the reviewer decides at execution time):**

- **CORE (must ship): Steps 0-4 + 6** — store extension, route + context,
  template with all honesty features (floor line, cohort size, as-of,
  provenance, est. tags, per-level pills), footer links, methodology note,
  tests. This IS the product.
- **CUT-CANDIDATE: Step 5 (the PNG + everything that travels with it)** — the
  `_PNG_CACHE_PARAMS` add, the cache-key test trio, the og_image blocks, and
  the cards-gallery tile all ship together or defer together. **If the PNG is
  cut, do NOT add `level`/`metric` to `_PNG_CACHE_PARAMS`** (no cache params
  for a route that doesn't exist) and say so in the status row. Prefer
  shipping it — the PNG is the social payload.
- There is no secondary cut. If the core is somehow over budget, the plan was
  mis-scoped — STOP and report rather than cutting an honesty feature.

**Out of scope** (do NOT touch):

- **Time-windowed leaders (7d/30d)** — V1 is SEASON-TO-DATE ONLY. The
  committed artifact holds season aggregates per level; windows require
  per-game history, which lives only in the UNCOMMITTED local pitch cache
  (plan 023's 2b size decision — ~350MB at full scale, gitignored). **Do NOT
  reopen that decision here.** Windows are an explicit fast-follow tied to
  the discipline CI-refresh work (see Non-goals).
- **The build script / artifact schema** — `scripts/build_pitch_discipline.py`,
  `scripts/validate_pitch_discipline.py`, the daily-build wiring, and the
  artifact file itself. The board reads what 023 ships; adding fields (e.g.
  names) to the artifact is a different plan.
- **`prospects/pitch_discipline.py`** — the pure counting module; nothing here
  needs it.
- **Contextual metrics as boards** — `swing_pct`, `z_swing_pct`, `zone_pct`
  get NO leaders surface (see Step 2's decision note).
- **The valuation / scoring math** — observe-only stands
  (`source_policy.feeds_rank/feeds_value: false`). No dynasty value or rank
  column on the board; no discipline number into any score.
- **The scouting-read text path** — card-bars/board-only, same as 023.
- **`_board_nav.html` / `site-nav`** — no new tab (nav diet; Alex's call).
- **Frozen files** — `prospects/ahead_of_consensus.py`,
  `scripts/build_ahead_of_consensus_scorecard.py`. This plan does not need
  them.
- **Per-source ranks** — irrelevant to this page; do not add any (house ToS
  rule).
- **DD (`dd_*`) feeds** — the name join reads `dd_store` (the ValuCast public
  snapshot store), never `data/dd/*`.

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT
  push**: master auto-deploys valucast.app via Render. Commit locally; the
  reviewer gates the push.
- NEVER `git add -A` or `commit -am`. Stage each in-scope file explicitly by
  path. **Never `git stash`.**
- Do NOT stage `data/prediction_archive/.../2026-06-15.json` (pytest
  byproduct — restore it via `git checkout --` after the suite) or any
  untracked `data/dd/*` / local pitch-cache files.
- Commit message style (short imperative subject), e.g.
  `Add Plate-Discipline Leaders board (/discipline-leaders): per-level rankable-metric leaders over the discipline artifact + share card`.

## Steps

### Step 0: Confirm the reuse surfaces are live before building

```
# The artifact is committed, has players + the cohorts orientation lists:
python -c "import json; d=json.load(open('data/models/valucast_pitch_discipline.json', encoding='utf-8')); print(len(d['players']), d['cohorts']['min_pitches'], d['cohorts']['lower_is_better'], d['cohorts']['higher_is_better'])"
# expect: 1322-ish, 300, ['chase_pct','swstr_pct','whiff_pct'], ['z_contact_pct']
# The store exists, is fail-soft, and has NO leaders method yet:
python -c "from web.pitch_discipline_store import PitchDisciplineStore as S; s=S(); print(hasattr(s,'groups_for'), hasattr(s,'leaders'), hasattr(s,'cohort_meta'))"
# expect: True False False   (Step 1 adds the two)
# The param-validation + memoization precedents exist:
python -c "import app; print(callable(app._parse_spark_window), app._VALUE_MAP_CACHE is not None)"
# expect: True True
# level/metric are NOT in the PNG cache vocabulary (Step 5 adds them IF the PNG ships):
python -c "import app; print('level' in app._PNG_CACHE_PARAMS, 'metric' in app._PNG_CACHE_PARAMS)"
# expect: False False
# No /discipline-leaders route yet:
python -c "import app; print([r.rule for r in app.app.url_map.iter_rules() if 'discipline' in r.rule])"
# expect: []
# The methodology anchor + the est-tag CSS exist:
grep -c "plate-discipline" templates/methodology.html && grep -c "pd-est-tag" static/style.css
# expect: >=1 and >=1
```
**Verify**: all confirm the state above. If a leaders method or route already
exists, someone landed here first — STOP and reconcile.

### Step 1: The store extension — `cohort_meta()` + `leaders(level, metric)`

Additive changes to `web/pitch_discipline_store.py`, preserving the fail-soft
contract exactly (a missing/malformed artifact degrades to empty returns,
never an exception):

**1a — Load `cohorts` in `_ensure_loaded`.** Alongside the existing
`players`/`metric_labels`/`as_of` reads, keep `self._cohorts = raw.get(
"cohorts") if isinstance(raw.get("cohorts"), dict) else {}` (and reset to `{}`
on the failure paths). Also keep `self._estimated_metrics` from the top-level
`estimated_metrics` list (defaulting to the same tuple `_metric_row` already
uses — read the live code and reuse its source of truth rather than
introducing a second list).

**1b — `cohort_meta()`** — returns the loaded block (or `{}`):
`{"min_pitches", "cohort_sizes", "lower_is_better", "higher_is_better"}` plus
`as_of` passthrough if convenient. Pure read, no computation.

**1c — `leaders(level, metric, *, limit=25)`** — the board query. Contract:

```python
def leaders(self, level: str, metric: str, *, limit: int = 25) -> dict | None:
    """Ranked qualifying buckets for one level x one rankable metric.

    Returns None when the artifact is empty/unloadable, the level is unknown,
    or the metric is not in the artifact's orientation lists (the artifact —
    not this code — decides what is rankable). Otherwise:
    {"level", "metric", "label", "as_of", "direction": "asc"|"desc",
     "min_pitches", "cohort_size", "total_qualifying", "estimated" (any row),
     "rows": [{"mlbam_id", "raw", "display", "pct", "pitches",
               "zone_estimated", "estimated"}, ...]}   # len <= limit
    """
```

Rules (each is a test in the Test plan):
- **Rankable gate**: `metric` must be in `cohort_meta()`'s
  `lower_is_better + higher_is_better`. Anything else (including the three
  contextual metrics and junk) returns `None` — the orientation lists in the
  ARTIFACT are the source of truth; do NOT hardcode a metric judgment the
  artifact didn't make, and do NOT fall back to a guess if the lists are
  missing (missing lists → `None` → the page renders its empty state).
- **Floor gate**: iterate `self._players`; include a bucket ONLY when
  `bucket.get("qualifies") is True` and the metric's rate is not None.
  Sub-floor buckets never enter the pool (394 of 1,740 buckets in the live
  artifact are sub-floor with fully-populated rates — this filter is the
  whole floor-honesty defense).
- **Ordering**: ascending for `lower_is_better` metrics (lowest Chase% =
  rank 1), descending for `higher_is_better` (highest Z-Contact% = rank 1).
  Deterministic tie-break: `(oriented_rate, -pitches, mlbam_id)` so equal
  rates rank the larger sample first and the output is stable across runs.
- **Per-level isolation**: only the requested level's bucket per player. A
  player qualifying at AA and AAA appears on BOTH boards, each with that
  level's numbers — never a blend, never a "best level" pick.
- **est. derivation**: per-row `estimated = (metric in estimated set) and
  bool(bucket.get("zone_estimated"))` — the SAME derivation `_metric_row`
  uses (read it; mirror it; do not fork it). Group-level
  `estimated = any(row estimated)`.
- **`pct`**: the bucket's committed cohort percentile for the metric (present
  on every qualifying bucket for all four rankable metrics), clamped/coerced
  the same way `_metric_row` does. `display` = the store's existing rate
  formatting (1dp + `%`).
- **`total_qualifying`**: the size of the filtered pool (for the "top 25 of N
  qualifying" line); `cohort_size` from `cohorts.cohort_sizes[level]` (the
  build-time cohort — expected to equal `total_qualifying`; if they diverge,
  serve `total_qualifying` in the ranking copy and keep `cohort_size` as
  metadata, do not fabricate agreement).

**Verify**:
- The store-leaders smoke command (Commands table) → `True 339 25` shapes.
- `python -c "from web.pitch_discipline_store import PitchDisciplineStore as S; s=S(path='nonexistent.json'); print(s.leaders('AA','chase_pct'), s.cohort_meta())"` → `None {}` (fail-soft).
- `python -c "import app; s=app.pitch_discipline_store; print(s.leaders('AA','swing_pct'), s.leaders('ZZ','chase_pct'))"` → `None None` (contextual metric refused; unknown level refused).
- Ascending check: `python -c "import app; r=app.pitch_discipline_store.leaders('AA','chase_pct')['rows']; v=[x['raw'] for x in r]; print(v == sorted(v))"` → `True`.

### Step 2: The route + context builder + the name join (app.py)

**2a — Slug allowlists (module-level constants, near the other route
constants).** The raw query values are ONLY ever used as keys into these
hardcoded maps (the injection/path-traversal discipline of constraint 8 — no
request string ever touches the artifact, a path, or a template as-is):

```python
# Plan 029: URL-safe slugs. The artifact's "A+" level key would form-decode
# as "A " in a query string ("+" = space), so slugs are the URL contract.
_LEADER_LEVEL_SLUGS = {"aa": "AA", "a-plus": "A+", "a": "A", "aaa": "AAA"}
_LEADER_METRIC_SLUGS = {
    "chase": "chase_pct", "whiff": "whiff_pct",
    "swstr": "swstr_pct", "z-contact": "z_contact_pct",
}
_LEADER_DEFAULT_LEVEL = "aa"      # AA is the moat: the level nobody else can render
_LEADER_DEFAULT_METRIC = "chase"  # the flagship social claim
_LEADER_LIMIT = 25
```

Parse helpers mirror `_parse_spark_window` exactly: normalize
(`str(raw or "").strip().lower()`), membership-check against the slug map,
`None` on miss, route applies the default. Junk (`?level=../etc`,
`?metric=DROP TABLE`) silently falls back to the default board with a 200.

**Metric pills are additionally filtered by the artifact**: a slugged metric
whose `*_pct` key is absent from the artifact's orientation lists renders no
pill and falls back to default if requested (defense in depth — the store's
rankable gate already refuses it; the pills just shouldn't offer it). Level
order on the pills: **AA, A+, A, AAA** (AA first — it is the flagship; AAA
last because AAA-ish data exists elsewhere).

**2b — The mlbam → row map, memoized on the DD generation.** Mirror
`_VALUE_MAP_CACHE` (app.py:6754-6772) exactly — a module-level
`(generation_key, mapping)` tuple swapped atomically:

```python
_DISCIPLINE_NAME_CACHE = (None, None)  # (dd generation, {mlbam_str: slim dict})

def _discipline_name_map():
    # {str(mlbam_id): {"name", "player_id", "team"}} from dd_store; rebuilt
    # only when generated_at changes. Read-only for consumers.
```

Built from `dd_store.get_all()` filtering rows with a non-empty
`getattr(row, "mlbam_id", None)`. Keep the per-entry dict slim (name,
player_id = `row.id`, team) — the board must NOT carry dynasty value/rank
into its rows (observe-only framing; see STOP conditions).

**2c — Context builder + route.**

```python
def _discipline_leaders_context(args):
    level_slug = _parse_leader_level(args.get("level")) or _LEADER_DEFAULT_LEVEL
    metric_slug = _parse_leader_metric(args.get("metric")) or _LEADER_DEFAULT_METRIC
    board = pitch_discipline_store.leaders(
        _LEADER_LEVEL_SLUGS[level_slug], _LEADER_METRIC_SLUGS[metric_slug],
        limit=_LEADER_LIMIT,
    )
    names = _discipline_name_map()
    rows, unresolved = [], 0
    for i, r in enumerate((board or {}).get("rows") or [], start=1):
        info = names.get(r["mlbam_id"])
        if info is None:
            unresolved += 1
        rows.append({**r, "rank": i,
                     "name": (info or {}).get("name") or f"MLBAM {r['mlbam_id']}",
                     "player_url": f"/player/{quote(str(info['player_id']), safe='')}?mode=prospects" if info else None,
                     "team": (info or {}).get("team")})
    return {"leaders_available": bool(rows), "board": board, "rows": rows,
            "unresolved_count": unresolved,
            "level_slug": level_slug, "metric_slug": metric_slug, ...}
```

Decisions encoded here:
- **Unresolved rows stay IN the ranking** (fallback label, no link) — dropping
  them would falsify "lowest chase rate in AA." If `unresolved_count > 0`, the
  template renders a fineprint line ("N of the ranked players are no longer in
  the served universe — shown by MLBAM id"). Expected ~0 in practice.
- **`leaders_available`** gates the whole template on the gaps.html pattern —
  empty artifact, refused metric, or empty pool all render the honest empty
  state with a 200, never a 500 (constraint 6: fail-soft).
- The route is a plain `GET /discipline-leaders` →
  `render_template("discipline_leaders.html", **context)`. Nothing else.
- Deep-link URL grammar matches `player_detail_url` (app.py:5972) — reuse or
  mirror it, don't invent a third form.

**Verify**:
- The page-render, slug-validation, and est.-split commands (Commands table)
  all pass.
- `python -c "import app; c=app.app.test_client(); h=c.get('/discipline-leaders').data.decode(); import re; print(h.count('/player/') >= 20)"` → `True` (rows deep-link to cards).

### Step 3: The template — board table + pills + every honesty line

`templates/discipline_leaders.html`, extending base.html (gaps/movers
skeleton: OG block overrides → `{% block content %}` → `editorial_date` macro
import → heading → content).

Layout (all classes are existing tokens — see Current state):

1. **Heading section** (`.glass`): title ("Plate-Discipline Leaders"), a
   one-line framing ("Who controls the strike zone at each level — counted
   from MLB play-by-play"), and the **as-of line** from `board.as_of`.
2. **Two pill rows** (`.bf-filter-pills.ledger-pills`, movers.html:36-41
   pattern): levels (AA · A+ · A · AAA) and metrics (Chase% · Whiff% ·
   SwStr% · Z-Contact%), each pill a server-rendered `<a
   href="/discipline-leaders?level={{slug}}&metric={{slug}}">` with
   `is-active` on the current selection. The metric pill label carries the
   est. marker when that metric at the CURRENT level is estimated (see 4).
3. **The board table** (`.rankings-table` + `col-*` classes): columns =
   Rank · Player (deep-linked; fallback label unlinked) · Team · <Metric>
   value · Cohort %ile · Pitches. **No dynasty value, no dynasty rank, no
   ETA — nothing that reads as a valuation** (observe-only; the card
   deep-link is where valuation context lives).
4. **est. honesty** (constraint 3, the 023 pattern): when
   `board.estimated` — i.e. the current metric is a zone metric AND the
   level's buckets are pixel-calibrated — render the `.pd-est-tag` "est."
   marker on the metric header/pill plus the standing note line linking
   `/methodology#plate-discipline` ("Zone metrics at this level are estimated
   from a pixel-coordinate calibration — see methodology"). When the level is
   measured (AAA: `zone_estimated false`), NO tag — never over-hedge a
   measurement into an estimate. Exact metrics (Whiff%, SwStr%) never carry
   the tag anywhere. Defensive: the per-row `estimated` flags feed the group
   flag; if a mixed level ever appears (shouldn't), tag rows individually
   rather than the header.
5. **Floor + cohort honesty line** (always visible, `.buys-fineprint` style):
   "Top {{rows|length}} of {{board.total_qualifying}} qualifying {{level}}
   hitters - minimum {{board.min_pitches}} pitches seen. Percentiles compare
   hitters at the same level only." Below-floor players never appear (the
   store already guarantees it; the line makes the rule legible).
6. **Provenance line**: "Computed from MLB play-by-play feeds - as of
   {{board.as_of}}." (identical grammar to the card's line).
7. **Unresolved fineprint** (only when `unresolved_count > 0`, per Step 2c).
8. **Empty state** (`{% if not leaders_available %}`, gaps.html:36-40 shape):
   ".glass" section, "Leaders unavailable — the board populates after the
   next daily build." — and nothing else renders. 200, never 500.
9. **(If Step 5 ships)** the og_image block overrides pointing at
   `/discipline-leaders/share-card.png?level=...&metric=...` (absolute URL,
   the way /trade builds its og_image), plus a small "Share this board" link
   to the PNG.

**Verify**:
- Template smoke (Commands table) passes.
- Rendered AA-chase page contains: the floor line ("minimum 300"), the cohort
  count, "Computed from MLB play-by-play feeds", the as-of date, "est." and
  the `/methodology#plate-discipline` link.
- Rendered AAA-chase page contains NO "est." tag.
- No contextual metric appears anywhere:
  `python -c "import app; c=app.app.test_client(); h=c.get('/discipline-leaders').data.decode(); print('Z-Swing' not in h and 'Zone%' not in h and 'Swing%' not in h.replace('Z-Swing%',''))"` → `True`
  (adjust the assertion so `Swing%` isn't matched inside other labels; the
  point: no pill, column, or ranking for swing_pct / z_swing_pct / zone_pct).

### Step 4: Footer links + the methodology sentences

**4a — Footer** (`templates/partials/_footer_provenance.html`): add
`<a href="/discipline-leaders">Discipline Leaders</a>` to EACH page-mode
branch's dash-joined list (the ~4 branches around lines 22/25-31/34-40/43-49
— the file duplicates the list per mode; match it, don't refactor it).
Plain label; any branding name is Alex's call — flag, don't invent.

**4b — Methodology** (`templates/methodology.html`, INSIDE the existing
`#plate-discipline` section at :364+): append 2-3 sentences in the section's
grammar: the leaders board ranks only hitters with at least the minimum
pitches seen (the same floor the cards use), within a single level's cohort;
zone metrics remain estimates at pixel-only levels and are tagged "est." on
the board exactly as on cards; the cohort is a snapshot of who is at the
level today, so leaders shift as players promote. No new anchor needed — the
board links the existing one.

**Verify**:
- `python -c "import app; c=app.app.test_client(); print(b'/discipline-leaders' in c.get('/').data)"` → `True` (footer link live on the board page).
- `grep -c "discipline-leaders" templates/partials/_footer_provenance.html` → one per branch (>= 4).
- `/methodology` still renders 200 and contains the new sentences.

### Step 5: (CUT-CANDIDATE — but prefer shipping) The PNG share card + the mandatory cache-key add + the gallery tile

**If cutting to hold S, skip this entire step** (including the
`_PNG_CACHE_PARAMS` add and the gallery tile) and record the cut in the
status row. If shipping, the order below is mandatory.

**5a — Add `"level", "metric"` to `_PNG_CACHE_PARAMS` FIRST** (app.py:154-162),
with the house comment convention:
```python
    "level", "metric",  # plan 029: the /discipline-leaders card renders from
    # these; they MUST be in the cache key or every level x metric board
    # collapses to one key and the first-rendered card is served for all of
    # them (the plan 007/022 cross-user poisoning class). Fixed names.
```
These are exact fixed names (not `w_`/`pt_` open suffixes) — the plain
allowlist is the right place, same as `give`/`get`. Note (accepted): stray
`level`/`metric` params on other PNG routes now enter those keys — harmless
fragmentation, not poisoning.

**5b — `_discipline_leaders_share_card_png(level_key, metric_key)`** — reuse
`pitch_discipline_store.leaders(...)` (top 10 rows) + `_discipline_name_map()`
for names; 1080x1350 RGB on the `_receipts_share_card_png` /
`_movers_share_card_png` skeleton (`_graphic_fill_background` →
`_graphic_header` → ranked list panel → `_graphic_footer(right_note=
"valucast.app/discipline-leaders")`). Headline states the claim in orientation
words, e.g. `LOWEST CHASE RATE - AA` / `HIGHEST Z-CONTACT - AA`; subtitle
carries the honesty line: `min 300 pitches - {total_qualifying} qualifying -
as of {as_of}`; when the board is estimated, one caveat line: `zone metrics
estimated from pixel calibration (see valucast.app/methodology)`. **Every
drawn string ASCII-only** (`" - "`, no em-dashes/middot/percent-sign issues —
`%` is ASCII and fine). Fail-soft: an unavailable board → the route returns
404 (or the house pattern for cardless states — grep how the receipts PNG
behaves under its hold and mirror), never a stack trace.

**5c — The routes**: `/discipline-leaders/share-card.png` parses the SAME slug
helpers as the page (junk → defaults — the PNG and the page must agree on
canonicalization so one URL means one board means one cache key), builds the
PNG, returns `make_response(png)` + `Content-Type: image/png` + inline
`Content-Disposition`. Add the HTML preview route
(`/discipline-leaders/share-card`) only if the house pattern has one for the
other cards (grep `receipts/share-card` — mirror whatever exists). Wire the
og_image blocks in `discipline_leaders.html` (Step 3.9).

**5d — The cards-gallery tile**: one dict appended to `entries` in
`cards_gallery()` (app.py:8009-8072), shaped exactly like the existing
entries (`title` "Plate-Discipline Leaders", `caption` with the min-pitch
floor claim, `page_url` `/discipline-leaders`, `png_url` the share-card URL
with the default slugs, `board_url`, `generated_at` from the store's
`as_of`). No hold flag needed (nothing about this page is held).

**Verify**:
- The PNG-render and cache-vocabulary commands (Commands table) pass.
- **The poisoning guard (load-bearing)**: two different boards produce
  DIFFERENT cache keys —
  `python -c "import app; a=app.app; k=[];\nwith a.test_request_context('/discipline-leaders/share-card.png?level=aa&metric=chase'): k.append(app._png_cache_key())\nwith a.test_request_context('/discipline-leaders/share-card.png?level=aaa&metric=whiff'): k.append(app._png_cache_key())\nprint(k[0] != k[1])"` → `True` (write it as the unit test, not just the smoke).
- `/cards` renders 200 and contains the new tile.

### Step 6: Full suite + restore the byproduct

```
python -m pytest -q
git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json
git status --short
```
**Verify**: full suite green (>= the count at HEAD, plus the new assertions);
`git status` shows ONLY in-scope files; the archive byproduct restored; no
`data/dd/*`, no local pitch-cache files staged; frozen files untouched
(`git diff --stat 32b9b265..HEAD -- prospects/ahead_of_consensus.py scripts/build_ahead_of_consensus_scorecard.py` → empty).

## Test plan

- `tests/test_pitch_discipline_store.py` additions (run against a small tmp
  fixture artifact written by the test — cohorts block + a handful of players
  incl. one sub-floor bucket, one two-level player, mixed zone_estimated
  levels):
  1. **Floor enforcement (load-bearing)**: a bucket with `qualifies: false`
     (e.g. 250 pitches) is EXCLUDED from `leaders()` rows AND from
     `total_qualifying`, even though its `rates` are populated.
  2. **Orientation**: `leaders(level, "chase_pct")` rows are ascending by
     raw rate; `leaders(level, "z_contact_pct")` descending. Rank-1 row
     carries the highest cohort percentile on the fixture (quality-oriented
     percentiles cross-check).
  3. **Rankable gate**: `leaders(level, "swing_pct")` → `None` (contextual);
     `leaders(level, "zone_pct")` → `None`; unknown metric → `None`; a
     fixture whose cohorts block LACKS the orientation lists → `None` (no
     hardcoded fallback judgment).
  4. **Per-level isolation**: the two-level fixture player appears on both
     levels' boards with that level's numbers; the AA board contains no AAA
     rate.
  5. **est. flags**: on the estimated-level fixture, chase rows carry
     `estimated True`; on the measured level (`zone_estimated: false`),
     `estimated False`; exact metrics `False` everywhere. Derivation matches
     `_metric_row`'s (same inputs → same flag).
  6. **Fail-soft**: nonexistent path → `leaders(...) is None`,
     `cohort_meta() == {}`; malformed JSON → same; `groups_for` behavior
     unchanged (existing tests still green).
  7. **Tie determinism**: two fixture players with equal rates order by
     larger `pitches` first.
- `tests/test_app.py` additions:
  1. **Default board renders**: `GET /discipline-leaders` → 200; contains the
     floor line, the cohort count, the as-of date, "Computed from MLB
     play-by-play feeds", and >= 1 `/player/` deep link.
  2. **Param validation**: `?level=a-plus&metric=whiff` → 200 with the A+
     board active; `?level=../etc&metric='+DROP` → 200 falling back to the
     default board (no 500, no reflection of the raw value into the page);
     `?level=A+` (which arrives as `"A "`) → 200 default board (the slug
     contract holds).
  3. **est-tag rendering**: AA chase page contains `est.` and
     `/methodology#plate-discipline`; AAA chase page contains NO `est.` tag.
     (If the live artifact is unavailable in CI, drive this through a fixture
     store monkeypatched onto `app.pitch_discipline_store` — same technique
     as the existing discipline card tests.)
  4. **Contextual metrics absent**: no pill/column/board for
     swing_pct / z_swing_pct / zone_pct anywhere in the rendered page.
  5. **Fail-soft empty artifact**: with the store pointed at a missing file,
     `GET /discipline-leaders` → 200 + "unavailable" copy, no table, no 500.
  6. **No valuation framing**: the rendered board contains no dynasty value /
     dynasty rank column for the ranked rows (assert the specific labels the
     board tables use, e.g. no `col-value` header cell on this page).
  7. **PNG cache-key trio (ONLY if Step 5 ships — mirror tests/test_app.py:1703-1725)**:
     (a) different `level`/`metric` → different `_png_cache_key()` tuples;
     (b) same params → same key; (c) `"level"` and `"metric"` literally in
     `_PNG_CACHE_PARAMS`. Plus: PNG route with junk params → the default
     board's card (canonicalization agreement between page and PNG).
- Template render smoke: `discipline_leaders.html` + `methodology.html` load
  with no exception.
- Final: `python -m pytest -q` all green, then restore the archive byproduct.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (>= the count at HEAD); byproduct restored.
- [ ] `GET /discipline-leaders` renders the default AA Chase% board: ranked
      qualifying hitters only, deep-linked to `/player/<id>`, floor stated
      on-page ("minimum 300 pitches"), cohort size shown, as-of date shown,
      provenance line shown.
- [ ] Below-floor players NEVER appear (store-level `qualifies` gate +
      fixture test).
- [ ] Only the 4 artifact-oriented metrics have boards (Chase%/Whiff%/SwStr%
      low-is-good ascending, Z-Contact% high-is-good descending); the 3
      contextual metrics have NO leaders surface of any kind.
- [ ] est./measured carries through per bucket: estimated zone rows are tagged
      "est." + `/methodology#plate-discipline` link (`.pd-est-tag`, same as
      cards); measured rows stay untagged, including on a mixed-level board;
      exact metrics are untagged everywhere. The live artifact contains a
      small number of estimated AAA/A buckets, so disclosure must follow the
      row's `zone_estimated` field rather than a level-wide assumption.
- [ ] Per-level only — a multi-level player appears per level, never blended.
- [ ] `?level=`/`?metric=` are slugged, validated against hardcoded allowlist
      maps, and junk falls back to defaults with a 200 (the `A+`-as-space trap
      covered by the slug contract).
- [ ] Empty/malformed artifact → honest empty state, 200, never a 500;
      `leaders()`/`cohort_meta()` fail-soft.
- [ ] No dynasty value/rank column or valuation framing on the board;
      observe-only intact (no discipline number flows into any score — no
      scoring file touched at all).
- [ ] Footer link in every `_footer_provenance.html` branch; NO new
      `horizon-tabs`/`site-nav` tab (flagged for Alex).
- [ ] Methodology `#plate-discipline` section extended with the board's
      floor/cohort/est. sentences.
- [ ] IF the PNG shipped: `"level"`,`"metric"` in `_PNG_CACHE_PARAMS` with the
      plan-029 comment, the cache-key test trio green, og_image wired, and the
      cards-gallery tile present. IF cut: none of those exist, and the status
      row says the PNG was cut.
- [ ] Serving stays network-free (no new network import reachable from the
      route path) and NO new build step/artifact/YAML change exists.
- [ ] `prospects/ahead_of_consensus.py` and
      `scripts/build_ahead_of_consensus_scorecard.py` untouched.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- **A below-floor player would appear on any leaderboard** — a `qualifies:
  false` bucket entering the ranked pool, the displayed rows, OR the
  `total_qualifying` count. Small-sample honesty is non-negotiable (the
  artifact carries fully-populated rates on 394 sub-floor buckets precisely
  so a naive iteration WILL leak them). STOP and restore the gate.
- **An estimated metric would render without the est. tag** — a pixel-
  calibrated zone metric showing as if measured, on the page OR the PNG.
  Either add the disclosure or cut the surface. The inverse — tagging a
  measured row "est." — is also a violation: never over-hedge a measurement.
- **A contextual metric is getting leader framing** — a board, pill, ranked
  column, or PNG for `swing_pct`/`z_swing_pct`/`zone_pct`, or any hardcoded
  orientation for them. The artifact's orientation lists are the source of
  truth; if you find yourself adding a metric to a local judged list the
  artifact doesn't orient, STOP.
- **Any new PNG query param is missing from `_PNG_CACHE_PARAMS`** — shipping
  `/discipline-leaders/share-card.png` reading `level`/`metric` without the
  allowlist add is the plan 007/022 cross-user cache-poisoning class. Do not
  ship the route without the add + the key-distinguishing test; if you cannot
  add them safely, cut the PNG.
- **Time-window temptation** — any implementation of 7d/30d leaders. The data
  does not exist in the committed artifact; the per-game history is the
  UNCOMMITTED local pitch cache and plan 023's 2b size decision is NOT
  reopened here. Windows are the CI-refresh fast-follow. STOP.
- **A discipline number is about to flow into the 0-150 value / z-scores /
  rank, or a dynasty value/rank column is about to render on the board** —
  observe-only is the artifact's own declared policy
  (`source_policy.feeds_rank/feeds_value: false`). STOP.
- **The artifact schema drifted** — `cohorts.lower_is_better`/
  `higher_is_better` missing, `qualifies`/`zone_estimated` renamed, or the
  bucket shape changed. Re-verify against the live artifact before building on
  a guess; on a real drift, STOP and reconcile with the 023 build script.
- **`PitchDisciplineStore`/`_metric_row`/`_png_cache_key`/`_PNG_CACHE_PARAMS`
  were refactored away** — re-locate the surfaces at HEAD before wiring; do
  NOT fork a parallel reader or cache path.
- **Unresolved-name blowup** — if the mlbam → dd_store join misses a LARGE
  fraction of ranked rows (>10%), that is an identity-drift signal, not a
  display problem; STOP and report rather than shipping a board of "MLBAM
  123456" rows.

## Non-goals (V1)

- **No time-windowed leaders (7d/30d).** The committed artifact holds
  season-to-date aggregates per level; windows require per-game history that
  lives only in the uncommitted local pitch cache (plan 023 Step 2b's size
  decision, ~350MB full-scale, gitignored — not reopened here). Windowed
  leaders are an explicit fast-follow **tied to the discipline CI-refresh
  work**: when/if a windowed slice is designed into the committed artifact,
  the board grows window pills the same way movers did.
- **No pitcher-side leaders.** Hitters only, same as the parent layer.
- **No contextual-metric boards.** Swing%, Zone%, Z-Swing% remain card-context
  only; V1 deliberately omits them from this page entirely (showing them
  unranked on a page titled "Leaders" invites exactly the misreading the
  orientation rule exists to prevent — they stay where the cards' neutral
  rendering already handles them).
- **No blended cross-level board, no "best level" selection.** Per-level
  cohorts only.
- **No new primary-nav tab** (nav diet; footer + cards gallery only —
  promotion is Alex's call).
- **No new build step, committed artifact, network fetch, or artifact-schema
  change.** The board is a pure read surface over what 023 ships daily.
- **No names added to the artifact.** The serve-time dd_store join is the V1
  answer; baking names into the artifact is a 023-build-script follow-up if
  the join ever proves inadequate.
- **No per-source ranks anywhere** (house ToS rule; nothing on this page needs
  consensus data at all).

## Rollout order

1. **Store extension + fixture tests** (`cohort_meta`, `leaders`) — the
   floor/orientation/isolation rules locked by unit tests before any route
   exists.
2. **Route + context + name join** (slug allowlists, memoized map, fail-soft
   empty state).
3. **Template** (pills, table, every honesty line, est. split, empty state).
4. **Footer + methodology.**
5. **PNG + cache-key add + gallery tile LAST** (the cut line — everything
   before this ships standalone).
6. **Full suite + byproduct restore.**

## Risks

- **Cohort churn.** Level cohorts shift daily as players promote/demote — a
  "leader" is a snapshot-in-time claim. The as-of date + the methodology's
  snapshot sentence carry the honesty; social posts inherit the date from the
  PNG subtitle.
- **Name-join drift.** A ranked mlbam with no dd_store row renders the
  fallback label. Rare by construction (the artifact is built from the
  tracked universe); the fineprint disclosure + the >10% STOP condition bound
  the failure.
- **Stale artifact.** If the daily discipline refresh no-ops (StatsAPI
  outage — 023's designed behavior), the board serves stale-but-labeled data;
  the as-of line is the disclosure. No new handling needed.
- **AAA cohort is small (150).** The floor still holds; the cohort-size line
  makes the thinner pool legible. No special-casing.
- **Slug/param drift between page and PNG.** If the two parse params
  differently, one URL could mean two boards. Mitigated by sharing the exact
  parse helpers (Step 5c) and the canonicalization test.
- **Social claim accuracy.** "Lowest chase rate in AA (min 300 pitches)" is
  only true if the ranking covers the FULL qualifying cohort — hence the
  never-silently-drop rule for unresolved names and the qualifies-only pool.

## Maintenance notes

- **The artifact's orientation lists are the board's contract.** If a future
  023 revision orients a fifth metric, the board picks it up by adding one
  slug entry — the store's rankable gate already reads the artifact. Never
  orient a metric board-side that the artifact left contextual.
- **The est. tag graduates per level via `zone_estimated`** (023's maintenance
  note): if AA ever publishes tracked pX/pZ, its buckets flip to measured and
  the board's tag disappears for that level automatically — no board change
  needed. That is why the tag reads the per-bucket flag, never a hardcoded
  per-metric rule.
- **`leaders()` must stay qualifies-only forever.** The sub-floor buckets in
  the artifact exist for card-side transparency, not ranking. The fixture
  test is the regression lock.
- **`level`/`metric` live and die with the PNG route.** If the share card is
  ever retired, remove them from `_PNG_CACHE_PARAMS` together with the route
  (plan 022's give/get note, same rule).
- **Windowed leaders are the designed fast-follow**, gated on the discipline
  CI-refresh work committing a windowed slice — the pills row and the slug
  grammar were chosen so windows bolt on without reshaping the page.
- **Plan 027 (glossary) imports `pitch_discipline_store._DEFAULT_LABELS`** in
  its coverage union — the store extension here must not rename or restructure
  it.
- **Nav promotion is a one-line macro edit + the 640px tab-wrap re-check** if
  Alex ever wants a tab — a separate, tiny follow-up, not this plan.
