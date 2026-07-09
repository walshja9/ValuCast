# Plan 013: Cohort/window honesty — align the shape-comps spans, and make the /buys and /movers fineprint match what the pills and filters actually do

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 72e68864..HEAD -- prospects/comps.py templates/partials/player_detail_dynasty.html templates/methodology.html web/buy_score.py app.py prospects/movers.py templates/buys.html templates/movers.html`
> At the time this plan was written only **app.py** had changed since
> `72e68864` — the in-flight Call-Up Receipts rescoring work is uncommitted in
> the working tree (`app.py`, `prospects/call_up_receipts.py`,
> `templates/receipts.html`, `tests/test_call_up_receipts.py`). That work does
> NOT touch the `_build_buys_page_context` region (app.py ~7540–7632) this plan
> edits, but **re-read that region against HEAD before editing** and confirm the
> excerpts below still match. If `prospects/comps.py`, `web/buy_score.py`,
> `prospects/movers.py`, or any of the three templates changed since
> `72e68864`, compare the "Current state" excerpts against the live code before
> proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M (three independent copy/label fixes; one carries small tests)
- **Risk**: LOW (display/labeling only — no scoring, math, or artifact-schema changes)
- **Depends on**: none. Touches app.py in a region disjoint from plans 005/007; if landing alongside them, re-run the drift check.
- **Category**: honesty (provenance / falsifiability / window-labeling)
- **Planned at**: commit `72e68864`, 2026-07-09

## Why this matters

ValuCast's brand is that a number never says more than it can defend. The 7/9
claims-register audit found three window/cohort surfaces where the copy claims a
span or a filter the data does not actually deliver. Each is a
screenshot-in-one-tweet failure for a site branded on dated honesty:

1. **Shape-comps card (provenance + falsifiability).** The "Closest MLB Shapes"
   card headlines the aging bars "Real MLB seasons (2000–2025)", but the entire
   OUTCOME cohort that drives those bars is drawn only from match seasons
   2000–2020 (a 5-season follow-up window has to end by 2025). *Embarrassment
   scenario from the register:* "A reader sees the aging bars headlined
   '2000–2025' … realizes every single outcome tier is computed from a frozen
   2000–2020 window, and posts that ValuCast's '2000–2025' framing is really a
   2000–2020 outcome study wearing a 2025 label — the aging bars can never
   include a modern comp by construction." Compounding it: the three named
   "shape twins" are the nearest matches *regardless of season*, so a twin from a
   post-2020 season renders with **no** aging verdict while further-away twins
   show one. *Register:* "Carlos Rodriguez's #1 closest twin is Bryson Stott '24
   (NO outcome tag shown), while his #2 and #3 twins … show 'everyday regular'. A
   sharp reader sees the CLOSEST match conspicuously has no aging label while
   further matches do, and reasonably infers either a data bug or cherry-picking"
   — when the real reason (Stott '24 has no complete 5-year window yet) is never
   stated. 43 of 105 players (41%) show this blank-vs-labeled asymmetry.

2. **/buys fineprint (provenance).** The fineprint says "Form curves span the
   tracked value history within the current scoring era (tracking began June
   13)" and offers All / 7d / 14d / 21d / 30d window pills. In reality
   `build_valucast_board` (web/buy_score.py:272) calls `clean_tail(score_history)`
   with **no** `window_days`, hard-capping every displayed curve at
   `MOMENTUM_WINDOW_DAYS = 14`; `build_spark(window_days=…)` can only shrink
   further, never widen. *Register:* "A sharp reader clicks the '30d' pill
   expecting a month of curve, sees no change from '14d' or 'All', opens the
   artifact (score_history goes back to 6/13), and points out the fineprint's
   'spans the tracked value history / tracking began June 13' is literally false
   — the curve is silently clamped to 14 days and three of the five window pills
   are inert." (The re-baseline epoch is actually 6/22, so "June 13" is doubly
   loose.)

3. **/movers fineprint (provenance).** The fineprint says "top-250 rank cap" with
   no qualifier, but the COOLING side is exempt by design: `movers.py:302` keys
   cooling eligibility on `start_rank`, so a faller can drop far past 250 and
   still show. *Register:* "A reader sees a COOLING row stamped '#595' or '#601'
   sitting directly under fineprint that promises a 'top-250 rank cap' and calls
   it a self-contradiction — either the cap is fake or the ranks are wrong. The
   nuance (cap applies to rising-current and cooling-START) is real and defensible
   but is nowhere on the surface, so it reads as a broken filter." Live examples:
   Tyson Neighbors #479, Jaxon Wiggins #448, Chris Clark #595, Thomas Harrington
   #409; the 14d board adds Andrew Walters #601.

All three fixes are copy/label + (for /buys) passing an already-existing
`window_days` through one call site. No scoring rule, artifact schema, or model
number changes.

## Current state

Verified against the live files at `72e68864` (app.py re-verify against HEAD per
drift check).

### (a) Shape-comps card

- **Builder `prospects/comps.py`** is honest and stays untouched:
  - `:37` `OUTCOME_HORIZON = 5`; `:161-165` `resolved_through` = `latest_season - OUTCOME_HORIZON` (= 2020 today, latest cached season 2025).
  - `:180-183` `outcome()` returns `None` when `season > resolved_through` — twins in a season past 2020 legitimately carry `outcome=None`.
  - `:219-243` twins = the `TWIN_COUNT` (3) nearest matches *regardless of season*, each with `outcome` populated only when resolvable.
  - `:245-257` the cohort loop **skips** any `row["season"] > resolved_through` — a strictly ≤2020 set.
  - `:272-277` emits `cohort = {"size": len(cohort_rows), "resolved_through": pool.resolved_through, "tiers": …, "median_pa_per_year": …}`. So `cohort.size` is the real rendered count (`len(cohort_rows)`), NOT the constant `COHORT_SIZE` — the template's `cohort.size` denominator is already honest; **do not "fix" it**.
  - Each twin dict (`:227-241`) carries `season` and `outcome` (dict or `None`). `distance` is present per twin but NOT per cohort row.
- **Template `templates/partials/player_detail_dynasty.html`** (region 184–221):
  - `:191` on-card note: `Real MLB seasons (2000–2025, era-adjusted) nearest his translated K% … ISO …`. (The `2000–2025` here is literal copy in the template, not read from the artifact.)
  - `:194-201` the twins loop; `:199` renders the outcome chip only `{% if twin.outcome %}` — a post-2020 twin renders a **blank** where others show a tier.
  - `:205` cohort note: `How this shape aged — the {{ shape_comps.cohort.size }} nearest matches old enough to judge (seasons through {{ shape_comps.cohort.resolved_through }}), …` — states the END year (2020) but not the START, and sits under the `2000–2025` headline.
  - `:207-216` the four tier bars, denominator `shape_comps.cohort.size` (honest).
  - `:220` closing disclaimer: `A shape match on three translated rates — descriptive, not a forecast. … Tiers measure playing time (PA/yr) plus era-relative OPS only …`. No clause telling the reader the aging bars only include matches old enough to grade (so the closest named twin may be absent from the bars).
  - `shape_comps.cohort.resolved_through` is accessible **anywhere** in this card block (sibling of `shape_comps.twins`), so the twins loop can compare `twin.season` against it template-side with no builder change.
- **Methodology `templates/methodology.html`** `:97-98`: "the real MLB seasons (2000–2025, age 26 or younger, 400+ PA) nearest the prospect's MLB-translated …" then `:102-104` "we show how the nearest matches with a complete five-season follow-up window actually aged". The two spans are adjacent but the page never states the outcome window's own year range.

### (b) /buys fineprint + window pills

- **`web/buy_score.py`**:
  - `:27` `MOMENTUM_WINDOW_DAYS = 14`.
  - `:80-106` `clean_tail(value_history, window_days=None)` — `reach = window_days or MOMENTUM_WINDOW_DAYS` (:91); step/gap guards always apply, only calendar reach is caller-tunable. **This function already accepts `window_days`** — movers passes it, buys does not.
  - `:272` inside `build_valucast_board`: `score_history = clean_tail(row.get("score_history") or ())` — **no `window_days`**, so it caps at 14d. This is the single line that makes the pills inert. `display_history` (`:273-277`) is that already-capped series; it becomes `row["value_history"]`.
- **`app.py`** `_build_buys_page_context` (~7563–7632):
  - `:7601` / `:7605` `row["spark"] = build_spark(row["value_history"], window_days=spark_window)` — `build_spark` (`web/value_spark.py:12-21`) only *trims* to the last N days; it can never widen beyond the 14-day-capped `value_history` it is handed.
  - `:7539` `SPARK_WINDOW_CHOICES = (7, 14, 21, 30)`; `:7545` `_parse_spark_window` accepts only those.
  - Context keys of interest: `spark_window`, `spark_window_choices`. There is **no** `buy_curve_reach` / window-reach key today; the fineprint string lives in the template (`templates/buys.html:43`), not in context.
- **`templates/buys.html`** `:43`: `Form curves span the tracked value history within the current scoring era (tracking began June 13). The <a href="/movers">Movers board</a> measures change over its own shorter window; different window, different question.` `:47-52` the pills, `{% for w in [none] + (spark_window_choices | list) %}` → All / 7d / 14d / 21d / 30d.
- **`prospects/buys.py`** `:32` `PROSPECT_BUYS_EPOCH = "2026-06-22-role-normalization"` — the real re-baseline is **6/22**, not 6/13. `score_history` (`:142-158`) carries every archived date (back to ~6/13), so the artifact genuinely has >14 days of history that the display throws away.

### (c) /movers fineprint

- **`prospects/movers.py`**:
  - `:24` `MAX_CURRENT_RANK = 250`.
  - `:296-303`: rising requires `current_rank <= MAX_CURRENT_RANK`; cooling requires `start_rank <= MAX_CURRENT_RANK` (comment: "Cooling eligibility keys on where the window STARTED, so a player who fell out of the top-N entirely still shows as a cooler."). The asymmetry is intentional and correct.
  - `:411` summary emits `current_rank_cap: MAX_CURRENT_RANK`.
- **`templates/movers.html`** `:30`: `{{ mover_count }} qualified of {{ … }} tracked prospects &middot; top-{{ movers_summary.current_rank_cap }} rank cap &middot; moves under &plusmn;{{ movers_summary.score_delta_threshold }} score don't qualify.` — the unqualified "top-250 rank cap" claim. `:83`/`:63` render `#{{ p.current_rank }}` on both sides, so a cooling row's past-cap current rank sits right under that line.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Buys unit/route tests | `python -m pytest -q tests/test_buy_score.py tests/test_valucast_buys.py` | all pass |
| Movers tests | `python -m pytest -q tests/test_movers.py` | all pass |
| Comps tests | `python -m pytest -q tests/test_prospect_comps.py` | all pass |
| Full suite (final) | `python -m pytest -q` | ~1771+ passed, 0 failed; then restore the byproduct (below) |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | file back to HEAD (pytest dirties it — NEVER commit it) |

