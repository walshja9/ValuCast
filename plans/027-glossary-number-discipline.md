# Plan 027: Glossary + Number-Resolution Discipline — a committed term glossary (`/glossary`), a build-time "every metric label resolves to a glossary entry" CI check, glossary-anchored tooltips on the card/trade/board surfaces, a dated methodology changelog, and a named display principle — the *enforced* version of eephus.io's convention-only glossary

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> ```
> git log -1 --format=%h    # baseline for this plan is 8676b2b0
> git diff --stat 8676b2b0..HEAD -- app.py templates/methodology.html templates/base.html templates/partials/_board_nav.html templates/partials/_footer_provenance.html templates/partials/player_detail_dynasty.html templates/trade.html templates/partials/_trade_result.html web/prospect_percentiles.py web/pitch_discipline_store.py web/category_registry.py scripts/run_daily_public_build.py
> git status --short
> ```
> This plan was written against `8676b2b0`. All "Current state" line refs are
> accurate to that commit. **This repo auto-checkpoints frequently** (commits
> titled `checkpoint <ts> (stop)`); line numbers drift even when the code does
> not. If any in-scope file changed since, re-read the cited excerpt against the
> live code before proceeding; on a mismatch with an excerpt, treat it as a STOP
> condition. In particular: the `/methodology` route + its inline artifact loads
> (`methodology()`, app.py:~4706-4762), the fail-soft page-route model
> (`front_office_report`, app.py:~4765-4772), the `_load_artifact` loader
> (app.py:~4778-4793), the primary nav (`base.html:31-37`), the board-tab macro
> (`_board_nav.html:3-20`), the four footer link rows
> (`_footer_provenance.html:22,25-49`), the three python label dicts
> (`prospect_percentiles.METRIC_LABELS` line ~34, `pitch_discipline_store._DEFAULT_LABELS`
> lines ~35-39, `web/category_registry.py`), and the card `(?)`-tooltip precedent
> (`player_detail_dynasty.html:41`) are the load-bearing reuse surfaces — re-verify
> them at HEAD.
>
> **This is a NEW-FEATURE / trust-surface plan.** It adds one hand-authored
> committed glossary JSON, one build-time validator (the CI check), one fail-soft
> route + template (or a methodology section — Step 1 decides), a dated changelog,
> a named display principle, and a small tooltip pattern. Nothing here is
> frozen-file-blocked. Master auto-deploys valucast.app via Render, so do NOT
> push; the reviewer gates the push.

## Status

- **Priority**: P2 (competitive-gap / trust-surface depth, not a correctness or
  honesty leak in the existing product). eephus.io ships a 266-term structured
  glossary and *states* "every number resolves to a glossary entry" — but that
  claim is enforced only by convention (they have no CI). ValuCast already writes
  numbers honestly (the `est.` tag, the `&mdash;`-not-fabricated dash, the
  sub-floor no-bar); this plan **indexes** that vocabulary into one glossary and
  adds the one thing eephus does not have — a *machine-enforced* "every label
  resolves" gate. The enforcement is the differentiator, not the term list.
- **Effort**: **M**. One hand-authored JSON (20-40 seed terms, each with a real
  worked example traced to a committed artifact), one label-registry validator in
  the `scripts/validate_*.py` family, one fail-soft route + template (or a
  methodology `<section>`), a dated changelog block, a named principle line, and a
  server-rendered tooltip on the major surfaces. No new model, no network, no
  pipeline math. The **cut-to-S lever is the tooltips (component 3)**: the
  glossary page + the CI check + the changelog + the principle stand entirely on
  their own; ship those and file the glossary-anchored tooltips as a fast-follow.
  See "Scope" for the explicit cut line. Do NOT cut the CI check — an enforced
  "every-number-resolves" gate is the whole competitive point (a glossary without
  it is just eephus's convention, which we already beat by having honest numbers).
- **Risk**: MEDIUM. The sharp edges are all *honesty*, not mechanics: (a) **worked
  examples must be real** — every glossary example cites numbers pulled from a
  committed artifact at authoring time, with an `as_of` date, never invented (a
  fabricated example is exactly the dishonesty the display-principle forbids —
  STOP condition); (b) **the CI check must fail hard, never warn-only** — a
  watered-down warn-only check is the eephus convention we are trying to beat
  (STOP condition); (c) **no per-source third-party ranks** — glossary entries
  that describe consensus MUST say "aggregate median + board count" only, never a
  named board's rank (outside boards' ToS, plan 020/072e68864 precedent); (d) the
  **display principle must be TRUE the day it ships** — it is verified against the
  live surfaces (`est.` tags, sub-floor no-bar, `&mdash;` dashes), not aspirational
  copy.
- **Depends on**: none in flight. **Composes with plan 024 (Model Verdicts
  registry, AUTHORED not yet shipped)** — the glossary NEVER duplicates the
  verdict registry's job. A glossary term that touches model status (e.g. an AOTC
  verdict-state term) *describes what the term means* and cross-links `/models`
  **if and only if** that route exists at execution time; it never restates a
  verdict or a failure number. The two surfaces are orthogonal: `/glossary`
  defines vocabulary; `/models` judges models. See "Scope → Composition with 024".
- **Category**: feature (product — new trust/vocabulary surface + a CI honesty gate).
- **Planned at**: commit `8676b2b0`, 2026-07-11.
- **Execution window**: **post-7/13.** No frozen-file dependency in the edit set,
  but do not start before the 7/13 ledger-week unlock (repo-wide batch-3
  convention). It reads committed artifacts as *example sources* only; it never
  writes or re-scores any of them.

## Why this matters

Competitive origin: eephus.io's glossary is their most-cited trust surface — 266
structured terms, and a stated design rule that "every number on the site resolves
to a glossary entry." But that rule is enforced **only by convention**: a human
promises it, nothing checks it, and a new number can ship un-glossaried silently.

ValuCast's grammar is *machine-enforced honesty* (the daily `validate_*` gates, the
drift-locked methodology page, the AOTC pre-registration). So the ValuCast version
of a glossary is not "266 terms" — it is **20-40 terms plus a CI check that fails
the build when a metric label on a major surface has no glossary entry.** That is
the thing eephus does not have and, structurally, cannot easily add. The term count
is table stakes; the enforcement is the moat.

Four properties make this a *ValuCast* glossary, not a generic one, and each is a
hard edge baked into the plan:

1. **Every worked example is real and traceable.** Each entry's example pulls
   numbers from a committed artifact (a specific player's card values, a real AOTC
   ledger row, a real receipts lead time) at authoring time, and records an
   `as_of` date so the example ages honestly. An example whose numbers cannot be
   traced to a committed artifact is a STOP condition — it is precisely the
   fabrication the display principle (component 5) forbids.
2. **Every number resolves — and CI proves it.** The label-registry validator
   (component 2) enumerates the metric labels each major surface renders and
   asserts each resolves to a glossary `id` or an *explicitly documented*
   exemption. A new un-glossaried label forces either a glossary entry or a
   visible exemption — never a silent pass. It fails the build; it never warns.
3. **The site's own honesty is the seed vocabulary.** The seed terms are the
   *actual* strings the site renders (verified against the templates, Step 1's
   inventory), including the ones the site coined: the `est.` exact-vs-estimated
   split, the `&mdash;`-not-fabricated dash, "Ahead of the Curve," the value band
   (±9), the sub-floor no-bar. The glossary documents what already ships.
4. **Attribution is a first-class field.** Each entry declares `origin` —
   "original to ValuCast" vs "adopted from <public stat>" — so a reader can see
   which vocabulary ValuCast invented (Dynasty Value scale, Ahead of the Curve,
   the value band) and which it adopted from public sabermetrics (Swing%, Whiff%,
   K-BB%). eephus does not attribute; ValuCast does.

The display principle (component 5) is the honesty spine, and **it already exists
in prose** on the methodology page — `methodology.html:387-391` says "We would
rather leave a box empty than fabricate a number." This plan *names* it, elevates
it to the top of the methodology page (and the glossary), and *verifies it is true*
against the live surfaces so the principle is not marketing.

