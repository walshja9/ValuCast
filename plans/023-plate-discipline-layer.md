# Plan 023: Plate-Discipline Data Layer — pitch-level swing/whiff/chase metrics for prospects, computed from MLB StatsAPI play-by-play, surfaced as new percentile bars with per-level cohorts and an exact-vs-estimated honesty split

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> ```
> git log -1 --format=%h    # baseline for this plan is 93304857
> git diff --stat 93304857..HEAD -- app.py web/statcast_store.py web/prospect_percentiles.py web/public_snapshot_models.py templates/partials/player_detail_dynasty.html scripts/refresh_milb_season_stats.py scripts/run_daily_public_build.py .github/workflows/daily-public-data.yml scouting/mlb_read.py
> git status --short
> ```
> This plan was written against `93304857`. All "Current state" line refs are
> accurate to that commit. If any in-scope file changed since, re-read the cited
> excerpt against the live code before proceeding; on a mismatch with an excerpt,
> treat it as a STOP condition. In particular the card context builder
> (`_build_dynasty_player_detail_context`, app.py:~8383-8494), the profile-bars
> render block (`player_detail_dynasty.html:84-143`), and the daily-build step
> lists (`run_daily_public_build.py:BUILD_STEPS`/`VALIDATE_STEPS`,
> `daily-public-data.yml` "Refresh …" steps + `git add` block) are the
> load-bearing reuse surfaces — re-verify them at HEAD.
>
> **This is a NEW-FEATURE / new-data-layer plan.** It adds a build-time data
> module, a committed artifact, a fail-soft reader, and a card section. Nothing
> here is frozen-file-blocked, but the same guardrails apply: master
> auto-deploys valucast.app via Render, so do NOT push; the reviewer gates the
> push.

## Status

- **Priority**: P2 (product depth / competitive gap, not a correctness or honesty
  leak in the existing product). Prospect debates increasingly cite ProspectSavant
  swing/whiff/chase numbers; the spike (7/10) proved the outcome metrics are
  *exactly* reproducible from MLB's public play-by-play, so this is a defensible,
  ledger-honest way to close a card-depth gap ValuCast currently has.
- **Effort**: **L**. This is genuinely large: a new StatsAPI play-by-play counting
  module, a ~8k-game one-time backfill (checkpointed + resumable), a compact
  committed intermediate + a per-player artifact, a cohort-percentile pass, a
  fail-soft reader, and a card section — plus the pixel-coordinate calibration for
  the estimated zone metrics. The **cut-to-M lever is the zone metrics** (Chase%,
  Z-Swing%, Z-Contact%, Zone%): the exact swing/whiff outcome metrics (Swing%,
  Whiff%, SwStr%) stand entirely on their own and are the product. Ship exact-only
  first; treat the pixel-calibrated zone group as a fast-follow that can be dropped
  or deferred without touching the core. See "Scope" for the explicit cut line.
- **Risk**: MEDIUM. All network is confined to build scripts (serving stays
  network-free — the FanGraphs/Statcast precedent). The sharp edges are (a)
  **calibration honesty** — zone metrics are estimates and MUST render visually
  tagged as such, never as if measured; (b) **small-sample honesty** — a hard
  minimum-pitch gate below which NO bar renders; (c) **artifact size** — ~8k feeds
  is large, so we commit a *compact per-pitch intermediate*, never raw feeds; (d)
  **EV temptation** — exit velocity is impossible from public AA data and is a
  STOP condition if anyone tries to estimate it.
- **Depends on**: none in flight. Reads the same `dd_store` rows the card already
  serves; the artifact is keyed by mlbam id (the identity the card already
  carries). Coordinates with nothing frozen.
- **Category**: feature (product — new prospect-card data layer).
- **Planned at**: commit `93304857`, 2026-07-10.
- **Execution window**: **post-7/13.** No frozen-file dependency, but do not start
  before the 7/13 ledger-week unlock (repo-wide batch-3 convention). When it runs,
  wire the incremental daily step LAST so a broken fetch never stalls the existing
  daily build.

## Why this matters

Plate discipline (does he swing at the right pitches, does he make contact when he
swings, does he chase out of the zone) is the single most-cited modern lens in
prospect debates, and ProspectSavant made it table stakes by publishing it for
MiLB. The 7/10 spike proved something valuable and specific: **the outcome half of
those metrics is exactly reproducible from MLB's own public play-by-play feed.** For
Mike Sirota (mlbam 701527), 41 Double-A games, our per-pitch counts matched
ProspectSavant to the decimal — Swing% 37.4 vs 37.4, SwStr% 9.2 vs 9.25, Whiff%
~27 vs 27.1. That is a genuine, deterministic, publicly-scored data layer we can
own — exactly the ValuCast grammar (numbers on the page reproducible from a
committed daily artifact).

The honesty bar is the same as everywhere else on the site, and here it has three
hard edges baked into the plan:

1. **Exact vs estimated is a visible split.** Swing%, Whiff%, SwStr% are *measured*
   (pitch-outcome descriptions in the feed). Chase%, Z-Swing%, Z-Contact%, Zone%
   depend on *where the pitch was*, and modern tracked coordinates (`pX`/`pZ`) are
   100% absent at AA — only legacy pixel coordinates exist there. So the zone
   metrics are **estimates** from a pixel→feet calibration and MUST render tagged as
   estimates ("est." + a methodology link). We never present an estimate as a
   measurement.
2. **Small samples get no bar.** Below a minimum pitches-seen threshold, the
   percentile bar does not render at all — the same small-sample discipline the
   card already applies to the MiLB stat bars (100 PA / 20 IP).
3. **Exit velocity is impossible and forbidden.** Public AA play-by-play carries no
   batted-ball tracking. The plan explicitly forbids fabricating or estimating EV
   anywhere.

## Current state

Verified against the live files at `93304857`. Read each cited line yourself before
building on it.

### The network-fetch-to-committed-artifact precedent is `scripts/refresh_milb_season_stats.py` + the daily YAML

- **The exact pattern to mirror.** `scripts/refresh_milb_season_stats.py` fetches
  from `https://statsapi.mlb.com/api/v1/stats?...` with a `urllib.request.Request`
  carrying a `User-Agent` (line 97-101), the SAME `SPORT_LEVELS = {11:"AAA",
  12:"AA", 13:"A+", 14:"A"}` sportId map this plan needs (line 20-25), an
  **atomic write** (`write_milb_season_stats`: write `.tmp`, `os.replace`, line
  304-310), and a **tiny-refresh guard** (`_assert_not_tiny_refresh`, line 288-302)
  that refuses to overwrite a good artifact with a suspiciously small one. Copy all
  four idioms. It is wired into the daily workflow as two "Refresh …" steps
  (`daily-public-data.yml:115-119`), which run BEFORE `run_daily_public_build.py`.
- **The daily build graph** is `scripts/run_daily_public_build.py`: `BUILD_STEPS`
  (line 16-96) is an ordered list of `(script, *args)` tuples run via
  `subprocess.run(..., check=True)`; `VALIDATE_STEPS` (line 99-148) is the parallel
  validator list ending in a targeted pytest step. A new build step is one tuple
  appended in dependency order; a new validator is one tuple in `VALIDATE_STEPS`.
  There is a `validate_steps()` duplicate-guard (line 162-167) — do not add a step
  twice.