## Scope

**In scope** (the only files you should modify):
- `web/buy_score.py` — thread `window_days` into the one `clean_tail` call (b).
- `app.py` — `_build_buys_page_context`: pass the pill's window into the board build, and add one context key for the honest reach so the fineprint can render it (b).
- `templates/buys.html` — rewrite the fineprint line (b).
- `templates/movers.html` — split the rank-cap fineprint per side (c).
- `templates/partials/player_detail_dynasty.html` — span-split copy, per-twin "too recent" chip, disclaimer clause (a).
- `templates/methodology.html` — one clause naming the outcome window's year range (a).
- Tests: `tests/test_buy_score.py` (extend), `tests/test_valucast_buys.py` (extend), `tests/test_movers.py` (extend if you touch summary; else leave).

**Out of scope** (do NOT touch):
- `prospects/comps.py` — the builder is honest (cohort is genuinely ≤2020, `cohort.size` is the real count). This plan is copy-only for shape-comps. Do NOT add per-cohort-row distance, do NOT change tier logic, do NOT change `COHORT_SIZE`.
- `prospects/movers.py` scoring/eligibility — the asymmetric cap is correct by design; only the template copy is wrong.
- `prospects/buys.py` and the buys artifact schema — `score_history` already carries the full history; the bug is purely that the display capped it.
- `prospects/ahead_of_consensus.py`, `scripts/build_ahead_of_consensus_scorecard.py` — the AOTC scorecard rules are FROZEN (pre-registered 7/2) until the ~7/13 gate unlock.
- The receipts in-flight work (`prospects/call_up_receipts.py`, `templates/receipts.html`, `tests/test_call_up_receipts.py`) — leave every uncommitted receipts change exactly as found.