## Current state

Verified against the live files at `8676b2b0`. Read each cited line yourself before
building on it. Line numbers drift under this repo's frequent checkpoint commits —
re-verify.

### The fail-soft page-route + artifact-loader precedents already exist

- **`front_office_report()` (app.py:~4765-4772)** is the canonical three-statement
  fail-soft page route: build a `Path` to a `data/…/*.json`,
  `json.loads(...read_text())` inside `try/except (OSError, json.JSONDecodeError)`
  degrading to `None`, then `render_template(...)`. **A `/glossary` route is this
  exact shape** — a missing/corrupt glossary must render an "unavailable" state,
  never 500 (the 7/2 lesson: `/methodology` was the one route that could 500 on a
  bad refresh; every sibling degrades).
- **`_load_artifact(path: Path) -> dict | None` (app.py:~4778-4793)** is the
  mtime-stamped, cached, fail-soft JSON loader (`_ARTIFACT_CACHE` at ~4775). The
  board pages use it (`/gaps`, `/intelligence`). **Use it for the glossary route**
  — do NOT add a new caching mechanism.
- **The `/methodology` route (app.py:~4706-4762)** already reads *committed
  copy-data artifacts* fail-soft: `data/validation/methodology_scorecard.json`
  (~4716-4722), `data/validation/sensitivity_scorecard.json` (~4723-4729), and
  `data/models/valucast_mlb_projection_source_comparison.json` (the forward-gate,
  ~4730-4736), each in its own `try/except (OSError, ValueError)`. It inlines its
  own loads (predates `_load_artifact`). **This matters for the placement
  decision** (Step 1): the methodology route already loads committed JSON and
  passes it to the template, so a glossary rendered *as a `#glossary` section of
  `/methodology`* is a one-artifact extension of an existing pattern; a standalone
  `/glossary` route is the `front_office_report` shape. Both fit — Step 1 decides
  and justifies.

### Where hand-authored committed site-copy JSON lives (there is NO `data/site/`)

- **`data/site/` does not exist.** The two live homes for hand-authored committed
  JSON are:
  - **`data/manual/*.json`** — the hand-maintained seed/override home:
    `call_up_receipts_seed.json`, `prospect_availability_overrides.json`,
    `prospect_graduation_overrides.json` (all git-tracked). This is the truest
    "hand-authored editorial source" convention — the glossary is the same kind of
    file (a human writes it; a validator keeps it honest).
  - **`data/models/valucast_*.json`** — mostly daily-build outputs, but plan 024's
    (AUTHORED) registry is slated to live here as a hand-authored exception.
  - **Decision (Step 1): put the glossary at `data/manual/valucast_glossary.json`**
    — it matches the `call_up_receipts_seed.json` "hand-authored source" convention
    exactly, and keeps it visibly distinct from the build-output `data/models/`
    pile. (If Step 1's placement puts the render on `/methodology`, the file home
    is unchanged — the route just reads it from `data/manual/`.) **A hand-authored
    source file is staged like any source file; it is NOT added to the
    `daily-public-data.yml` `git add` block** (it is not a daily-build output).
- **`.gitignore` posture**: committed by default under `data/` except
  `data/projections/raw/*.json`, `data/prospects/raw/milb_season_stats_*.json`, and
  `data/prospects/raw/pitch_discipline_pitch_cache.json` (~350MB — never sweep it
  in). `data/manual/*.json` is committed. `data/dd/*` is DD-only — **do NOT read
  it** (ValuCast is DD-independent).

### The metric labels the site renders come from THREE places (the CI-check linchpin)

The "every number resolves" check must cover labels from all three sources —
hardcoded template strings AND python-built dicts. Verified inventory:

- **Python label dicts** (enumerate these programmatically in the validator):
  - `web/prospect_percentiles.py:METRIC_LABELS` (~line 34): `avg→"AVG"`, `obp→"OBP"`,
    `slg→"SLG"`, `ops→"OPS"`, `iso→"ISO"`, `k_pct→"K%"`, `bb_pct→"BB%"`,
    `era→"ERA"`, `whip→"WHIP"`, `k_per_9→"K/9"`, `bb_per_9→"BB/9"`, `k_bb_pct→"K-BB%"`.
    Fed to the card `profile_bars` (rendered `player_detail_dynasty.html:101-113`).
  - `web/pitch_discipline_store.py:_DEFAULT_LABELS` (~lines 35-39): `swing_pct→"Swing%"`,
    `whiff_pct→"Whiff%"`, `swstr_pct→"SwStr%"`, `chase_pct→"Chase%"`,
    `z_swing_pct→"Z-Swing%"`, `z_contact_pct→"Z-Contact%"`, `zone_pct→"Zone%"`.
    `_EXACT_ORDER` = the three measured metrics (no `est.`); `_ESTIMATED_ORDER` = the
    four zone metrics (tagged `est.`). This is the exact-vs-estimated split.
  - `web/category_registry.py` — the fantasy category labels (R/HR/RBI/SB/OPS/etc.)
    rendered in the Category Breakdown table (`player_detail_dynasty.html:696-707`).