- **The YAML commit block** (`daily-public-data.yml:147-246`) is an explicit
  `git add \` list of every artifact path — **a new committed artifact MUST be
  added to this list** or the daily build computes it and throws it away (never
  commits it, so serving never sees the refresh). This is the one wiring step that
  is silent-if-missed.

### The fail-soft committed-artifact reader precedent is `web/statcast_store.py`

- **`StatcastStore` (web/statcast_store.py:73-149)** is exactly the shape this
  layer's reader wants: a lazy, fail-soft reader of a committed JSON
  (`data/statcast/percentiles.json`). `_ensure_loaded` (line 83-97) reads once and
  degrades to an empty store on `OSError`/`ValueError` — "a missing or malformed
  artifact degrades to 'no percentile section' — never an exception and never a
  fetch (request-time fetches on Render were the 502 lesson)" (docstring, line 1-10).
  `display_groups(mlbam_id, ...)` (line 104-125) returns card-ready
  `[{"label","metrics":[{"label","pct","raw","display","color"}]}]` or `[]`. **Model
  the plate-discipline reader on this class** — same fail-soft contract, keyed by
  `str(mlbam_id)`, returning `[]` when the player/artifact is absent.
- `percentile_color(pct)` (line 62-70) is the ValuCast clay→slate→teal ramp — reuse
  it if the discipline bars want the same coloring, or reuse the profile-bar
  elite/good/risk/neutral classes (below). Do NOT invent a new color scale.
- The app instantiates `statcast = StatcastStore()` at module load (app.py:409) and
  the card context calls `statcast.display_groups(...)` (app.py:424). Follow that
  instantiate-once, read-per-request pattern.

### The prospect-card percentile bars — render block + the model that feeds it

- **The render block** is `templates/partials/player_detail_dynasty.html:84-143`,
  inside `<div class="detail-section prospect-profile-card">`. It iterates
  `profile_bars` (line 100-113): each bar is `{key, label, value, percentile,
  caption}` and renders a `.profile-bar-track` with the fill class chosen by
  percentile (`elite` >=90, `good` >=75, `risk` <=25, else `neutral`, line 106) and
  a `.profile-bar-num` at `left: {{pct}}%`. **This is the exact widget to reuse for
  the discipline bars** — a new `profile_bars`-shaped list rendered by the same
  markup (or a near-clone with an "est." tag on the estimated rows). The plate-
  discipline group renders as its own labeled sub-section INSIDE this card (or a
  sibling `detail-section`), not mixed into the existing MiLB `profile_bars` (those
  are AVG/OPS/K%/etc. from the stat line — a different pool).
- **The model** is `web/prospect_percentiles.py`. `profile_bars(row, percentiles)`
  (line 1009-1031) builds the bar dicts from a selected stat line + a precomputed
  `percentiles` dict; `percentile_for(pool, metric, value)` (line 931-942) is the
  midrank-percentile function (clamped 1..99, quality-oriented via
  `LOWER_IS_BETTER`); `build_pool(rows)` (line 912-928) builds the sorted per-metric
  pool. **The plate-discipline percentiles are precomputed per-level in the build
  script (Step 4), NOT with `build_pool` at app startup** — because the cohort is
  by-level and the raw pitch counts live in the artifact, not on the snapshot row.
  Read `percentile_for`'s midrank formula as the reference for the build-script
  cohort math so the two agree. `MIN_PA=100`/`MIN_IP=20` (line 17-18) are the
  card's existing small-sample floors — the plate-discipline floor is analogous
  (Step 4: a pitches-seen minimum).
- **The card context builder** is `_build_dynasty_player_detail_context(player_id,
  args)` (app.py:~8383-8494). For a prospect it assembles `prospect_context`
  (app.py:8431-8442) with `stat_percentiles`, `profile_bars`, `skill_grades`, etc.,
  then `context.update(prospect_context)` (line 8491). **Add the plate-discipline
  block here**, guarded by `if dd_row.is_prospect:` and keyed by
  `getattr(dd_row, "mlbam_id", None)` (the id `shape_comps` already uses at line
  8428-8430). It renders only when the reader returns a non-empty group.

### The identity / artifact-load plumbing already exists

- **`_load_artifact(path)`** (app.py:4663-4678) — mtime-stamped, cached, fail-soft
  JSON loader returning a dict or `None`. Use it if the reader is a plain function;
  or model a `StatcastStore`-style class (preferred, for parity). Either is fine —
  do NOT add a new caching mechanism.
- **`_artifact_context_for_row(row)`** (app.py:5050+) is the precedent for
  attaching a per-row artifact slice keyed by `_row_identity_key(row)`
  (app.py:4888) / `_identity_key(mlbam_id, role)` (app.py:4882). The plate-
  discipline artifact is keyed by **mlbam id** (a hitter has one batter id; there
  is no role split for V1 since pitchers are out of scope), so keying is simpler
  than the role-split identity key — key on `str(row.mlbam_id)`.
- **`refresh_milb_season_stats.py:_int/_number/_pct/_innings`** (line 35-73) are the
  numeric coercion helpers; the plate-discipline module wants the same defensive
  parsing (a feed field can be missing/None). Reuse the idioms; do not import across
  the scripts (keep the module self-contained per the milb_translation precedent).

### The scouting number-grounding guard (plan 015 / 021) — a boundary to respect, not touch

- **`scouting/mlb_read.py:_format_stat`** (line ~11-18) is the IP/number-rounding
  guard plan 021 fixed ("182.888 innings" → "182.9") — it rounds raw model floats
  before they reach the scouting-read text/LLM. **The plate-discipline metrics do
  NOT flow into scouting reads in V1** (they are card bars fed straight from the
  artifact). So this guard is a *boundary note*, not an edit target: if a future
  change ever pipes a discipline number into `scouting/repository.py` /
  `mlb_read.py` read text, that number must pass through the same rounding/word-form
  guard (plan 015 added the digit/word-form flag at ~2.09% measured rate). Keep the
  discipline numbers OUT of the scouting-read path in V1 — card bars only — and note
  the boundary in a comment so the next person knows the rule.

### The PNG cache — scope it OUT of V1

- The PNG share-card cache-key allowlist `_PNG_CACHE_PARAMS` (app.py:~153) is the
  poisoning surface plan 022 had to extend. **V1 adds NO new PNG and NO new query
  params to any share card** (the discipline bars render on the existing player
  card page/partial, which is not param-driven by discipline data). So V1 needs no
  `_PNG_CACHE_PARAMS` change. If the existing `_prospect_player_card_png`
  (app.py:2836) is later extended to draw the discipline bars, that is a separate
  follow-up — and if it ever takes a new query param, that param must enter
  `_PNG_CACHE_PARAMS` (plan 007's invariant). Do NOT touch the PNG in V1.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Counting-logic unit tests | `python -m pytest -q tests/test_pitch_discipline.py` | all pass |
| Reader tests | `python -m pytest -q tests/test_pitch_discipline_store.py` | all pass |
| App/card render tests | `python -m pytest -q tests/test_app.py -k "discipline or player_detail"` | all pass |
| Artifact schema validator | `python scripts/validate_pitch_discipline.py` | prints OK, exit 0 |
| Counting module smoke (synthetic feed) | `python -c "from prospects.pitch_discipline import count_player_pitches; from tests.fixtures.pitch_events import SYNTHETIC_FEED, PID; print(count_player_pitches(SYNTHETIC_FEED, PID))"` | a dict of counts, no exception (adjust import to what Step 1 defines) |
| One player end-to-end (network; backfill dev only) | `python scripts/build_pitch_discipline.py --player 701527 --season 2026 --level AA --limit-games 3` | fetches 3 feeds, writes counts, no exception |
| Reader returns a group for a known id | `python -c "import app; g=app.pitch_discipline_store.groups_for('701527'); print(bool(g), [m['label'] for grp in g for m in grp['metrics']] if g else [])"` | `True` and the metric labels (or `False` if artifact not built yet) |
| Card renders with the section | `python -c "import app; c=app.app.test_client(); r=c.get('/player/<a real prospect id with data>'); print(r.status_code, b'Plate Discipline' in r.data)"` | `200` and `True` when data present |
| Network-free serving proof | `python -c "import prospects.pitch_discipline as m, inspect; src=inspect.getsource(m); print('urllib' not in src.split('# fetch section')[0] if '# fetch section' in src else None)"` OR the structural test in the Test plan | no network symbol reachable from the reader path |
| Full suite (final gate) | `python -m pytest -q` | ~1871+ pass, 0 fail; then restore the byproduct (below) |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | file back to HEAD (pytest dirties it — NEVER commit it) |

## Scope

**In scope** (the only files you create or modify):

- **NEW `prospects/pitch_discipline.py`** (or a small `prospects/pitch_discipline/`
  package) — the **pure** per-pitch counting logic: given a game feed's `allPlays`
  and a batter id, count pitches / swings / whiffs / (zone estimates), returning a
  counts dict. NO network, NO file I/O in the counting functions (network + I/O live
  in the build script, mirroring `milb_translation.py`'s "pure functions, no I/O"
  contract). The pixel→feet calibration helper lives here too (pure: pixel x,y +
  strikeZoneTop/Bottom → in/out-of-zone estimate).
- **NEW `scripts/build_pitch_discipline.py`** — the build script. Two modes:
  `--backfill` (season-wide, checkpointed/resumable) and default incremental
  (new games since the last run). Owns network (game-log + feed fetch, rate-limited
  ~0.15s), the **game-feed compact cache** (Step 2), cohort percentiles (Step 4),
  atomic write of the committed artifact, and a tiny-refresh guard. Mirrors
  `refresh_milb_season_stats.py`.
- **NEW `scripts/validate_pitch_discipline.py`** — artifact schema validator, in the
  style of the other `scripts/validate_*.py` (checks keys, per-level splits,
  `zone_estimated` flag presence, sample-size fields). Added to `VALIDATE_STEPS`.
- **NEW `web/pitch_discipline_store.py`** — the fail-soft reader (model on
  `StatcastStore`): `groups_for(mlbam_id)` → card-ready groups or `[]`. Exact metrics
  and estimated metrics returned with an `estimated: true/false` flag per metric so
  the template can tag them.
- **`app.py`** — (i) instantiate `pitch_discipline_store = PitchDisciplineStore()`
  at module load (next to `statcast = StatcastStore()`, app.py:409); (ii) in
  `_build_dynasty_player_detail_context` (app.py:~8431), add
  `"plate_discipline": pitch_discipline_store.groups_for(getattr(dd_row,
  "mlbam_id", None))` to `prospect_context` (guarded by `dd_row.is_prospect`). No
  cache/scoring/PNG region touched.
- **`templates/partials/player_detail_dynasty.html`** — a new
  `{% if plate_discipline %}` sub-section reusing the `.prospect-profile-bars` /
  `.profile-bar-*` markup, with an "est." tag + methodology link on estimated rows
  and a provenance line "Computed from MLB play-by-play feeds."
- **`templates/methodology.html`** — a new section (anchored, e.g.
  `id="plate-discipline"`) explaining the exact-vs-estimated split, the pixel
  calibration, and why EV is absent. The card's estimated-metric link points here.
- **`scripts/run_daily_public_build.py`** — append the incremental build step to
  `BUILD_STEPS` and the validator to `VALIDATE_STEPS` (LAST, per rollout order).
- **`.github/workflows/daily-public-data.yml`** — add a "Refresh plate-discipline
  metrics" step (calling the incremental build) BEFORE the build stage if the fetch
  must run in the fetch phase, OR rely on the `BUILD_STEPS` entry if the build
  script does its own incremental fetch; **and add the committed artifact + the
  compact cache path to the `git add \` block** (line 151-243).
- **NEW data artifacts** (committed):
  `data/models/valucast_pitch_discipline.json` (the per-player keyed artifact) and
  `data/prospects/raw/pitch_discipline_pitch_cache.json` (the compact per-pitch
  intermediate — see Step 2 on size). **Never commit raw game feeds.**
- **NEW tests**: `tests/test_pitch_discipline.py` (counting logic against a
  synthetic-feed fixture), `tests/test_pitch_discipline_store.py` (reader fail-soft
  + estimated flag), additions to `tests/test_app.py` (card render + network-free),
  and a fixtures file `tests/fixtures/pitch_events.py`.

**Cut line to hold Effort (the reviewer decides at planning time):**

- **CORE (must ship): the EXACT outcome metrics** — Swing%, Whiff%, SwStr% — end to
  end: counting module, backfill, per-level cohort percentiles, reader, card bars,
  methodology, daily wiring. This IS the product and it is fully deterministic /
  ProspectSavant-exact.
- **CUT-CANDIDATE: the ESTIMATED zone metrics** — Chase%, Z-Swing%, Z-Contact%,
  Zone% — and their pixel→feet calibration. If the calibration fights or the day
  runs long, ship exact-only and file the zone group as a fast-follow. The exact
  bars stand alone. **If you DO ship the zone metrics, the "est." tag + methodology
  disclosure is mandatory, not optional.** Do not ship an estimated number that
  reads like a measurement.
- **Secondary cut (only if still over): the incremental daily wiring.** Ship the
  backfilled artifact + card + methodology first; wire the daily incremental step
  as the final fast-follow (the artifact serves stale-but-labeled until then, which
  is the standard ValuCast posture).

**Out of scope** (do NOT touch):

- **Pitcher-side plate-discipline metrics** — V1 is hitters only. A pitcher's
  induced-whiff / zone rates are a symmetric but separate build (different cohort,
  different card surface). Explicit non-goal (see Non-goals).
- **Exit velocity / batted-ball tracking / any Statcast-style batted-ball metric at
  MiLB** — impossible from public AA data. Fabricating or estimating EV is a STOP
  condition.
- **The valuation / scoring math** — these are display-only card context, NEVER a
  value input (the `milb_translation.py` / percentiles precedent: "observe-only,
  never a value input"). Do NOT feed a discipline number into the 0-150 value, the
  z-scores, the peak projection, or any ranking.
- **The scouting-read text path** — do NOT pipe discipline numbers into
  `scouting/repository.py` / `scouting/mlb_read.py` / `report_generator.py` in V1
  (keeps them clear of the plan-015 word-form guard surface). Card bars only.
- **The PNG share cards / `_PNG_CACHE_PARAMS`** — no new PNG, no new share-card
  param in V1 (see Current state).
- **Frozen files** — `prospects/ahead_of_consensus.py`,
  `scripts/build_ahead_of_consensus_scorecard.py` (pre-registered AOTC scoring,
  ~7/13 unlock). This plan does not need them.
- **A public "board" / leaderboard page for discipline** — V1 is the per-player card
  only. No `/discipline` route, no ranked board (see Non-goals).
- **DD (`dd_*`) feeds** — ValuCast is DD-independent. This layer's only inputs are
  MLB StatsAPI (public) and the ValuCast prospect universe (mlbam ids of tracked
  hitters). Do NOT read `data/dd/*`.

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**:
  master auto-deploys valucast.app via Render. Commit locally; the reviewer gates
  the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — untracked feeds/caches and
  pytest byproducts must not be swept in). Stage each in-scope file explicitly by
  path. **Never `git stash`.**
- Do NOT stage `data/prediction_archive/.../2026-06-15.json` (pytest byproduct) or
  any untracked `data/dd/*`.
- **Do NOT commit raw game feeds** — only the compact per-pitch intermediate cache
  and the final per-player artifact (both explicit paths in Scope).
- Commit message style (short imperative subject), e.g.
  `Add plate-discipline data layer (StatsAPI play-by-play): exact swing/whiff bars + estimated zone bars on prospect cards`.

## Steps

### Step 0: Confirm the reuse surfaces are live before building

```
# The MiLB-fetch precedent exists with the sportId map + atomic write + tiny guard:
python -c "import scripts.refresh_milb_season_stats as m; print(m.SPORT_LEVELS, hasattr(m,'write_milb_season_stats'), hasattr(m,'_assert_not_tiny_refresh'))"
# expect: {11:'AAA',12:'AA',13:'A+',14:'A'} True True
# The fail-soft reader precedent exists:
python -c "from web.statcast_store import StatcastStore; s=StatcastStore(); print(hasattr(s,'display_groups'))"
# expect: True
# The card context builder + profile-bars widget exist:
python -c "import app; print(hasattr(app,'_build_dynasty_player_detail_context'))"
# expect: True
# There is NO plate-discipline module/artifact yet:
python -c "import importlib.util as u; print(u.find_spec('prospects.pitch_discipline'))"
# expect: None  (Step 1 creates it)
# The daily build graph + YAML commit block exist:
python -c "import scripts.run_daily_public_build as r; print(len(r.BUILD_STEPS), len(r.VALIDATE_STEPS))"
# expect: two integers
```
**Verify**: all confirm the state above. If `prospects.pitch_discipline` already
exists or a `valucast_pitch_discipline.json` is already committed, someone landed
here first — STOP and reconcile.

### Step 1: The pure counting module `prospects/pitch_discipline.py`

Adapt the spike's counting logic into a **pure, testable** module. NO network, NO
file I/O in these functions — a unit test calls them with a synthetic `allPlays`
list. The core is one function that, given a list of `allPlays` for one game and a
batter mlbam id, returns per-pitch counts:

```python
"""ValuCast-owned plate-discipline counting from MLB StatsAPI play-by-play.

Pure functions over already-fetched game-feed play lists; NO network, NO file I/O
(fetch + I/O live in scripts/build_pitch_discipline.py). Observe-only display
context, NEVER a value input (the milb_translation precedent).

EXACT vs ESTIMATED split:
  - Swing/Whiff/SwStr are MEASURED from pitch-outcome descriptions (exact — matched
    ProspectSavant to the decimal in the 7/10 spike).
  - Zone metrics (Chase/Z-Swing/Z-Contact/Zone) are ESTIMATED from legacy pixel
    coordinates because modern tracked pX/pZ are 100% absent at AA. They carry
    zone_estimated=True and MUST render tagged as estimates.
  - Exit velocity is IMPOSSIBLE from public AA data and is never produced here.
"""
from __future__ import annotations

# Plate half-width in feet (rulebook zone ~17in ball-adjusted); used only when REAL
# tracked coords (pX/pZ) exist. Pixel coords go through calibrate_pixel() instead.
_ZONE_HALF_WIDTH_FT = 0.83


def _is_swing(desc: str, is_in_play: bool) -> bool:
    # A swing = ball put in play, OR the description says the batter swung/fouled.
    # Bunts are special-cased: a foul/missed bunt is a swing attempt.
    if is_in_play:
        return True
    if "foul bunt" in desc or "missed bunt" in desc:
        return True
    return "swinging" in desc or "foul" in desc


def _is_whiff(desc: str) -> bool:
    # A whiff = swing that missed. "swinging strike" (incl. "...blocked") or a
    # missed bunt. NOT a foul (foul = contact).
    return "swinging strike" in desc or "missed bunt" in desc


def count_player_pitches(all_plays: list, batter_id: int) -> dict:
    """Per-pitch counts for one batter across one game's allPlays.

    Returns a dict of raw integer counts (never rates): pitches, swings, whiffs,
    contact, plus zone-conditioned counts when coordinates are usable:
    in_zone, out_zone, o_swings (chase), z_swings, z_contact, plus
    zone_pitches_with_coords (denominator honesty). Rates are computed later, once,
    from summed counts — so multi-game aggregation stays exact.
    """
    c = {
        "pitches": 0, "swings": 0, "whiffs": 0, "contact": 0,
        "in_zone": 0, "out_zone": 0, "o_swings": 0, "z_swings": 0,
        "z_contact": 0, "zone_pitches_with_coords": 0,
    }
    for play in all_plays:
        matchup = play.get("matchup") or {}
        if (matchup.get("batter") or {}).get("id") != batter_id:
            continue
        for ev in play.get("playEvents") or ():
            if not ev.get("isPitch"):
                continue
            det = ev.get("details") or {}
            desc = (det.get("description") or "").lower()
            is_in_play = bool(det.get("isInPlay"))
            # Intentional balls / pitchouts / automatic balls are not swing
            # opportunities in the usual sense but ARE pitches seen; they simply
            # never register as swings (no swinging/foul/inplay in the description).
            c["pitches"] += 1
            swing = _is_swing(desc, is_in_play)
            if swing:
                c["swings"] += 1
                if _is_whiff(desc):
                    c["whiffs"] += 1
                else:
                    c["contact"] += 1
            # Zone conditioning (estimated) — only when coordinates are usable.
            pd = ev.get("pitchData") or {}
            zone = classify_zone(pd)   # True=in, False=out, None=unusable
            if zone is not None:
                c["zone_pitches_with_coords"] += 1
                if zone:
                    c["in_zone"] += 1
                    if swing:
                        c["z_swings"] += 1
                        if not _is_whiff(desc):
                            c["z_contact"] += 1
                else:
                    c["out_zone"] += 1
                    if swing:
                        c["o_swings"] += 1   # chase
    return c
```

**The zone classifier `classify_zone(pitch_data)`** is the estimated part. It must
prefer REAL tracked coords when present (AAA has them) and fall back to the pixel
calibration otherwise:

```python
def classify_zone(pitch_data: dict, calib=None) -> bool | None:
    """True=in-zone, False=out-of-zone, None=cannot determine.

    Order of preference:
      1. Real tracked pX/pZ (present at AAA, absent at AA): |pX| <= 0.83 ft and
         szBottom <= pZ <= szTop. This is the ground truth the pixel calibration
         is fit against.
      2. Legacy pixel coords.{x,y} + strikeZoneTop/Bottom, mapped to feet via a
         fitted affine calibration (see calibrate_pixel). ESTIMATE.
      3. Missing strikeZoneTop/Bottom -> fall back to a league-default vertical
         band, and mark the pitch as reducing zone-metric quality (the build
         script counts these toward an 'estimated_quality' denominator).
      4. No usable coords at all -> None (excluded from zone denominators).
    """
    co = pitch_data.get("coordinates") or {}
    px, pz = co.get("pX"), co.get("pZ")
    szt, szb = pitch_data.get("strikeZoneTop"), pitch_data.get("strikeZoneBottom")
    if isinstance(px, (int, float)) and isinstance(pz, (int, float)) \
       and isinstance(szt, (int, float)) and isinstance(szb, (int, float)):
        return abs(px) <= _ZONE_HALF_WIDTH_FT and szb <= pz <= szt
    x, y = co.get("x"), co.get("y")
    if calib is not None and isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return calib.classify(x, y, szt, szb)   # estimated (Step 3)
    return None
```

Also add `rates_from_counts(counts)` returning the display rates from summed counts
(so aggregation across a season is exact — sum counts, then divide once):
`swing_pct = swings/pitches`, `whiff_pct = whiffs/swings`, `swstr_pct =
whiffs/pitches`, and (estimated) `chase_pct = o_swings/out_zone`, `z_swing_pct =
z_swings/in_zone`, `z_contact_pct = z_contact/z_swings`, `zone_pct =
in_zone/zone_pitches_with_coords`. Each rate returns `None` when its denominator is
0 (never a divide-by-zero, never a fabricated 0%).

**Verify**:
- `python -c "from prospects.pitch_discipline import count_player_pitches; ap=[{'matchup':{'batter':{'id':1}},'playEvents':[{'isPitch':True,'details':{'description':'Swinging Strike'}},{'isPitch':True,'details':{'description':'Ball'}},{'isPitch':True,'details':{'isInPlay':True,'description':'In play, out(s)'}}]}]; c=count_player_pitches(ap,1); print(c['pitches'],c['swings'],c['whiffs'],c['contact'])"` -> `3 2 1 1`.
- Foul is a swing, not a whiff; a plain ball is neither: assert against a fixture.

### Step 2: The build script `scripts/build_pitch_discipline.py` — backfill (checkpointed) + incremental + the compact cache

Mirror `refresh_milb_season_stats.py`'s network idiom (User-Agent Request, timeout,
atomic write, tiny guard). This script owns ALL network and I/O.

**2a — Game discovery per player.** For each tracked hitter (mlbam id) at each level:
```python
# gameLog gives the player's gamePks at a level (sportId 11/12/13/14):
url = f"https://statsapi.mlb.com/api/v1/people/{pid}/stats?stats=gameLog&season={season}&group=hitting&sportId={sport_id}"
games = [s["game"]["gamePk"] for s in data["stats"][0]["splits"]]
```
**Dedupe gamePks** across the player's rows (a suspended/resumed game or a
doubleheader can surface the same or paired pks — dedupe by pk; a resumed game's
continuation is a distinct pk but the player's plate appearances are attributed to
the pk they occurred under, so counting each pk once is correct).

**2b — The compact per-pitch cache (size discipline, REQUIRED).** ~8k feeds at raw
size is far too large to commit. So the cache is **NOT raw feeds** — for each
gamePk, fetch the feed once, extract ONLY the per-pitch fields the counter needs
(batter id, description, isInPlay, coordinates.{pX,pZ,x,y}, strikeZoneTop/Bottom),
and store that compact slice keyed by gamePk in
`data/prospects/raw/pitch_discipline_pitch_cache.json`. A final feed is immutable,
so a cached gamePk is NEVER re-fetched. This cache is the resumable checkpoint AND
the size-bounded committed intermediate.
- **Size strategy**: store only the ~7 scalar fields per pitch; prune gamePks older
  than the current + prior season on each incremental run (a `--prune-before-season`
  arg) so the cache tracks ~1.5 seasons, not the whole history. If even the compact
  cache grows past a soft ceiling (e.g. > ~40MB), the fallback is to keep the cache
  UNcommitted (rebuildable from network) and commit only the final per-player
  artifact — decide this at implementation time based on the measured size and note
  the decision in the plan status.

**2c — Checkpointed backfill (`--backfill`).** Must survive interruption. After every
N gamePks (e.g. 50), atomically flush the compact cache to disk (write `.tmp`,
`os.replace`). On restart, load the cache and skip any gamePk already present. Rate-
limit ~0.15s between feed fetches (`time.sleep(0.15)`) as StatsAPI courtesy. Log
progress (`fetched X/Y, cached Z, skipped W`). A `--limit-games` arg caps fetches for
dev smoke.

**2d — Incremental (default mode).** ~60-90 new game feeds/day. Re-run gameLog for
each tracked hitter, diff against cached gamePks, fetch only the new pks, update the
cache, recompute the artifact. **StatsAPI outage handling**: if the gameLog or feed
fetch fails (network error / non-200 / empty), the incremental run must **no-op
gracefully** — keep the existing artifact + cache untouched, exit 0 with a logged
warning, so the stale artifact keeps serving with its `as_of` date. Do NOT write a
truncated artifact on a partial fetch (that is what the tiny-guard also backstops).

**2e — Assemble per-player counts.** For each tracked hitter, sum
`count_player_pitches` across their cached gamePks, split BY LEVEL (a player who
went AA→AAA gets separate AA and AAA count buckets — never blended). Attach the
per-level `zone_estimated` flag (True whenever the level's zone counts came from the
pixel calibration rather than real pX/pZ; AAA may be exact, AA/A+/A estimated).

**Verify**:
- `python scripts/build_pitch_discipline.py --player 701527 --season 2026 --level AA --limit-games 3` -> fetches 3 feeds, writes a cache + a one-player artifact slice, no exception.
- Re-run the same command -> the 3 gamePks are cache hits (0 new fetches) — proves resumability.

### Step 3: The pixel→feet calibration (the estimated part; CUT-CANDIDATE)

Legacy `pitchData.coordinates.{x,y}` are screen pixels; `pX`/`pZ` are feet. Fit a
mapping so AA/A+/A pixel coords can be classified in/out of zone.

- **Fit set**: games/levels where BOTH pixel `x,y` AND tracked `pX,pZ` exist. AAA
  has tracked coords, so AAA feeds provide (pixel, feet) pairs. Fit a single global
  affine map `pX ≈ a*x + b`, `pZ ≈ c*y + d` (least squares over the paired sample;
  the horizontal and vertical axes fit independently). Persist the fitted
  coefficients in the artifact metadata (`calibration: {a,b,c,d, n_pairs,
  fit_r2, fitted_at}`) so the numbers on the page are reproducible from the
  committed artifact.
- **Classify**: map pixel (x,y) → estimated (pX,pZ) → in-zone iff `|pX_est| <= 0.83`
  and `szBottom <= pZ_est <= szTop`. When `szTop/szBottom` are missing, fall back to
  a league-default vertical band (constants, documented) and count the pitch toward
  an `estimated_quality` denominator so the methodology can state what fraction of
  zone calls used the fallback.
- **Honesty**: the calibration is an ESTIMATE. Every zone metric derived from it
  carries `estimated: true`. The card tags it "est." and links to methodology.
- **Drift note**: pixel scales can differ by venue/camera. V1 uses a single global
  fit (simplest honest approach); if the fit `r2` is poor or venue drift is
  material, a per-venue fit is a documented follow-up, NOT a V1 requirement. Record
  the global fit quality in metadata so the follow-up decision is data-driven.

**If cutting to hold Effort**: skip Step 3 entirely, produce exact metrics only, and
have the reader/card render just the exact group. File the zone group as a
fast-follow.

**Verify**:
- On a AAA sample, classify with real `pX/pZ` and with the pixel calibration; assert the calibrated in/out agreement with the real coords is high (e.g. >85% on the held-out AAA pairs) — this is the calibration-quality check that justifies shipping the estimate.

### Step 4: Cohort percentiles by level (min-sample gate is a hard requirement)

For each level cohort (AA, A+, etc.), compute the midrank percentile of each metric
across all tracked hitters IN THAT LEVEL who clear the minimum-sample threshold.

- **Min-sample gate**: a player-level bucket needs `>= 300 pitches seen` (tune at
  implementation; state the chosen floor in the artifact metadata) to (a) enter the
  cohort pool AND (b) render a bar. Below the floor: NO percentile bar renders for
  that player at that level — small-sample honesty is non-negotiable (this mirrors
  the card's existing 100 PA / 20 IP floor discipline).
- **Percentile math**: use the SAME midrank formula as
  `prospect_percentiles.percentile_for` (below+0.5*ties)/n, clamped 1..99, and
  orient each metric to quality-direction (higher-is-better after orientation):
  Swing% is neutral-ish but for card consistency treat higher-contact / lower-whiff
  as better — decide orientation per metric and document it (Whiff%, SwStr%,
  Chase% are LOWER-IS-BETTER; Z-Contact% is higher-is-better; Swing%/Z-Swing%/Zone%
  are contextual — present the RAW value always and only attach a percentile where a
  quality direction is defensible, else show the raw number with no fill judgment).
- **Multi-level seasons**: percentiles are computed WITHIN each level cohort; a
  multi-level player shows a per-level row set (AA bars vs the AA cohort, AAA bars vs
  the AAA cohort), NEVER a blended "across AA/A+" percentile. The existing card copy
  precedent for multi-level honesty ("A and A+" naming) applies.
- Store per player: `{ "<mlbam>": { "AA": {"pitches": N, "swing_pct": .., ...,
  "percentiles": {...}, "zone_estimated": true}, "AAA": {...} }, ...}` plus a
  top-level `cohorts` block (per-level cohort sizes + the min-sample floor + the
  calibration metadata) so the numbers are reproducible and the validator can check
  them.

**Verify**:
- A synthetic cohort of players with known counts produces the expected midrank
  percentiles; a player below the 300-pitch floor produces NO `percentiles` entry.

### Step 5: The fail-soft reader `web/pitch_discipline_store.py`

Model on `StatcastStore`: lazy `_ensure_loaded`, degrade to empty on
`OSError`/`ValueError`, keyed by `str(mlbam_id)`. `groups_for(mlbam_id)` returns
card-ready groups or `[]`:

```python
# One group PER LEVEL the player has a qualifying bucket for, each:
# {"level": "AA", "as_of": "...", "estimated": True/False (any estimated metric),
#  "metrics": [
#     {"key":"swing_pct","label":"Swing%","raw":..,"display":"37.4%","pct":..,"estimated":False},
#     {"key":"chase_pct","label":"Chase%","raw":..,"display":"..","pct":..,"estimated":True},
#     ...]}
```
Exact metrics carry `estimated: False`; zone metrics carry `estimated: True`. A
metric with no percentile (below floor, or no defensible quality direction) is
returned with `pct: None` and the template renders the raw value without a fill
judgment (or is omitted — decide, and keep it consistent). Provide `as_of` (the
artifact's build date) for the provenance line. Instantiate once in app.py
(`pitch_discipline_store = PitchDisciplineStore()`, next to `statcast`).

**Verify**:
- `python -c "import app; print(app.pitch_discipline_store.groups_for('nonexistent'))"` -> `[]` (fail-soft).
- With the artifact built: `groups_for('701527')` returns a list with an "AA" group whose metrics include Swing%/Whiff%/SwStr% (`estimated False`) and, if Step 3 shipped, Chase% (`estimated True`).

### Step 6: Wire into the card context + template

**6a — Context** (`app.py:_build_dynasty_player_detail_context`, ~8431): inside the
`if dd_row.is_prospect:` block, add to `prospect_context`:
```python
"plate_discipline": pitch_discipline_store.groups_for(getattr(dd_row, "mlbam_id", None)),
```
It flows to the template via the existing `context.update(prospect_context)`
(app.py:8491). Non-prospects and players without data get nothing (empty list →
section not rendered).

**6b — Template** (`templates/partials/player_detail_dynasty.html`): add a
`{% if plate_discipline %}` sub-section (inside or just after the
`prospect-profile-card` block, ~line 143). Reuse the `.prospect-profile-bars` /
`.profile-bar-*` markup. For each level group, render its metric bars; tag every
`metric.estimated` row with a small "est." marker and a link to
`/methodology#plate-discipline`. Add a provenance line: "Computed from MLB
play-by-play feeds{% if group.as_of %} - as of {{ group.as_of }}{% endif %}." Use the
existing fill-class logic (`elite`/`good`/`risk`/`neutral`) only where `metric.pct`
is not None; where `pct` is None, render the raw value with a neutral rail (no
quality judgment).
- **All estimated numbers visibly labeled**: the "est." tag + the methodology link
  is mandatory on estimated rows. An estimated number must never look like a
  measurement.

**Verify**:
- `python -c "import jinja2; jinja2.Environment(loader=jinja2.FileSystemLoader('templates')).get_template('partials/player_detail_dynasty.html')"` -> no exception.
- Card render for a prospect WITH data contains "Plate Discipline" and "est." (if Step 3 shipped) and the `/methodology#plate-discipline` link.
- Card render for a prospect WITHOUT data does NOT contain the section (no empty shell).

### Step 7: Methodology section

In `templates/methodology.html`, add an anchored section
(`id="plate-discipline"`) that states, plainly:
1. **Exact metrics** (Swing%, Whiff%, SwStr%) are counted directly from MLB's
   public play-by-play pitch descriptions — reproducible, and validated against
   ProspectSavant to the decimal (cite the Sirota match as the proof point without
   over-claiming).
2. **Estimated metrics** (Chase%, Z-Swing%, Z-Contact%, Zone%) come from a pixel-
   coordinate calibration because modern tracked coordinates are absent at the
   minor-league levels; they are estimates, labeled "est." on the card.
3. **Why there is no exit velocity / batted-ball data**: public minor-league play-
   by-play carries no batted-ball tracking, so ValuCast does not show (and will not
   estimate) EV or contact-quality metrics at these levels.
4. **Cohorts**: percentiles compare a player to others AT THE SAME LEVEL, with a
   minimum pitches-seen sample; below it, no bar renders.

Match the methodology page's existing section grammar (see the
`#dynasty-value-scale` section as the style reference). Keep it honest and specific.

**Verify**:
- `python -c "import app; c=app.app.test_client(); h=c.get('/methodology').data.decode(); print('plate-discipline' in h and 'exit velocity' in h.lower())"` -> `True`.

### Step 8: Wire the incremental build into the daily pipeline (LAST)

**8a — Build graph** (`scripts/run_daily_public_build.py`): append
`("scripts/build_pitch_discipline.py",)` to `BUILD_STEPS` (the default incremental
mode) and `("scripts/validate_pitch_discipline.py",)` to `VALIDATE_STEPS`. Place the
build step AFTER the prospect universe/rank steps (it needs the tracked-hitter id
list) and the validator near the other `validate_*` entries.

**8b — YAML** (`.github/workflows/daily-public-data.yml`): add the artifact +
compact cache paths to the `git add \` block (line 151-243):
```
data/models/valucast_pitch_discipline.json \
data/prospects/raw/pitch_discipline_pitch_cache.json \
```
(Only add the cache path if 2b's decision was to commit it. If the cache is kept
UNcommitted, add ONLY the artifact.) If the incremental fetch is better run in the
fetch phase, add a "Refresh plate-discipline metrics" step alongside the existing
"Refresh …" steps (line 109-119) instead of relying on the `BUILD_STEPS` entry —
pick one, not both, to avoid a double fetch.

**8c — Graceful degradation**: confirm the incremental step's outage no-op (Step 2d)
means a StatsAPI-down morning does not fail the whole daily build (the step exits 0
with the stale artifact intact).

**Verify**:
- `python -c "import scripts.run_daily_public_build as r; print(any('pitch_discipline' in ' '.join(s) for s in r.BUILD_STEPS), any('validate_pitch_discipline' in ' '.join(s) for s in r.VALIDATE_STEPS))"` -> `True True`.
- `grep -n "valucast_pitch_discipline.json" .github/workflows/daily-public-data.yml` -> appears in the `git add` block.

### Step 9: Full suite + restore the byproduct

```
python -m pytest -q
git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json
git status --short
```
**Verify**: full suite green (~1871+ pass, plus the new assertions); `git status`
shows ONLY in-scope files (the new module/scripts/reader/tests, the two artifacts,
the template + methodology + app + daily-build edits) — the untracked `data/dd/*`
is NOT staged and the archive byproduct is restored. No raw game feeds staged.

## Test plan

- `tests/fixtures/pitch_events.py` — a small synthetic `allPlays` fixture covering:
  a swinging strike (whiff), a called ball, a foul (swing + contact), a foul bunt
  (swing), a missed bunt (whiff), a ball-in-play, an intentional ball, a pitchout,
  a pitch with real `pX/pZ` in-zone, one out-of-zone, one with only pixel `x/y`,
  one with missing `strikeZoneTop/Bottom`, and a pitch by a DIFFERENT batter
  (must be ignored). Plus a `PID` constant.
- `tests/test_pitch_discipline.py` (counting logic — the load-bearing exactness):
  1. **Swing detection**: in-play, swinging, foul, foul bunt, missed bunt all count
     as swings; called ball / called strike / intentional ball / pitchout do not.
  2. **Whiff detection**: swinging strike + missed bunt are whiffs; a foul is a
     swing but NOT a whiff (contact).
  3. **Denominators exact**: SwStr% = whiffs/pitches, Whiff% = whiffs/swings,
     Swing% = swings/pitches — assert the exact ratios on the fixture.
  4. **Batter filter**: pitches to a different batter id are excluded.
  5. **Zone classify**: real `pX/pZ` in/out is correct; missing coords -> None
     (excluded from zone denominators); a divide-by-zero denominator -> the rate is
     None, never 0.0 or an exception.
  6. **Multi-game aggregation is exact**: summing counts across two fixture games
     then computing rates == the single combined computation (proves count-then-
     divide, never averaging rates).
- `tests/test_pitch_discipline_store.py` (reader):
  1. **Fail-soft**: missing/malformed artifact -> `groups_for(x) == []`, no
     exception.
  2. **Estimated flag**: a built fixture artifact returns exact metrics with
     `estimated False` and (if present) zone metrics with `estimated True`.
  3. **Min-sample gate**: a player below the pitch floor returns no bar for that
     level (no `percentiles`).
  4. **Per-level, never blended**: a two-level player returns two groups (AA, AAA),
     each scored against its own cohort.
- `tests/test_app.py` additions:
  1. **Card renders the section with data**: `GET /player/<prospect id with a
     fixture bucket>` -> 200, HTML contains the plate-discipline heading and the
     `/methodology#plate-discipline` link.
  2. **Estimated rows tagged**: if Step 3 shipped, the HTML contains "est." on a
     zone-metric row.
  3. **No section without data**: a prospect with no bucket -> 200, no empty
     plate-discipline shell.
  4. **Network-free serving (structural)**: assert the reader module
     (`web.pitch_discipline_store`) source imports no `urllib`/`requests`/`http`
     (the fetch lives only in `scripts/build_pitch_discipline.py`) — the same
     network-free-at-runtime lock the Statcast layer relies on.
- `tests/test_pitch_discipline_schema.py` (or fold into the reader test) — validate
  the committed artifact (or a fixture) against the expected schema: per-player
  per-level buckets, `zone_estimated` bool per level, sample-size int, `cohorts`
  metadata with the min-sample floor + (if Step 3) `calibration` coefficients.
- Template render smoke: `player_detail_dynasty.html` + `methodology.html` load with
  no exception.
- Final: `python -m pytest -q` all green, then restore the archive byproduct.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (~1871+ pass); the byproduct file restored after.
- [ ] `prospects/pitch_discipline.py` counting functions are PURE (no network, no
      file I/O) and reproduce the spike's Swing%/Whiff%/SwStr% definitions exactly
      (fixture-tested).
- [ ] `scripts/build_pitch_discipline.py` backfill is checkpointed/resumable (a
      re-run re-uses the compact cache, 0 re-fetches of cached gamePks) and rate-
      limited (~0.15s); the incremental mode no-ops gracefully on a StatsAPI outage
      (stale artifact keeps serving).
- [ ] The committed intermediate is the COMPACT per-pitch cache (or is left
      uncommitted per 2b's size decision) — **raw game feeds are never committed.**
- [ ] Cohort percentiles are BY LEVEL with a hard minimum-pitch gate; below it NO
      bar renders. Multi-level seasons show per-level rows, never blended.
- [ ] Exact metrics (Swing%, Whiff%, SwStr%) render as measured; if the zone group
      shipped, estimated metrics (Chase%, Z-Swing%, Z-Contact%) render visibly
      tagged "est." with a `/methodology#plate-discipline` link.
- [ ] The card provenance line states "Computed from MLB play-by-play feeds."
- [ ] The methodology section explains exact-vs-estimated, the pixel calibration,
      and why EV is absent.
- [ ] Serving is network-free: the reader imports no network library; all fetch is
      in the build script (structural test passes).
- [ ] The daily build wires the INCREMENTAL step + validator, and the artifact
      (plus cache, if committed) is in the YAML `git add` block.
- [ ] NO exit-velocity / batted-ball metric is produced or estimated anywhere.
- [ ] No discipline number flows into the value/scoring path, the scouting-read
      text path, or any PNG/`_PNG_CACHE_PARAMS`.
- [ ] `prospects/ahead_of_consensus.py` and
      `scripts/build_ahead_of_consensus_scorecard.py` untouched
      (`git diff --stat` empty for them).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- **Anyone tries to produce or estimate exit velocity / batted-ball quality** from
  MiLB data. It is impossible from public play-by-play and forbidden. STOP.
- **An estimated zone metric would render without the "est." tag / methodology
  disclosure** — that presents an estimate as a measurement. Do not ship it; either
  add the disclosure or cut the zone group.
- **The min-sample gate is being bypassed** (a bar rendering below the pitch floor,
  or a cohort including sub-floor players). Small-sample honesty is non-negotiable —
  STOP and restore the gate.
- **The compact cache or artifact would balloon past the size budget** and the
  response is "just commit the raw feeds" — no. Either keep the compact extraction,
  prune older seasons, or leave the cache uncommitted (rebuildable). Never commit
  raw feeds. If the artifact itself is too large, reduce what's stored per player
  (counts + percentiles only, not per-pitch detail).
- **A discipline number is about to flow into the 0-150 value / z-scores / peak
  projection / a ranking** — this layer is observe-only display context (the
  milb_translation precedent). If you find yourself wiring it into a value input,
  STOP.
- **The StatsAPI endpoint shape changed** (gameLog `stats[0].splits[].game.gamePk`
  or `liveData.plays.allPlays[].playEvents[]` no longer resolve) — re-verify the
  feed shape against a live pull before building the counter on a guess. The 7/10
  spike shapes are the reference; a drift is a STOP-and-reconcile.
- **`_build_dynasty_player_detail_context` / the `profile_bars` render block was
  refactored away** — re-locate the prospect-card context assembly and the bars
  widget before wiring; do NOT invent a parallel card path.
- **Effort is clearly exceeding the window** after the exact metrics ship — invoke
  the cut line: cut the zone metrics (Step 3) + their card rows, then defer the
  daily incremental wiring, before cutting the min-sample gate or the exact-vs-
  estimated honesty (never cut those). Report what was cut.

## Non-goals (V1)

- **No pitcher-side plate discipline.** Hitters only. Pitcher induced-whiff/zone
  metrics are a symmetric but separate build (different cohort, card surface, and
  labeling) — a later plan.
- **No exit velocity, ever.** Not measured, not estimated, not at any MiLB level.
- **No new PNG share card / no new share-card query param.** V1 renders on the
  existing player-card page only; no `_PNG_CACHE_PARAMS` change.
- **No public "board" / leaderboard page for discipline.** V1 is per-player card
  bars only; no `/discipline` route, no ranked page. (A board is a natural
  fast-follow once the artifact is proven, but it is not V1 and would reopen the
  PNG-cache surface.)
- **No blended multi-level percentiles.** Per-level cohorts only.

## Rollout order

1. **Counting module + synthetic fixtures** (`prospects/pitch_discipline.py`,
   `tests/fixtures/pitch_events.py`, `tests/test_pitch_discipline.py`) — the exact
   definitions, fully unit-tested, before any network.
2. **Backfill** (`scripts/build_pitch_discipline.py --backfill`, checkpointed) — the
   compact cache + per-player counts, resumable.
3. **Cohort percentiles** (per-level, min-sample gate) into the artifact.
4. **Reader** (`web/pitch_discipline_store.py`) + app instantiation.
5. **Card UI** (template section, exact bars first; estimated bars if Step 3
   shipped, always tagged).
6. **Methodology** section.
7. **Wire the incremental step into the daily build LAST** (so a broken fetch never
   stalls the existing pipeline; the artifact serves stale-but-labeled until the
   wiring is proven).

## Risks

- **StatsAPI rate limiting / courtesy.** ~8k backfill feeds + ~60-90/day incremental
  hit a public API. Mitigations: ~0.15s inter-request sleep, the immutable-feed
  cache (a cached gamePk is never re-fetched), and a User-Agent header identifying
  the client. The backfill is a one-time cost; steady-state is small.
- **Pixel calibration drift by venue/camera.** Legacy pixel coordinate scales can
  differ across parks. V1 fits a single global affine map and records its quality
  (`fit_r2`, `n_pairs`) in the artifact. If drift proves material, a per-venue fit
  is a documented follow-up — the estimated label already hedges the honesty.
- **Cohort comparability as players promote.** A level cohort's composition shifts
  through the season (promotions/demotions), so a percentile is a snapshot-in-time
  comparison, not a stable rank. The daily rebuild keeps it current; the methodology
  states it is a within-level, current-cohort comparison.
- **Artifact / cache size growth.** ~8k feeds is the reason for the compact
  extraction + season pruning + the commit-or-not decision (2b). If it still grows,
  the STOP condition forces reducing stored detail before committing bulk.
- **Small-sample false precision.** Early-season buckets are thin. The hard min-pitch
  gate (no bar below the floor) is the primary defense; the per-level cohort keeps
  the comparison fair.
- **Estimate-as-measurement confusion.** The single biggest trust risk is a reader
  mistaking an estimated Chase% for a measured one. The mandatory "est." tag +
  methodology link + the per-level `zone_estimated` flag are the defense; the STOP
  condition enforces it.

## Maintenance notes

- **Exact vs estimated is the load-bearing distinction.** Swing/Whiff/SwStr are
  measured and match ProspectSavant to the decimal; the zone group is a pixel-
  calibration estimate. If a future MiLB level starts publishing tracked `pX/pZ`
  (as AAA does), that level's zone metrics can graduate from estimated to measured —
  flip its `zone_estimated` flag and drop the "est." tag for that level only.
- **The counting definitions are the contract.** Swing = in-play OR
  swinging/foul(+bunt specials); whiff = swinging strike OR missed bunt. These
  matched ProspectSavant exactly on 7/10; changing them re-baselines every number.
  Keep the fixture test as the regression lock.
- **Observe-only forever.** These are display context, never a value input — same as
  the MiLB translation layer. If a later plan wants discipline to influence value,
  that is a scoring change with its own gate, not a quiet wiring here.
- **The cache is a rebuildable checkpoint.** A final game feed is immutable, so the
  compact cache can always be rebuilt from network if lost. If size ever forces
  dropping it from the commit, serving is unaffected (the reader reads the artifact,
  not the cache) — only the backfill speed is.
- **Keep discipline numbers out of scouting-read text.** They are card bars only in
  V1. If a future change surfaces them in read prose, the number must pass the
  plan-015 word-form / plan-021 rounding grounding guard in `scouting/mlb_read.py` —
  do not route around it.