### Register gaps deliberately EXCLUDED from this plan

- Shape-comps **tier-bat disclaimer** (medium, correctness): "Tiers measure PA/yr plus era-relative OPS" is only true of the top tier — belongs to a tier-semantics fix, not a window/cohort-honesty copy pass. Different theme.
- Shape-comps **cohort dispersion / tight-vs-loose comp set** (medium, uncertainty): requires the builder to compute a per-cohort-row distance and surface max/median — a `comps.py` change, out of scope for a copy-only plan.
- Shape-comps **raw-vs-era-adjusted displayed rates** (medium, provenance): requires the builder to expose the z/percentile it matched on — a `comps.py` change.
- Shape-comps **2020 pro-rate on-card note** (low, staleness): trivial and thematically adjacent — **INCLUDED** as an optional one-clause add in Step 1c because it is one word in copy the step already edits; if it complicates the diff, drop it and note so.

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**: master auto-deploys valucast.app via Render. Commit locally; the reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — parallel sessions and the in-flight receipts work leave the tree dirty). Stage each in-scope file explicitly. **Never `git stash`.**
- Do not stage or commit the receipts in-flight files or the pytest byproduct file.
- Commit message style (short imperative subject), e.g. `Align shape-comps spans; make /buys and /movers window fineprint honest`.