- **Hardcoded template strings** — the card partial alone renders ~60 distinct
  user-facing labels: `"Dynasty Value"` (:41), `"ValuCast Rank"` (:501/511),
  `"Public Consensus"` (:526/538), `"Ahead of the Curve +N"` (:533/542),
  `"1 board (not a consensus)"` (:548), the board column headers
  (`rankings_table_dynasty.html:49-65`: `P#`, `Dynasty Value`, `Category Fit`,
  `Confidence`, …), the trade verdict strings, the receipts/movers/gaps/ledger
  labels. **These are NOT in a dict** — the validator handles them via a *curated
  label registry* (a fixture list in the test, per component 2's design), NOT by
  DOM-scanning the rendered HTML (brittle).

### The real vocabulary (seed inventory — verified strings, NEVER invent)

The seed terms are the *actual* strings the site renders. Verified corrections to
guard against inventing vocabulary:

- **Dynasty Value** — the 0-100 headline (`player_detail_dynasty.html:41`, with a
  `(?)` link to `/methodology#dynasty-value-scale`). Origin: original to ValuCast.
- **Exact metrics** (Swing%, Whiff%, SwStr%) vs **estimated zone metrics** (Chase%,
  Z-Swing%, Z-Contact%, Zone%) — the `est.`-tagged split
  (`pitch_discipline_store.py`). Origin: adopted from public plate-discipline stats.
- **Percentile / percentile chips** — "top N%" / "bottom N%" (`_statcast_bars.html`),
  "vs same-level cohort," "100 = best in the ValuCast prospect pool." Origin: adopted.
- **Public Consensus** — "~P#N" median + "N boards" board count
  (`player_detail_dynasty.html:526-528/538-540`). **Aggregate median + board count
  ONLY** — never a named board's rank (ToS). Origin: original framing.
- **Ahead of the Curve (AOTC)** — the site's coined divergence-call brand; the chip
  "Ahead of the Curve +N" (`:533/542`), the `/ledger` track record. Origin:
  original to ValuCast. **Its verdict states are a 7-state machine, not a 4-way
  win/loss/open** — `track_record.html:111-119`: `open_toward`→"Field moving to us",
  `closed_caught_up`→"Caught up — win", `open_away`→"Field moving away",
  `retired_we_backed_off`→"We backed off", `open_flat`→"No decisive move",
  `resolved_called_up_or_graduated`→"Called up / graduated", `left_universe`→"Left
  universe", surfaced as 4 filter kinds (Wins/Losses/Retreats/Undecided/Resolved).
  A glossary "AOTC verdict states" entry describes these; it does NOT restate a
  lift number and it cross-links `/models` only if that route exists.
- **Receipts lead time** — the field is `flagged_days_early`, rendered
  "· flagged Nd early" (`receipts.html:67,69,93,95`). "Lead time" is the concept;
  the string is "flagged Nd early." Origin: original.
- **Movers score delta** — a bare signed number `.mover-delta`
  (`movers.html:70,90`) with a disclosed threshold ("moves under ±N score don't
  qualify," `:30`); window pills 7d/14d/30d (`:36-41`). Origin: original.
- **Value band (noise band)** — the trade honesty note: "within the value band
  (about ±9 per player)… a coin-flip on these numbers" (`_trade_result.html:56`;
  `_TRADE_NOISE_PER_PLAYER = 9.0`, app.py:~6836). **The user-facing string is
  "value band," not "noise band"** (noise band is the internal name). Origin:
  original. The three trade verdicts are exactly: "Inside the noise band - call it
  even" / "You come out ahead" / "You give up more than you get" — **there is no
  "FAIR"/"LOPSIDED" vocabulary anywhere** (0 repo hits).
- **Forward-gate** — the methodology-only "currently losing" live check
  (`methodology.html:351-358`). Origin: original. Describes the concept; links the
  live artifact, never restates the ratio.
- **Confidence** — "High/Medium/Low confidence" chip
  (`rankings_table_dynasty.html:62`, `player_detail_dynasty.html:53/466`). Origin:
  original framing.
- **~~GM-free~~** — **does NOT exist in the repo** (0 hits). Do NOT seed it. The
  closest real ValuCast-original taglines are "free, no login" and "Deterministic ·
  committed daily · publicly scored" (`_board_nav.html:23`, `cards.html:18`). If a
  "no-GM / free" concept is wanted, seed it from those *real* strings and mark
  origin "original to ValuCast," not from the non-existent "GM-free."

### The methodology page structure + where the principle + changelog attach

- **`templates/methodology.html`** is one `<article class="methodology">` of flat
  `<section> > <h3>` blocks (some with inner `<details>` for progressive
  disclosure). Anchored sections declare the `id` **mixed** — 2 on `<section>`
  (`dynasty-value-scale` :52, `plate-discipline` :364) and 2 on `<h3>` (`aotc-rules`
  :270, `sensitivity` :302). (Plan 024's prose says "3 of 4 favor section-level" —
  that is slightly off vs the live file; use the majority `<section>`-level pattern
  but do not cite 024's ratio.)
- **The display principle already exists in prose**: `methodology.html:387-391`
  ("Why there is no exit velocity…"): *"…ValuCast does not show — and will not
  estimate — … We would rather leave a box empty than fabricate a number."* The
  sample-floor principle is at `:392-398` ("a bucket must clear a minimum
  pitches-seen sample before any bar renders — below that floor we show no
  percentile at all"). Component 5 **names and elevates** these existing lines,
  it does not invent a new claim.
- **The honest-failure voice** to match is the forward-gate block
  (`methodology.html:343-362`): state the number → state the limitation → "We
  publish it here rather than wait for it to look better."
- **There is NO changelog / dated-history section today.** The only dated markers
  are the version line (:10) and the AOTC "(pre-registered 2026-07-02)" in its `<h3>`
  (:270). Component 4 adds the first append-only dated changelog.

### The placement surfaces (nav / footer / board tabs)

- **Primary nav** (`base.html:31-37`) is a deliberate 5-link bar (Board,
  Backfields, Map, Intelligence Hub, Methodology). **`/glossary` does NOT go here**
  (matches plan 024's convention — trust sub-pages live elsewhere).
- **Board-tab macro** (`_board_nav.html:3-20`, `.horizon-tabs`): Redraft, Dynasty,
  Prospects, Backfields, Map, Movers, Gaps, Receipts, Buys, Trade, Ledger, Cards.
  A "Glossary" tab here (adjacent to Methodology-adjacent trust surfaces) is the
  primary discoverability placement IF the render is a standalone page. Non-DD
  content — no `dd_available` gate needed.
- **Footer** (`_footer_provenance.html`) carries the trust-surface links in **four
  near-duplicate rows** (:22 methodology/scouting/intelligence branch; :25-31,
  :33-40, :42-49 the board/source branches). Add the glossary link to **every** row
  or it is missing on half the site.
- **Existing tooltip precedent** (the tooltips component builds on this):
  `title="…"` attributes are the *only* definition-on-hover mechanism site-wide (34
  uses, no JS tooltip component, no `<abbr>`, no `data-tooltip`). The cleanest
  precedent is the card `(?)` pattern (`player_detail_dynasty.html:41`): a small
  `<a>` linking `/methodology#anchor` with a `title=` explainer — and the `est.`
  tag (`:164`) is literally already this: `<a class="pd-est-tag"
  href="/methodology#plate-discipline" title="…">est.</a>`. **The glossary-anchored
  tooltip is this exact pattern pointed at `/glossary#<term-id>`** — server-rendered,
  zero-JS, progressive-enhancement-native. The one inline-`<script>`-IIFE JS-island
  pattern (`trade.html:65-187`, `{{ var | tojson }}` + `data-*` + event delegation +
  graceful `.catch()`) is available if a richer popover is ever wanted, but V1 does
  NOT need JS.

### The `scripts/validate_*.py` family (the CI-check idiom)

- There are ~20+ `scripts/validate_*.py` scripts (thin CLI, exit-code gate:
  `validate_ahead_of_consensus.py`, `validate_pitch_discipline.py`,
  `validate_feed.py`, …). The label-registry validator (component 2) is one more in
  this family, wired into `scripts/run_daily_public_build.py:VALIDATE_STEPS`. The
  daily build has a `validate_steps()` duplicate-guard — do not add a step twice.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Glossary schema + example-provenance validator | `python scripts/validate_glossary.py` | prints OK, exit 0; nonzero if a term is malformed or an example lacks a traceable `as_of`/source |
| Every-label-resolves CI check | `python scripts/validate_label_glossary_coverage.py` | prints OK + coverage summary, exit 0; nonzero + names the unresolved label(s) on failure |
| Validator + coverage unit tests | `python -m pytest -q tests/test_glossary.py` | all pass |
| App/route render tests | `python -m pytest -q tests/test_app.py -k "glossary"` | all pass |
| Page renders (if standalone route) | `python -c "import app; c=app.app.test_client(); r=c.get('/glossary'); print(r.status_code, b'Glossary' in r.data)"` | `200 True` (or the methodology-section check if that placement chosen) |
| Every example source path exists (smoke) | `python -c "import json,os; d=json.load(open('data/manual/valucast_glossary.json')); miss=[t['id'] for t in d['terms'] if t.get('example',{}).get('source') and not os.path.exists(t['example']['source'])]; print('MISSING SOURCES:', miss)"` | `MISSING SOURCES: []` |
| Python label dicts are importable (validator input) | `python -c "from web.prospect_percentiles import METRIC_LABELS; from web.pitch_discipline_store import _DEFAULT_LABELS; print(len(METRIC_LABELS), len(_DEFAULT_LABELS))"` | two integers |
| No per-source ranks in glossary (ToS lock) | `python -c "import json; s=json.dumps(json.load(open('data/manual/valucast_glossary.json'))).lower(); bad=[k for k in ('fangraphs #','cfr #','hkb #','pipeline #','the board rank') if k in s]; print('BAD:', bad)"` | `BAD: []` |
| Display principle is true (est. tag live) | `python -c "import app; c=app.app.test_client(); h=c.get('/methodology').data.decode(); print('est.' in h.lower() and 'fabricate' in h.lower())"` | `True` |
| Full suite (final gate) | `python -m pytest -q` | ~1871+ pass, 0 fail; then restore the byproduct (below) |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | file back to HEAD (pytest dirties it — NEVER commit it) |

## Scope

**In scope** (the only files you create or modify):

- **NEW `data/manual/valucast_glossary.json`** — the hand-authored glossary
  (Step 1). One top-level object: `{"schema_version", "generated_at" (hand-edit
  date), "principle" (the named display principle string), "changelog":[…],
  "terms":[…]}`. Each term:
  `{"id" (slug, stable — tooltip anchors point at it), "term" (display name),
  "definition" (plain language), "formula" (one line, OPTIONAL), "example"
  ({"text", "source" (a committed artifact path under data/), "as_of" (ISO date
  the example numbers were pulled)} — OPTIONAL but if present MUST be traceable),
  "origin" ("original to ValuCast" | "adopted from <public stat>"), "see_also"
  ([term ids])}`. 20-40 terms (Step 1's inventory).
- **NEW `scripts/validate_glossary.py`** — schema + provenance validator (the
  `validate_*.py` family). Asserts: (1) the file parses; (2) every term has
  `id`/`term`/`definition`/`origin`; (3) every `id` is unique and slug-shaped;
  (4) every `see_also` id resolves to a real term; (5) **every `example.source`
  path exists on disk AND the example carries an `as_of`** (the traceability lock —
  no example with a source pointing nowhere, no dated example without a date);
  (6) **no per-source third-party rank strings** appear anywhere (ToS lock — the
  smoke command's denylist, plus "not used in ValuCast score"-style framing for any
  consensus term). Prints a one-line OK summary.
- **NEW `scripts/validate_label_glossary_coverage.py`** — **the every-number-resolves
  CI check.** It builds the set of metric labels rendered on the *major surfaces*
  from (a) the importable python dicts (`prospect_percentiles.METRIC_LABELS`,
  `pitch_discipline_store._DEFAULT_LABELS`, the category registry) and (b) a
  **curated `MAJOR_SURFACE_LABELS` registry** hardcoded in the validator (the
  hardcoded template strings — "Dynasty Value", "ValuCast Rank", "Public Consensus",
  "Ahead of the Curve", the board column headers, the trade verdict vocabulary,
  etc.). For each label it asserts the label resolves to a glossary term (by an
  explicit `label→term-id` map the glossary carries, OR by matching a term's
  `term`/aliases). An unresolved label **fails nonzero and names it**, UNLESS the
  label is in the validator's visible `EXEMPTIONS` set (each exemption carries a
  one-line reason comment). **This is fail-hard, never warn-only.** Coverage
  **starts at the major surfaces (player card, trade page, boards) and ratchets** —
  the registry is honest that it is not yet exhaustive (a `COVERAGE_SCOPE` note
  lists which surfaces are enforced).
- **`app.py`** — EITHER (Step 1 decision) a new `@app.route("/glossary")` →
  `glossary()` modeled on `front_office_report()` (`_load_artifact` the glossary,
  fail-soft, render `glossary.html`), OR extend the existing `methodology()` route
  to load the glossary artifact and pass it to a `#glossary` section. Add a
  `GLOSSARY_PATH` constant near the other `data/…` path constants. No
  cache/scoring/PNG region touched.
- **NEW `templates/glossary.html`** (if standalone) — `{% extends "base.html" %}`,
  the board-tab macro (`active='glossary'`), a hero, the named principle at the top,
  a searchable/anchored term list (each term an `id="<term-id>"` target so tooltips
  deep-link), an origin badge per term, and the worked example with its `as_of`.
  Fail-soft `{% if not terms %}` unavailable state. (If the methodology-section
  placement is chosen, this content becomes a `<section id="glossary">` in
  `methodology.html` instead — Step 1 decides.)
- **`templates/methodology.html`** — (i) **name + elevate the display principle**
  (component 5): a short principled line at the top of the article (near :10-14),
  e.g. *"When data is absent we show a dash, never a fabricated estimate; when a
  number is an estimate we label it."* — cross-referencing the existing :387-391 and
  :392-398 copy so the principle and its proof sit together. (ii) **the dated
  changelog** (component 4): a new `<section id="methodology-changelog">` (or render
  the glossary's `changelog` array) — an append-only dated list. (iii) a
  cross-link section/line to `/glossary` (mutual, per the ledger↔methodology
  precedent).
- **Card / trade / board templates — glossary-anchored tooltips (component 3, the
  cut-to-S lever)**: on the major metric labels, wrap the label (or add the `(?)`
  companion) in an `<a href="/glossary#<term-id>" title="<one-line definition>">…</a>`
  — the **exact `est.`/`(?)` pattern already in `player_detail_dynasty.html:41,164`**,
  pointed at `/glossary`. Touch only: `player_detail_dynasty.html` (Dynasty Value,
  the plate-discipline labels, ValuCast Rank, Public Consensus), `trade.html` /
  `_trade_result.html` (the value band note, the verdict), and the board column
  headers (`rankings_table_dynasty.html`). Server-rendered, zero-JS.
- **NEW `templates/partials/_board_nav.html`** edit (if standalone route) — add a
  `<a href="/glossary" class="htab{% if active == 'glossary' %} on{% endif %}"…>Glossary</a>`
  tab (no gating flag).
- **`templates/partials/_footer_provenance.html`** — add
  `- <a href="/glossary">Glossary</a>` to **every** link row (:22 and :25-49).
- **`scripts/run_daily_public_build.py`** — add BOTH validators to `VALIDATE_STEPS`
  (`("scripts/validate_glossary.py",)` and
  `("scripts/validate_label_glossary_coverage.py",)`), respecting the
  `validate_steps()` duplicate-guard. Do NOT add a `BUILD_STEPS` entry — the
  glossary is hand-maintained, not computed. The glossary JSON is NOT added to the
  `daily-public-data.yml` `git add` block (hand-authored source, staged like code).
- **NEW tests**: `tests/test_glossary.py` (validator logic on fixtures:
  missing-example-source fails, example-without-`as_of` fails, per-source-rank
  string fails, unresolved-label fails, an EXEMPTED label passes, a `see_also`
  dangling id fails) + additions to `tests/test_app.py` (route/section renders
  200 + contains the principle + a fail-soft empty case + a tooltip anchor
  resolves to a real term id).

### Composition with plan 024 (Model Verdicts registry) — do NOT duplicate

- **024 is AUTHORED, not shipped** (no `data/models/valucast_model_registry.json`,
  no `templates/models.html`, no `/models` route at HEAD — verified). So at
  execution time `/models` MAY OR MAY NOT exist.
- **The glossary defines vocabulary; the registry judges models.** They never
  overlap: a glossary "Ahead of the Curve" term explains *what a divergence call
  is*; the registry's AOTC row says *whether the AOTC model is validated*. A
  glossary "forward-gate" term explains *what the gate measures*; the registry's
  MLB-projection row says *it is currently losing*.
- **Cross-link conditionally, never restate.** Where a glossary term names a model
  status concept, link `/models` **only if that route exists at execution time**
  (guard the link: `{% if models_page_available %}` or a simple route-exists check).
  A glossary term must NEVER restate a verdict label or a failure number — that is
  the registry's job and MEMORY's numbers (1.21×/1.44×) are already stale. If
  `/models` does not exist yet, omit the cross-link (the glossary term stands
  alone); do not block on 024.

**Cut line to hold Effort (the reviewer decides at planning time):**

- **CORE (must ship): the glossary JSON + the schema/provenance validator + the
  every-label-resolves CI check + the `/glossary` render (page or section) + the
  named display principle + the dated changelog.** This is the product: an
  *enforced* "every number resolves" glossary with real, traceable examples and a
  named honesty principle. **The every-label-resolves CI check is NON-cuttable and
  MUST be fail-hard** — a warn-only check is the eephus convention we exist to
  beat.
- **CUT-CANDIDATE: the glossary-anchored tooltips (component 3).** If the day runs
  long, ship the glossary page + the CI check + the changelog + the principle, and
  file the tooltips as a fast-follow. The glossary is fully useful without them
  (it is a page a reader can open); the tooltips are the convenience layer.
- **Secondary cut (only if still over): the board-tab entry.** Ship the footer +
  the methodology cross-link for discoverability first; add the `_board_nav.html`
  "Glossary" tab as a fast-follow. The page is reachable and linked either way.

**Out of scope** (do NOT touch):

- **Any model math / valuation / scoring.** The glossary is *display/copy only* —
  it reads artifacts as *example sources* and prints definitions. It NEVER changes
  a value, a rank, a projection, or a gate. Do not edit any `prospects/*.py`,
  `projections/*.py`, `web/valuation*`, and do NOT modify the *values* in the label
  dicts (`METRIC_LABELS`, `_DEFAULT_LABELS`, `category_registry`) — read them,
  never rewrite them.
- **The Model Verdicts registry (plan 024).** Do not build it, restate its
  verdicts, or hardcode any failure number. Cross-link `/models` only if it exists
  (above). The glossary is a *separate, orthogonal* surface.
- **Per-source third-party board ranks anywhere.** Any consensus term describes
  **aggregate median + board count ONLY** — never a named board's rank
  (plan 020 / 72e68864 ToS precedent). This is a STOP condition.
- **The frozen AOTC scoring files** — `prospects/ahead_of_consensus.py`,
  `scripts/build_ahead_of_consensus_scorecard.py` (pre-registered scoring, ~7/13
  unlock). The glossary may *cite the committed scorecard artifact as an example
  source* (read-only); it does NOT re-score or touch those files.
- **Any PNG / share card / `_PNG_CACHE_PARAMS`.** V1 is HTML + copy only — no new
  graphic, and **no tooltip may add a query param to any share-card PNG** (that
  would touch `_PNG_CACHE_PARAMS`, app.py:~154 — out of scope, STOP condition). The
  tooltips are `<a title=…>` on the HTML page only; they never change a PNG URL.
- **DD (`dd_*`) feeds.** ValuCast is DD-independent. The glossary cites only
  ValuCast-owned artifacts as example sources. Do NOT read `data/dd/*`.
- **DOM-scanning the rendered HTML for the coverage check.** Full DOM-scan is
  brittle and explicitly rejected — the coverage check uses the curated
  label-registry + importable dicts approach (component 2). Do not build an
  HTML-parsing crawler.
- **Watering the CI check down to warn-only.** STOP condition. It fails the build.

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT
  push**: master auto-deploys valucast.app via Render. Commit locally; the
  reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — untracked `data/dd/*`,
  raw caches, and pytest byproducts must not be swept in). Stage each in-scope
  file explicitly by path. **Never `git stash`.**
- Do NOT stage `data/prediction_archive/.../2026-06-15.json` (pytest byproduct),
  any untracked `data/dd/*`, or any `data/prospects/raw/*` cache.
- The glossary JSON is a **hand-authored committed source file** (like
  `data/manual/call_up_receipts_seed.json`) — staged like source; it is NOT added
  to the `daily-public-data.yml` `git add` block.
- Commit message style (short imperative subject), e.g.
  `Add term glossary (/glossary) + every-number-resolves CI check + dated methodology changelog + named display principle`.

## Steps

### Step 0: Confirm the reuse surfaces are live and nothing exists yet

```
# Fail-soft page-route + loader present:
python -c "import app; print(hasattr(app,'_load_artifact'))"
# expect: True
# The three label sources are importable:
python -c "from web.prospect_percentiles import METRIC_LABELS; from web.pitch_discipline_store import _DEFAULT_LABELS; import web.category_registry; print(len(METRIC_LABELS), len(_DEFAULT_LABELS))"
# expect: two integers (>=12 and 7)
# The display principle already exists in prose (component 5 elevates it, not invents):
python -c "print(open('templates/methodology.html',encoding='utf-8').read().count('fabricate'))"
# expect: >=1
# There is NO glossary artifact/route/template yet:
python -c "import os; print(os.path.exists('data/manual/valucast_glossary.json'), os.path.exists('templates/glossary.html'))"
# expect: False False
python -c "import app; print(any(str(r)=='/glossary' for r in app.app.url_map.iter_rules()))"
# expect: False
# The daily validate list exists:
python -c "import scripts.run_daily_public_build as r; print(len(r.VALIDATE_STEPS))"
# expect: an integer
```
**Verify**: all confirm the state above. If a glossary artifact/route/template
already exists, someone landed here first — STOP and reconcile.

### Step 1: Decide the render surface + author `data/manual/valucast_glossary.json`

**Decision A — render surface (justify in the commit).** Two honest options:
- **Standalone `/glossary` route + `glossary.html`** (modeled on
  `front_office_report`) — best if the glossary is 20-40 terms and wants its own
  searchable, deep-linkable page (tooltips point at `/glossary#<id>`). **Recommended
  default**: a glossary is a reference surface people link to; a page with stable
  `#id` anchors is the natural home, and it composes cleanly with a board-tab entry.
- **`#glossary` section of `/methodology`** — best if the term count stays small
  (<~15) and the reviewer prefers one consolidated "how it works" page. The
  methodology route already loads committed JSON (:4716-4736), so this is a
  one-artifact extension.
- **Pick one, state why.** Either way the file home is `data/manual/valucast_glossary.json`
  and the principle + changelog live on `/methodology`. If unsure, ship the
  standalone page (stable anchors for tooltips are the deciding factor).

**Decision B — the glossary is HAND-MAINTAINED, machine-validated.** Same posture
as plan 024's registry and the AOTC pre-registration: a human writes the
definitions and picks the real examples; the validators (Step 2) keep it honest
(schema, traceable examples, no per-source ranks, every label resolves). Do NOT
auto-generate definitions.

**Author the terms.** 20-40 core terms from the verified seed inventory (Current
state → "The real vocabulary"). For each: write `definition` in plain language,
`origin` (original vs adopted), an OPTIONAL `formula` one-liner, `see_also` links,
and — where it adds value — a **real worked example** pulled from a committed
artifact with an `as_of`. Minimum seed set (the coverage check enforces the major
surfaces have a term):

1. **Dynasty Value** — origin: original. Formula: the 0-100 scale. Example: a real
   player's current committed value from `data/public/public_dynasty_snapshot.json`
   with `as_of`. See_also: percentile, confidence.
2. **Swing% / Whiff% / SwStr%** (exact) — origin: adopted from public plate
   discipline. Formula each (swings/pitches, whiffs/swings, whiffs/pitches). Example:
   a real prospect's numbers from `data/models/valucast_pitch_discipline.json`.
3. **Chase% / Z-Swing% / Z-Contact% / Zone%** (estimated) — origin: adopted;
   definition MUST state these are `est.` (pixel-calibration), cross-ref the
   principle. Example from the same artifact's calibration metadata.
4. **Percentile / percentile chip** — origin: adopted. "vs same-level cohort; 100 =
   best in the ValuCast pool."
5. **Public Consensus (median + board count)** — origin: original framing.
   **Aggregate median + board count ONLY.** Definition states "not used in ValuCast
   score." Example: a real "~P#N across N boards" from a committed artifact.
6. **Ahead of the Curve (AOTC)** — origin: original. Definition explains the
   divergence-call concept; cross-links `/models` only if it exists; links `/ledger`.
7. **AOTC verdict states** — origin: original. Definition lists the real state→label
   map (the 7 states / 4 kinds). Example: a real `/ledger` row's status. Cross-links
   `/models` conditionally.
8. **Receipts lead time (flagged Nd early)** — origin: original. Example: a real
   receipts row's `flagged_days_early` from the committed receipts artifact.
9. **Movers score delta** — origin: original. Formula: the delta + the disclosed
   threshold. Example: a real mover's delta.
10. **Value band (±9)** — origin: original. Definition: the trade coin-flip band;
    the three verdict strings. Example: the ±9 constant.
11. **Forward-gate** — origin: original. Definition: the live Steamer forward check;
    links the artifact, **never restates the ratio**.
12. **Confidence (High/Medium/Low)** — origin: original framing.
13. **Est. / exact-vs-estimated** — origin: original honesty device. Definition ties
    directly to the display principle.
14. **The `&mdash;` dash / absent-vs-estimate** — origin: original honesty device.
    Definition IS the display principle in miniature.
15. **Free, no login / deterministic-committed-daily** (the real ValuCast-original
    taglines — use these, NOT the non-existent "GM-free").

Add the standard sabermetric rate terms already in `METRIC_LABELS` (AVG/OBP/SLG/OPS/
ISO/K%/BB%/ERA/WHIP/K/9/BB/9/K-BB%), each origin "adopted from public stats," to
reach the 20-40 range and satisfy the coverage check for the card `profile_bars`.

Also author the top-level `principle` string (component 5) and the `changelog`
array (component 4 — Step 4 pins the real dated entries).

**Verify**:
- `python scripts/validate_glossary.py` → OK (after Step 2 exists).
- `python -c "import json; d=json.load(open('data/manual/valucast_glossary.json')); print(len(d['terms']), sorted({t['origin'].split(' from ')[0] for t in d['terms']}))"` → a count 20-40 and the two origin families.
- Every `example.source` exists (the smoke command): `MISSING SOURCES: []`.

### Step 2: The two validators

**2a — `scripts/validate_glossary.py`** (schema + provenance, the `validate_*.py`
family): loads the glossary and fails nonzero with a named reason on: a term missing
`id`/`term`/`definition`/`origin`; a duplicate or non-slug `id`; a dangling
`see_also`; an `example.source` path that does not exist; an `example` with a source
but no `as_of`; **any per-source third-party rank string** (the denylist:
`fangraphs #`, `cfr #`, `hkb #`, `pipeline #`, `the board rank`, a named-board rank
pattern). Prints a one-line OK summary.

**2b — `scripts/validate_label_glossary_coverage.py`** (the every-number-resolves CI
check — fail-hard). Structure:
```python
"""Every metric label the major surfaces render must resolve to a glossary term,
or be an explicitly documented exemption. Fail-HARD (never warn) so a new
un-glossaried label forces a glossary entry or a visible exemption. Coverage starts
at the major surfaces and ratchets."""
import json, sys
from pathlib import Path
from web.prospect_percentiles import METRIC_LABELS
from web.pitch_discipline_store import _DEFAULT_LABELS

ROOT = Path(__file__).resolve().parent.parent
GLOSSARY = ROOT / "data" / "manual" / "valucast_glossary.json"

# Which surfaces this check enforces today (honest about the ratchet):
COVERAGE_SCOPE = ("player_card", "trade_page", "board_columns")

# Hardcoded template labels on the enforced surfaces (the strings NOT in a dict).
# Keep this list in sync when a major surface gains a label — that is the point.
MAJOR_SURFACE_LABELS = {
    "Dynasty Value", "ValuCast Rank", "Public Consensus", "Ahead of the Curve",
    "Category Fit", "Confidence", "Value band",  # ... (author the full curated set)
}

# Visible exemptions — each with a reason. A label here does NOT need a glossary
# term (e.g. pure UI chrome, not a metric). NOT silent — it lives in the check.
EXEMPTIONS = {
    "Player": "identity column, not a metric",
    "Pos": "position column, not a metric",
    # ...
}

def _glossary_labels(reg):
    """Every string a term resolves: its display `term`, plus any `aliases`,
    plus the values of an optional `label_map` the glossary carries."""
    hit = set()
    for t in reg.get("terms", []):
        hit.add(t["term"])
        hit.update(t.get("aliases", []))
    hit.update((reg.get("label_map") or {}).keys())
    return hit

def main() -> int:
    reg = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    resolved = _glossary_labels(reg)
    labels = set(METRIC_LABELS.values()) | set(_DEFAULT_LABELS.values()) | MAJOR_SURFACE_LABELS
    unresolved = sorted(l for l in labels if l not in resolved and l not in EXEMPTIONS)
    if unresolved:
        print("LABEL COVERAGE FAILED — no glossary term for:\n  " + "\n  ".join(unresolved))
        print("Add a glossary term (or a documented EXEMPTION) for each.")
        return 1
    print(f"OK: {len(labels)} labels across {COVERAGE_SCOPE} all resolve to a glossary term")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```
- The category-registry labels can be folded into `labels` too (import the registry
  and union its category labels) — do it if the registry exposes them cleanly; if
  not, add the fantasy category letters to `MAJOR_SURFACE_LABELS` or EXEMPTIONS with
  a reason. Be honest about scope in `COVERAGE_SCOPE`.
- **This must fail-hard.** No `--warn` flag, no exit-0-on-unresolved. That is the
  competitive point.

**Verify**:
- `python scripts/validate_glossary.py` → OK, exit 0.
- `python scripts/validate_label_glossary_coverage.py` → OK, exit 0.
- Temporarily add a fake label to `MAJOR_SURFACE_LABELS` in a scratch copy → the
  coverage check exits 1 and names it. Restore.
- Temporarily point one `example.source` at a bogus path → `validate_glossary.py`
  exits 1 and names the term. Restore.

### Step 3: The render surface (route + template OR methodology section)

**If standalone (recommended):** add `GLOSSARY_PATH` near the other `data/…` path
constants, then a `front_office_report`-shaped route:
```python
@app.route("/glossary")
def glossary():
    """Public term glossary: every metric ValuCast shows, defined in plain language
    with a real worked example and an origin attribution. The every-number-resolves
    gate (scripts/validate_label_glossary_coverage.py) keeps it complete. Fail-soft:
    a missing/corrupt glossary renders an unavailable state, never a 500."""
    reg = _load_artifact(GLOSSARY_PATH) or {}
    return render_template(
        "glossary.html", glossary_page=True,
        terms=reg.get("terms") or [],
        principle=reg.get("principle"),
        as_of=reg.get("generated_at"),
        models_page_available=any(str(r) == "/models" for r in app.url_map.iter_rules()),
    )
```
`templates/glossary.html`: `{% extends "base.html" %}`, the board-tab macro
(`active='glossary'`), a hero, **the named principle at the top**, the term list
(each `<div id="{{ term.id }}">` so tooltips deep-link; render `term`, `definition`,
optional `formula`, the worked `example` with `{{ example.as_of }}`, an origin badge,
`see_also` links). A cross-universe/consensus term renders "aggregate median + board
count" language only. `{% if not terms %}` unavailable notice. Cross-link `/models`
ONLY `{% if models_page_available %}`.

**If methodology-section:** extend `methodology()` to `_load_artifact` the glossary
and render a `<section id="glossary">` (mirror the `plate-discipline` `<section>`
grammar). Same content, same fail-soft.

**Verify**:
- `python -c "import jinja2; jinja2.Environment(loader=jinja2.FileSystemLoader('templates')).get_template('glossary.html')"` → no exception (standalone).
- `python -c "import app; c=app.app.test_client(); r=c.get('/glossary'); print(r.status_code)"` → `200` (standalone) — or the `#glossary in /methodology` render check.
- With the artifact temporarily unreadable → 200 unavailable state, never 500.

### Step 4: The named display principle + the dated changelog (methodology)

**4a — Principle (component 5).** In `methodology.html` near the topline (:10-14),
add a named principled line, e.g. an `<p class="methodology-principle">`:
*"Our display rule: when data is absent we show a dash, never a fabricated estimate;
when a number is an estimate we label it (est.)."* Then confirm it is TRUE by
cross-referencing the existing proof copy (:387-391 "leave a box empty than
fabricate," :392-398 sub-floor no-bar) — do NOT delete those; the principle names
what they already do. **Verify the claim against the live surfaces** (the `est.` tag
renders on the card, the `&mdash;` renders where data is absent, the sub-floor
renders no bar) so the principle is true the day it ships.

**4b — Changelog (component 4).** Add an append-only dated `<section
id="methodology-changelog">` (or render the glossary's `changelog` array). Seed it
with the **real, verified** recent history — dates pinned against git log at
authoring time (re-verify each against `plans/README.md` and `git log`):
- **2026-07-10 — Plate-discipline layer** (commits `adf7e9d9`/`543905b8`; plan 023):
  exact Swing/Whiff/SwStr + est. zone metrics on prospect cards.
- **2026-07-09 — Methodology honesty polish** (commit `0de09023`; plan 014): the
  forward-gate "currently losing" disclosure added.
- **2026-07-02 — AOTC scorecard v2 pre-registered** (commit `2a39d0cb`): exit-
  accounted, controlled, pre-registered targets.
- **2026-07-01 — SV/HLD split targets** (commit `d81ccca5`): saves and holds
  regressed separately, then summed.
- **DO NOT include ClaudeBot's max_tokens / exit fixes** — those are the *trading
  bot*, a different project, NOT ValuCast. (Explicit: they are not in this repo's
  history; including them would be fabrication.)

Each changelog entry: `{date, title, detail (one line)}`. Match the methodology
voice. Append-only — never rewrite a past entry.

**Verify**:
- `python -c "import app; c=app.app.test_client(); h=c.get('/methodology').data.decode(); print('methodology-principle' in h or 'display rule' in h.lower())"` → `True`.
- `python -c "import app; c=app.app.test_client(); h=c.get('/methodology').data.decode(); print('2026-07-10' in h and 'max_tokens' not in h)"` → `True` (real dates present; ClaudeBot content absent).

### Step 5: Glossary-anchored tooltips (component 3 — the cut-to-S lever)

On the major metric labels, extend the **exact `(?)`/`est.` precedent**
(`player_detail_dynasty.html:41,164`) — a small `<a href="/glossary#<term-id>"
title="<one-line definition>">` companion or wrapper. Server-rendered, zero-JS.
Touch only:
- `player_detail_dynasty.html`: Dynasty Value (:41 already has a `(?)` → repoint or
  add `/glossary#dynasty-value`), the plate-discipline labels (:162-176), ValuCast
  Rank (:501/511), Public Consensus (:526/538).
- `trade.html` / `_trade_result.html`: the value-band note (:56), the verdict.
- `rankings_table_dynasty.html`: the board column headers (:49-65).

Each tooltip `href` MUST point at a real glossary `id` (the coverage check + a test
enforce this). **No tooltip adds a query param to any share-card PNG** — these are
`<a title=…>` on the HTML page only; the PNG URLs are untouched (STOP condition if a
PNG param is added).

**Verify**:
- `python -c "import app; c=app.app.test_client(); h=c.get('/player/<a real prospect id>').data.decode(); print('/glossary#' in h)"` → `True`.
- A test asserts every `/glossary#<id>` anchor rendered on the card resolves to a
  term `id` in the glossary (no dangling tooltip).
- `git diff` shows NO change to any `*share-card*` PNG route or `_PNG_CACHE_PARAMS`.

### Step 6: Placement (nav / footer) + wire the validators into the daily build

**6a — Board tab** (if standalone): add a `Glossary` `.htab` in `_board_nav.html`
(no gating flag).
**6b — Footer**: add `- <a href="/glossary">Glossary</a>` to **every** link row in
`_footer_provenance.html` (:22 and :25-49).
**6c — Methodology cross-link**: the `#glossary` (or `/glossary`) link on
`/methodology`, mutual with the glossary→`/methodology` link.
**6d — Daily validate steps**: append BOTH validators to
`run_daily_public_build.py:VALIDATE_STEPS` (respect the duplicate-guard). No
`BUILD_STEPS` entry (hand-maintained). The glossary JSON is NOT in the YAML `git
add` block.

**Verify**:
- `python -c "import app; c=app.app.test_client(); print(b'/glossary' in c.get('/ledger').data)"` → `True` (footer/board-nav link present).
- `python -c "import scripts.run_daily_public_build as r; print(sum('glossary' in ' '.join(s) for s in r.VALIDATE_STEPS))"` → `2`.

### Step 7: Full suite + restore the byproduct

```
python -m pytest -q
git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json
git status --short
```
**Verify**: full suite green (~1871+ pass, plus the new assertions); `git status`
shows ONLY in-scope files (the glossary JSON, the two validators, the route/section
in app.py, `glossary.html`, the methodology/footer/board-nav edits + the tooltip
edits, the daily-build validate entries, the new tests) — the untracked `data/dd/*`
is NOT staged and the archive byproduct is restored.

## Test plan

- `tests/test_glossary.py`:
  1. **Schema gate**: a fixture term missing `id`/`term`/`definition`/`origin`
     makes `validate_glossary.py` return 1.
  2. **Example-provenance gate**: a fixture example with a `source` path that does
     not exist returns 1; an example with a source but no `as_of` returns 1.
  3. **Per-source-rank gate (ToS)**: a fixture term whose definition contains a
     named-board rank string returns 1.
  4. **see_also integrity**: a dangling `see_also` id returns 1.
  5. **Coverage gate (fail-hard)**: `validate_label_glossary_coverage.py` returns 0
     on the real glossary; a fixture with a label removed from the glossary (present
     in `MAJOR_SURFACE_LABELS`, absent from terms + EXEMPTIONS) returns 1 and names
     it.
  6. **Exemption is honored**: a label in `EXEMPTIONS` does not fail coverage.
  7. **Real coverage holds**: on the committed glossary, every
     `METRIC_LABELS`/`_DEFAULT_LABELS`/`MAJOR_SURFACE_LABELS` label resolves.
  8. **No warn-only escape hatch**: assert the coverage script has no flag/env that
     turns a failure into exit 0 (grep its source for `warn`/`--soft` returns
     nothing, or the test asserts `main()` returns 1 on an unresolved label).
- `tests/test_app.py` additions:
  1. **Render**: `GET /glossary` → 200, contains "Glossary" and the principle
     (or the `#glossary` section renders in `/methodology`).
  2. **Fail-soft**: monkeypatch the loader to empty → 200 unavailable state, not 500.
  3. **Principle + changelog on methodology**: `/methodology` contains the named
     principle and the real changelog dates, and does NOT contain `max_tokens`
     (ClaudeBot content) or a fabricated date.
  4. **Tooltip anchors resolve**: every `/glossary#<id>` rendered on a real player
     card maps to a term `id` in the committed glossary (no dangling tooltip).
  5. **Discoverability**: `/ledger` (a board page) contains a `/glossary` link.
  6. **Composition with 024**: if `/models` does not exist, the glossary renders no
     broken `/models` link (the conditional cross-link is off).
- Template render smoke: `glossary.html` + `methodology.html` load with no
  exception.
- Final: `python -m pytest -q` all green, then restore the archive byproduct.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (~1871+ pass); the byproduct file restored after.
- [ ] `data/manual/valucast_glossary.json` exists, is hand-authored (20-40 terms),
      and every term has `id`/`term`/`definition`/`origin`; every worked `example`
      cites a committed artifact `source` that exists on disk AND carries an `as_of`.
- [ ] `scripts/validate_glossary.py` fails nonzero (naming the term) on a malformed
      term, a missing example source, an example without `as_of`, a dangling
      `see_also`, and a per-source-rank string. In `VALIDATE_STEPS`.
- [ ] `scripts/validate_label_glossary_coverage.py` **fails hard** (never warns)
      when a major-surface label has no glossary term and is not an explicit
      documented EXEMPTION; passes on the real glossary; names unresolved labels.
      In `VALIDATE_STEPS`. `COVERAGE_SCOPE` honestly states which surfaces are
      enforced (card / trade / boards; it ratchets).
- [ ] The glossary renders (standalone `/glossary` or `#glossary` on `/methodology`,
      Step 1's justified choice), fail-soft (empty artifact → unavailable state,
      never 500), with the named principle at the top, per-term origin attribution,
      and worked examples showing their `as_of`.
- [ ] Consensus terms describe **aggregate median + board count only** — NO
      per-source third-party board rank anywhere in the glossary (the ToS lock).
- [ ] The **named display principle** is stated at the top of `/methodology` and is
      TRUE against the live surfaces (the `est.` tag renders, the `&mdash;` dash
      renders where data is absent, the sub-floor renders no bar).
- [ ] The **dated methodology changelog** is seeded with the real, git-verified
      history (plate-discipline 7/10, forward-gate 7/9, AOTC scorecard v2 7/2,
      SV/HLD split 7/1) — append-only; **no ClaudeBot max_tokens/exit content**; no
      invented date.
- [ ] Glossary-anchored tooltips (if shipped, not cut) point at real glossary term
      ids (no dangling anchor); they are server-rendered `<a title=…>`; **no
      tooltip adds a query param to any share-card PNG** (`_PNG_CACHE_PARAMS`
      untouched).
- [ ] `/glossary` is linked from the footer (every row) and the board-tab nav (if
      standalone); it is NOT in the primary site nav. Mutual methodology cross-link.
- [ ] Composes with plan 024 without duplication: no verdict restated, no failure
      number hardcoded; `/models` cross-links are conditional on the route existing.
- [ ] NO model/valuation/scoring/PNG code touched; the label dict *values* are read,
      never rewritten; `prospects/ahead_of_consensus.py` and
      `scripts/build_ahead_of_consensus_scorecard.py` untouched (`git diff --stat`
      empty for them).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- **A glossary worked example whose numbers cannot be traced to a committed
  artifact** (no `example.source`, or a source path that does not exist, or numbers
  that don't match the artifact). A fabricated example is exactly the dishonesty the
  display principle forbids. STOP — trace it or drop the example.
- **The every-number-resolves CI check is watered down to warn-only** (a `--warn`
  flag, an env escape hatch, exit-0 on unresolved labels). The enforcement is the
  entire competitive point vs eephus's convention. STOP and restore the hard failure.
- **A tooltip implementation adds a new query param to any share-card PNG** (would
  touch `_PNG_CACHE_PARAMS`, app.py:~154 — plan 007's invariant surface). The
  tooltips are HTML `<a title=…>` only. STOP.
- **A glossary entry names a third-party board's rank** (FanGraphs #, CFR #, HKB #,
  Pipeline #, "the board has him #N"). Consensus is aggregate median + board count
  only (ToS, plan 020). STOP.
- **A glossary term restates a model verdict or a failure number** (a verdict label,
  the forward-gate "1.21×", the AOTC "1.44×"). Those are the registry's job and are
  already stale in MEMORY — link the live artifact/page, never freeze a number. STOP.
- **A model/scoring/valuation file is being edited**, or a label dict *value* is
  being rewritten to make coverage pass. The glossary is display/copy only; it reads
  the labels, it never changes them. If coverage fails, add a glossary term or a
  documented exemption — do NOT rename the label. STOP.
- **The frozen AOTC scoring files are being touched** —
  `prospects/ahead_of_consensus.py` / `scripts/build_ahead_of_consensus_scorecard.py`.
  The glossary only *reads* the committed scorecard as an example source. STOP.
- **The route can 500 on a bad/missing glossary** — a corrupt artifact must render
  the unavailable state, not crash the page (the `/methodology` 7/2 lesson). STOP
  and restore the fail-soft path.
- **The display principle is stated but NOT true** on some live surface (a place
  that fabricates instead of dashing, or shows an unlabeled estimate). The principle
  must be true the day it ships — either the surface is fixed (in scope only if it
  is a copy/label fix, not a model change) or the principle is scoped to what is
  actually true. STOP and reconcile — never ship an untrue principle.
- **`_load_artifact` / the `front_office_report` model / the footer link rows / the
  board-nav macro / the three label dicts were refactored away** — re-locate the
  current surfaces before wiring; do NOT invent a parallel path.

## Non-goals (V1)

- **No 266-term parity with eephus.** V1 is 20-40 *real* terms covering the major
  surfaces; the coverage check ratchets. Breadth is not the point — enforcement is.
- **No auto-generated definitions.** Hand-authored, machine-validated (the
  registry/AOTC posture). A helper that *proposes* a definition is fine as a review
  aid, but the committed copy is a human decision.
- **No exhaustive label coverage on day one.** `COVERAGE_SCOPE` is honest that it
  enforces the major surfaces (card / trade / boards) and grows. A minor surface
  gaining a label is a fast-follow, not a V1 blocker.
- **No JS tooltip component / popover framework.** V1 tooltips are server-rendered
  `<a title=…>` (the existing `est.`/`(?)` pattern). The inline-`<script>` island is
  available for a later richer popover, but it is not V1 and must never add a PNG
  param.
- **No Model Verdicts registry work.** That is plan 024. The glossary defines
  vocabulary; it does not judge models.
- **No per-source third-party ranks, ever.** Aggregate median + board count only.
- **No new PNG / share card / share-card query param.**

## Rollout order

1. **Author the glossary JSON** (`data/manual/valucast_glossary.json`) — the seed
   terms with real, traceable examples, origins, the principle string, the changelog
   array; confirm every example source exists first.
2. **The two validators** (`validate_glossary.py`, `validate_label_glossary_coverage.py`)
   + their unit tests — schema/provenance + the fail-hard coverage gate green on the
   real glossary.
3. **The render surface** — the `/glossary` route + `glossary.html` (or the
   `#glossary` methodology section), fail-soft.
4. **The principle + the dated changelog** on `/methodology` — named principle at the
   top (verified true against live surfaces), the real git-verified changelog.
5. **Cross-links** — methodology↔glossary, footer (every row), board-tab entry.
6. **Glossary-anchored tooltips** (the cut-to-S lever) — the `(?)`/`est.` pattern
   pointed at `/glossary#<id>` on the card/trade/board labels; no PNG param.
7. **Daily-build validate steps** LAST (so a broken glossary or an un-glossaried
   label fails the build).

## Risks

- **Example rot (the central honesty risk).** A worked example's numbers drift as
  the underlying artifact refreshes. Mitigation: the `as_of` date on every example
  (the example is honestly a snapshot), and `validate_glossary.py` fails if the
  source path disappears. The example ages honestly; it is not silently wrong.
- **Coverage-check brittleness.** The curated `MAJOR_SURFACE_LABELS` list can drift
  from the templates. Mitigation: the check is honest via `COVERAGE_SCOPE` about
  what it enforces; when a label is added to an enforced surface, the executor adds
  it to the list AND a glossary term in the same change (that coupling is the point).
  The alternative — DOM-scanning — is explicitly rejected as brittler.
- **Principle-truth drift.** If a future surface fabricates a number, the named
  principle becomes false. Mitigation: the principle is verified true at ship, and
  the display-principle STOP condition + a test lock the claim to reality.
- **Composition with an unshipped 024.** `/models` may or may not exist at execution
  time. Mitigation: every `/models` cross-link is conditional on the route existing;
  the glossary never restates a verdict, so it composes cleanly whether 024 has
  shipped or not.
- **ToS exposure via a careless consensus term.** A definition that names a board's
  rank breaks outside boards' ToS. Mitigation: the per-source-rank denylist in
  `validate_glossary.py` + the aggregate-median-only framing rule.
- **Reading as marketing.** A glossary can drift into product copy. Mitigation: the
  origin attribution ("adopted from …" is an honest give-back), the real examples,
  and the principle that names where the site leaves boxes empty.

## Maintenance notes

- **The glossary is hand-maintained editorial copy — machine-validated.** When a
  new metric ships on a major surface, add its glossary term (with a real example)
  AND, if the coverage check flags it, either the term or a documented EXEMPTION in
  the same change. The coverage gate keeps the "every number resolves" promise real.
- **Examples are snapshots with an `as_of`.** They are allowed to age; they are
  never allowed to be untraceable. If a source artifact is renamed, update the
  example's `source` (the validator will have failed the build to force it).
- **Never a per-source rank.** Consensus is aggregate median + board count forever
  (ToS). The denylist enforces it; do not route around it.
- **The changelog is append-only.** Add dated entries; never rewrite history. Verify
  each date against git log at authoring time — never invent one, and never import a
  ClaudeBot (trading-bot) change into ValuCast's history.
- **The principle must stay true.** If the site ever adds a surface that fabricates
  a number, that is a bug against the named principle, not an exception to it — fix
  the surface, do not soften the principle.
- **Composes with, never duplicates, the Model Verdicts registry (024).** Glossary
  = vocabulary; registry = model judgments. Keep them cross-linked (conditionally)
  but distinct; a glossary term that starts restating verdicts has crossed into the
  registry's lane — pull it back.