## Steps

### Step 1: Shape-comps — split the twin-search span from the outcome span

All edits in `templates/partials/player_detail_dynasty.html` (region 184–221) plus one clause in `templates/methodology.html`. No builder change.

**1a — State the cohort's START year, not just "through 2020".** The cohort's
window is `2000` → `resolved_through`. Edit the cohort note at `:205` so it names
both ends. Current:
```
How this shape aged &mdash; the {{ shape_comps.cohort.size }} nearest matches old enough to judge (seasons through {{ shape_comps.cohort.resolved_through }}), measured on playing time kept and era-relative bat over their next five years:
```
Change the parenthetical to name the full span explicitly, e.g. `(matches from 2000&ndash;{{ shape_comps.cohort.resolved_through }} — the seasons with a complete 5-year outcome window)`. Keep the rest of the sentence. The point: the reader must see that the aging bars are a 2000–2020 study, distinct from the 2000–2025 twin search headline above.

**1b — Render a "too recent to grade" chip for post-2020 twins.** At `:199` the
outcome chip renders only `{% if twin.outcome %}`. Add an `{% else %}` (or
`{% elif %}`) branch: when `twin.outcome` is falsy AND
`twin.season > shape_comps.cohort.resolved_through`, render an explicit muted chip
like `too recent to grade` (needs a 5-year window). Guard on `resolved_through`
being defined (`shape_comps.cohort and shape_comps.cohort.resolved_through`). A
twin with no outcome for any OTHER reason (there should be none today, but be
safe) renders nothing, as now — do not label a genuinely-unresolvable twin
"too recent". Use an existing muted chip style if one is available in this
template's CSS neighborhood; otherwise reuse the `shape-twin-outcome` span class
without a `tier-…` modifier so it inherits neutral styling. Do not invent new
CSS files.

**1c — Add the disclaimer clause (and optional 2020 note).** In the closing
disclaimer at `:220`, add one sentence: the aging bars include only matches old
enough to grade, so the closest named twin may not appear in the bars. Optionally
(see EXCLUDED list) append `(2020 pro-rated to a full schedule)` to the cohort
note at `:205` to match the methodology page. Keep the tone terse and factual.

**1d — Methodology parity.** In `templates/methodology.html` around `:102-104`,
add a short clause to the "how the nearest matches … actually aged" sentence
naming the outcome window's own range, e.g. "(match seasons 2000–2020 — the ones
with a complete five-season follow-up by 2025)". Do not restate the whole method.

**Verify**:
- `python -m pytest -q tests/test_prospect_comps.py` → all pass (this step is template-only; the builder tests must be untouched and green).
- Grep the two high-severity fixes landed:
  - `grep -n "too recent" templates/partials/player_detail_dynasty.html` → ≥1 hit.
  - `grep -n "2000" templates/partials/player_detail_dynasty.html` → the cohort note now names 2000 as the start (in addition to the `:191` headline).
- Manual render sanity (optional, if you can run the app): open a hitter prospect card where a named twin has a post-2020 season (e.g. any card whose #1 twin is a '21–'25 season) and confirm the chip reads "too recent to grade" instead of a blank, and the cohort note reads "matches from 2000–2020".

### Step 2: /buys — make the window pills real and the fineprint honest

**2a — Thread the window into the board build.** The pill's window
(`spark_window`) must reach `clean_tail` so the displayed curve can actually
re-span. Two-part change:

1. In `web/buy_score.py`, give `build_valucast_board` a `window_days` parameter
   and pass it through to the `clean_tail` call at `:272`:
   ```python
   def build_valucast_board(rows, n=BOARD_SIZE, window_days: int | None = None):
       ...
       score_history = clean_tail(row.get("score_history") or (), window_days=window_days)
   ```
   Default `None` preserves today's 14d behavior for every existing caller (the
   server-rendered share-card PNG stays on the canonical view). Keep
   `MIN_VALUCAST_BUY_SPARK_POINTS` gating as-is.
2. In `app.py` `_build_buys_page_context`, pass the page's window into the two
   `build_valucast_board` calls (`:7573` and `:7576`) so the page list re-spans:
   `build_valucast_board(buy_store.get_all(), window_days=spark_window)` (and the
   `n=n` variant likewise). The `build_spark(..., window_days=spark_window)` calls
   stay — they now trim a correctly-widened series. When `spark_window is None`
   ("All"), `clean_tail` falls back to `MOMENTUM_WINDOW_DAYS` (14) via its
   `reach = window_days or MOMENTUM_WINDOW_DAYS`; see 2b for what "All" must then
   claim.

**Correctness constraint**: `clean_tail`'s step/gap guards ALWAYS fire regardless
of `window_days` (buy_score.py:99-102) — widening the reach can never span the
6/22 re-baseline step, so a wider pill still cannot render a fake surge. Confirm
this in the code before trusting it; if any path lets a pre-epoch step through,
STOP.

**2b — Rewrite the fineprint to state the real reach.** In `templates/buys.html:43`,
replace the false "spans the tracked value history within the current scoring era
(tracking began June 13)" with copy that matches behavior. Two honest options —
pick based on what 2a delivers:
- If "All" still falls back to 14d (simplest, recommended): state that curves
  span up to the selected window within the current scoring era, the era
  re-based **June 22** (not June 13), and that "All" shows the last 14 days. E.g.
  `Form curves span the selected window within the current scoring era (re-based June 22); "All" shows the last 14 days.`
- Do NOT claim "spans the tracked value history" or "June 13" — both are the
  exact falsifiable statements the register flagged. If you make "All" genuinely
  reach the epoch instead of 14d, the copy must then say so and you must verify
  the epoch-step guard still holds.

To render the real reach in the fineprint, add a context key in
`_build_buys_page_context` (e.g. `"buy_curve_max_days": spark_window or buy_score.MOMENTUM_WINDOW_DAYS`)
and use it in the template rather than hardcoding "14". Keep the "different
window, different question" sentence pointing at /movers.

**Verify**:
- `python -m pytest -q tests/test_buy_score.py tests/test_valucast_buys.py` → all pass, plus your new tests (below).
- `grep -n "June 13\|tracked value history" templates/buys.html` → **no hits** (the false claims are gone).
- `grep -n "June 22\|re-based\|selected window" templates/buys.html` → the honest copy is present.
- Behavior spot-check (if you can run the app): request `/buys?window=30` and
  `/buys?window=7`; confirm the sparkline `window_days`/`delta` on at least one row
  DIFFERS between the two (they were identical before the fix). A pure-unit
  substitute is in the test plan.

### Step 3: /movers — disclose the rising/cooling cap asymmetry

Template-only. In `templates/movers.html:30`, split the "top-250 rank cap" claim
so it states the asymmetry the builder actually implements:
- Rising: capped at **current** top-250.
- Cooling: qualified at top-250 **at the window start** — a faller can drop below
  250 and still show.

Keep it inside the existing fineprint `<p>` (or add a second short `<p class="buys-fineprint">`), driven by `movers_summary.current_rank_cap` so the number stays single-sourced. Example phrasing:
```
Rising: current top-{{ movers_summary.current_rank_cap }}. Cooling: was top-{{ movers_summary.current_rank_cap }} at the window start — a faller can drop past it and still show.
```
Do not change `movers.py` or the summary payload.

**Verify**:
- `python -m pytest -q tests/test_movers.py` → all pass (no builder change, so these should be untouched-green).
- `grep -n "window start\|still show" templates/movers.html` → ≥1 hit.
- Confirm the number is still `{{ movers_summary.current_rank_cap }}` (not a hardcoded 250): `grep -n "current_rank_cap" templates/movers.html` → the cap references remain data-driven.

## Test plan

- `tests/test_buy_score.py`: **+1–2** unit tests on `build_valucast_board`:
  1. A row whose `score_history` spans >14 clean days: `build_valucast_board([row])`
     with default (`window_days=None`) yields a `value_history` capped near 14
     days; the same call with `window_days=30` yields a **longer** `value_history`
     (more points / a wider first→last calendar span). This is the direct
     regression proof that the pills are no longer inert. Model the fixtures on
     the existing `_row` / `_daily` helpers (test file lines ~15–29) and on
     `TestCleanTail` (line ~32). Ensure the series has no >`STEP_THRESHOLD` jump so
     the guard doesn't truncate it for an unrelated reason.
  2. (Optional) `window_days=None` still passes the `MIN_VALUCAST_BUY_SPARK_POINTS`
     gate identically to before (no behavior change for the default caller).
- `tests/test_valucast_buys.py`: **+1** route/context test if the file already
  exercises `_build_buys_page_context` against the committed feed: assert that the
  fineprint reach key (`buy_curve_max_days`) equals the requested `spark_window`,
  and that the context no longer implies a fixed 14. If the file is purely
  builder-level (it currently imports `build_buy_signals`), add the context
  assertion only if it fits the existing precedent — otherwise rely on the
  buy_score unit test and skip, noting why.
- `tests/test_movers.py`, `tests/test_prospect_comps.py`: **no new tests** — both
  changes are template copy with no builder change. Confirm the existing suites
  stay green (a comps or movers builder-test failure here means you touched a
  builder you shouldn't have — STOP).
- Final: `python -m pytest -q` all green, then
  `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (~1771+ passed, 0 failed); the byproduct file restored after.
- [ ] `grep -n "June 13\|tracked value history" templates/buys.html` → **0 hits**.
- [ ] `grep -n "window_days" web/buy_score.py` → `build_valucast_board` signature and its `clean_tail` call both pass it.
- [ ] `grep -n "build_valucast_board" app.py` → both call sites pass `window_days=spark_window`.
- [ ] `grep -n "too recent" templates/partials/player_detail_dynasty.html` → ≥1 hit (post-2020 twin chip).
- [ ] `grep -n "window start" templates/movers.html` → ≥1 hit (cooling-side disclosure).
- [ ] `git diff --name-only` shows ONLY: `web/buy_score.py`, `app.py`, `templates/buys.html`, `templates/movers.html`, `templates/partials/player_detail_dynasty.html`, `templates/methodology.html`, and the two extended buys test files — plus the pre-existing uncommitted receipts files, which you did not touch. The pytest byproduct is restored (not listed).
- [ ] `git diff --stat prospects/comps.py prospects/movers.py prospects/buys.py` → **empty** (no builder changes).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The `_build_buys_page_context` region in app.py (or the `build_valucast_board`
  caller shape) no longer matches the excerpts — the in-flight receipts work or
  plan 005/007 landed here first. Re-read, reconcile, and if the window is already
  threaded through differently, report instead of re-fixing.
- `clean_tail` no longer accepts `window_days`, or its step/gap guards became
  conditional on `window_days` — widening the reach could then render a fake
  re-baseline surge. Report; do not ship 2a.
- `prospects/comps.py` `resolved_through` / cohort loop changed such that
  `cohort.size` is no longer the real rendered count, or `twin.season` /
  `cohort.resolved_through` is no longer available to the template — the
  span-split copy would then misstate the data. Report.
- Any existing comps or movers **builder** test fails after your changes — you
  edited a builder that should have stayed untouched.

## Maintenance notes

- The /buys "All" pill: this plan's recommended path leaves "All" as a 14-day
  fallback (via `clean_tail`'s `reach = window_days or MOMENTUM_WINDOW_DAYS`) and
  makes the copy say so. If a future change wants "All" to genuinely reach the
  6/22 epoch, compute the epoch-reach the way `prospects/movers.py:336-343` does
  (`current_date - EPOCH_DATE` in days) and pass it as `window_days` — but then the
  fineprint MUST be updated in the same commit and the epoch-step guard re-verified.
- Shape-comps span-split is copy-only *because the builder is already correct*.
  If a later plan makes the cohort include post-2020 matches (e.g. a shorter
  outcome horizon), the "matches from 2000–2020" copy must move in lockstep with
  `resolved_through`; prefer rendering the range from `resolved_through` (already
  done for the end year) over hardcoding, and consider surfacing the START year
  from the artifact too if the builder ever exposes it.
- The /movers cap number is single-sourced from `movers_summary.current_rank_cap`
  — if `MAX_CURRENT_RANK` changes, the fineprint follows automatically. Keep it
  that way; never hardcode 250 in the template.
- Reviewer scrutiny: confirm no shape-comps twin that is genuinely unresolvable
  for a NON-recency reason gets mislabeled "too recent to grade" (the chip must
  guard on `twin.season > resolved_through`, not merely on `not twin.outcome`).
