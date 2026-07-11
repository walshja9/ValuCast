# Plan 024: Model Verdicts Registry — a public `/models` page listing every ValuCast model/subsystem with an honest four-way verdict (VALIDATED / PROVISIONAL / DEPRECATED / REJECTED), each row citing a committed evidence artifact a reader can open, with a build-time validator that fails if any cited artifact path is missing

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> ```
> git log -1 --format=%h    # baseline for this plan is f60b8545
> git diff --stat f60b8545..HEAD -- app.py templates/base.html templates/partials/_footer_provenance.html templates/partials/_board_nav.html templates/methodology.html templates/track_record.html templates/gaps.html static/style.css scripts/run_daily_public_build.py
> git status --short
> ```
> This plan was written against `f60b8545`. All "Current state" line refs are
> accurate to that commit. If any in-scope file changed since, re-read the cited
> excerpt against the live code before proceeding; on a mismatch with an excerpt,
> treat it as a STOP condition. In particular the artifact loader
> (`_load_artifact`, app.py:~4777-4795), the `/front-office` route
> (app.py:4765-4773) — the cleanest fail-soft page-route model — the footer
> provenance link rows (`_footer_provenance.html:22,25-49`), and the board-tab
> macro (`_board_nav.html:2-20`) are the load-bearing reuse surfaces — re-verify
> them at HEAD.
>
> **This is a NEW-FEATURE / new-public-page plan.** It adds one committed,
> hand-maintained registry JSON, one build-time validator, one fail-soft route,
> one template, a methodology cross-link, and a footer/nav placement. Nothing
> here is frozen-file-blocked. Master auto-deploys valucast.app via Render, so do
> NOT push; the reviewer gates the push.

## Status

- **Priority**: P2 (competitive-gap / trust-surface depth, not a correctness or
  honesty leak in the existing product). The existing accountability surfaces
  (the AOTC ledger `/ledger`, Call-Up Receipts `/receipts`, the methodology
  forward-gate paragraph) already publish call-level and model-level honesty;
  this plan *indexes* them into one accountability layer and adds the one thing
  the site does not yet have in a single place — a per-model verdict a reader can
  scan.
- **Effort**: **M**. It is one committed JSON (hand-authored), one small
  validator in the `scripts/validate_*.py` family, one fail-soft route modeled
  1:1 on `/front-office`, one table-driven template modeled on
  `track_record.html`/`gaps.html`, one methodology section, footer + board-tab
  links, and a CI/test lock. No new model, no network, no pipeline math. The
  **cut-to-S lever is the coverage lock** (Step 6's "every major surface has a
  row" assertion): the registry + validator + page can ship first and the
  coverage lock lands as a fast-follow if the day runs long. See "Scope" for the
  explicit cut line. Do NOT cut the artifact-path validator — a verdict without
  evidence is the whole thing this page is against.
- **Risk**: MEDIUM. The sharp edges are all *honesty*, not mechanics: (a) a
  verdict must never overclaim — a `shadow_only`/`insufficient_sample` artifact
  maps to PROVISIONAL, never VALIDATED, and the editor must resist upgrading; (b)
  **no failure number is hardcoded** — the forward-gate "1.21×" and the AOTC
  lift number are *already stale in MEMORY* and are computed live from artifacts
  on the pages that show them; the registry links to the artifact and lets the
  reader open the current number, it does not restate a frozen figure; (c) the
  page must not read as marketing (the Intelligence Hub already does "Ready /
  Live / Next build" lane copy — this is the OPPOSITE: it publishes what is *not*
  proven, including the disclosed failures, as first-class content); (d) the
  validator must fail the build on a missing artifact path so a verdict can never
  outlive its evidence.
- **Depends on**: none in flight. Reads existing committed artifacts read-only.
  Executes post-7/13, so it MAY cite the AOTC scorecard artifact
  (`data/models/valucast_ahead_of_consensus_scorecard.json`) as a registry row's
  evidence — but it does NOT touch the frozen AOTC *scoring* files (see Scope).
- **Category**: feature (product — new public accountability page).
- **Planned at**: commit `f60b8545`, 2026-07-11.
- **Execution window**: **post-7/13.** No frozen-file dependency in the edit set,
  but do not start before the 7/13 ledger-week unlock (repo-wide batch-3
  convention). It reads the AOTC scorecard as *evidence only*; it never writes or
  re-scores it.

## Why this matters

Competitive origin: eephus.io ships a **79-model registry** with four-way
verdicts, committed eval artifacts, and *published failures*. It is the one place
they out-rigor us. ValuCast already has the harder half — **call-level ledgers**
(the AOTC scorecard at `/ledger` + `/aotc-scorecard.json`, the Call-Up Receipts
at `/receipts`) that they do **not** have. Adding a model-level registry gives
ValuCast **two accountability layers** — "here is every model and whether we've
proven it" *and* "here is every individual call and how it turned out" — which
nobody else in the space has. This plan builds the missing first layer and links
the two.

The credibility core is the **published failures**, and they are mandatory
content, not optional:

1. **The forward-gate is currently LOSING to Steamer.** The methodology page
   already says so in prose ("A live forward check is running — and currently
   losing", `methodology.html:352-360`), computed live from
   `data/models/valucast_mlb_projection_source_comparison.json` (`gate.model_score`
   ≈ 1.21 at planning, `marcel_beats_steamer: false`, `advisory_only: true`,
   gate `status: insufficient_sample`). The registry's MLB-projection row carries
   verdict PROVISIONAL (or REJECTED-so-far, editor's call — it does NOT beat the
   external board) and cites that artifact. **Do not restate the number in the
   registry file** — link the artifact; the number is already computed live where
   it renders and MEMORY's "1.21×" is exactly the kind of figure that goes stale.
2. **The W target is untrainable.** There is no `W` in the label seasons, so a
   preset with `W` hits the partial-coverage refusal (`prospects/adapters.py:30-33`
   comment: "no W in the label seasons"). This is a real, on-the-record modeling
   limit the *site never states plainly* today — the registry closes that gap
   with an explicit DEPRECATED/REJECTED row for the W-inclusive preset lane,
   citing the adapter coverage evidence.
3. **Usage features were gate-rejected.** Per the identity-polish work, usage
   features were rejected by the backtest gate. This is currently disclosed
   *nowhere on the live site* (grep found no in-repo template/artifact copy). The
   registry adds a REJECTED row — but **the executor must first locate the
   committed evidence** (an adapter/backtest artifact or a plans/docs note) and
   cite it; **if no committed artifact substantiates the rejection, the row is
   OMITTED, not asserted from memory** (STOP condition — no verdict without
   evidence).

The honesty bar is the same as everywhere else on the site, with three hard
edges baked into the plan: **(a)** every verdict row cites a committed artifact
path (no row renders without one, and the validator fails the build otherwise);
**(b)** verdict labels never overclaim the artifact's own status (a `shadow_only`
backtest is PROVISIONAL, never VALIDATED); **(c)** as-of dates come from each
artifact's own `generated_at`, rendered with the site's `editorial_date` macro —
the registry never invents freshness.

## Current state

Verified against the live files at `f60b8545`. Read each cited line yourself
before building on it.

### The fail-soft page-route precedent is `/front-office`

- **The exact route shape to mirror.** `front_office_report()` (app.py:4765-4773)
  is a three-line, fail-soft page route: build a `Path` to a `data/models/*.json`,
  `json.loads(...read_text())` inside a `try/except (OSError, json.JSONDecodeError)`
  that degrades to `report = None`, then `render_template("front_office.html",
  report=report)`. **The registry route is this exact shape** — load
  `data/models/valucast_model_registry.json`, degrade to `None`/empty, render.
  A missing or malformed artifact must render an "unavailable" page, never 500
  (the 7/2 audit lesson: `/methodology` was the one route that could 500 on a bad
  refresh — every sibling degrades).
- **Better still, use `_load_artifact`** (app.py:~4777-4795): an mtime-stamped,
  cached, fail-soft JSON loader returning a `dict` or `None`. The board pages
  (`/gaps` app.py:7607, `/intelligence` app.py:4840-4849) use it. Use it here —
  do NOT add a new caching mechanism.
- **The `/gaps` route (app.py:7601-7628)** is the closest *board-page* precedent:
  `_load_artifact(PATH) or {}`, pull sub-lists, compute a staleness flag against
  the site's single 7-day bar (`_within_stale_window(board_min_date)`,
  app.py:7614), pass an `as_of`, and `render_template`. The registry page follows
  this: load the registry, pass the rows + an `as_of` (the registry file's own
  `generated_at`), render. No per-request fetch, ever (Render 502 lesson).

### The committed evidence artifacts already exist and already carry status + dates

The registry cites artifacts that are **already built and committed daily** under
`data/models/`. Confirmed present at `f60b8545` (sizes/dates from the 7/11 build):

- **MLB projection / forward-gate** —
  `data/models/valucast_mlb_projection_source_comparison.json`. Keys:
  `gate` (`model_score` ≈ 1.2141, `baseline: steamer_ros`, `status:
  insufficient_sample`, `validated_through`), `marcel_beats_steamer: false`,
  `advisory_only: true`, `live_source_flip` (`automatic: false`,
  `default: current`). This is the **forward-gate published-failure evidence**;
  it is already the artifact the `/methodology` route reads for the "currently
  losing" paragraph (app.py:4730-4736). Registry row → PROVISIONAL (does not beat
  the external board yet), cites this file.
- **Prospect Rank v1 calibration** —
  `data/models/valucast_prospect_calibration_report.json`
  (`status: needs_review`, `generated_at`, `metrics`, `criteria`,
  `recommendations`). Built by `scripts/build_prospect_calibration_report.py`
  → `prospects/calibration_report.py` (`ARTIFACT_PATH` line 20).
- **Prospect coverage audit** —
  `data/models/valucast_prospect_coverage_audit.json`
  (`status: candidate_ready`, `blockers`, `criteria`). Built by
  `scripts/build_prospect_coverage_audit.py` → `prospects/coverage_audit.py:15`.
- **Peak Projection v1 calibration** —
  `data/models/valucast_prospect_peak_projection_calibration.json`
  (`buckets`, `validation`, `summary`, `watch_items`). Built by
  `scripts/build_prospect_peak_calibration_report.py` →
  `prospects/peak_calibration.py:17`. (The model itself:
  `data/models/valucast_prospect_peak_projection_v1.json`, built by
  `prospects/peak_projection.py`.)
- **Backtests (all `status: shadow_only`)** —
  `valucast_universal_prospect_index_backtest.json`,
  `valucast_prospect_dynasty_backtest.json`,
  `valucast_prospect_adapter_backtest.json`,
  `valucast_prospect_outcome_backtest.json` (`status: evidence_ready`). These are
  the **PROVISIONAL evidence** for the prospect model family — `shadow_only`
  means observed-but-not-promoted, which is exactly a PROVISIONAL verdict, never
  VALIDATED.
- **Shape comps** — `data/models/valucast_prospect_comps.json` (`method`,
  `players`, `tier_labels`; module `prospects/comps.py`). Display-only; the
  methodology already calls them "measured, not vibes"
  (`methodology.html` Prospect Rank v1 section). A VALIDATED-as-*measured* row
  (it is deterministic and reproducible), citing this artifact.
- **Pitch discipline (plan 023)** — `data/models/valucast_pitch_discipline.json`.
  Metadata under `cohorts.calibration`: `n_train: 411354`, `n_held: 102839`,
  `n_pairs: 514193`, `held_out_agreement_pct: 97.3`, `agreement_floor_pct: 85.0`,
  `fit_r2: 0.9427`, `passes_quality_gate: true`, `fitted_at`. `source_policy`:
  `observe_only: true`, `feeds_rank: false`, `feeds_value: false`. The **exact**
  metrics are VALIDATED (ProspectSavant-matched); the **estimated** zone metrics
  are PROVISIONAL (calibrated, ≥85% agreement bar, tagged "est."). One row, or a
  row per half — editor's call; cite this artifact for both.
- **AOTC divergence-call track record** —
  `data/models/valucast_ahead_of_consensus_scorecard.json`, served publicly at
  `/aotc-scorecard.json` (app.py:7646-7659). Evidence for the AOTC row — **read
  only**; do NOT hardcode the lift number (the 7/9 claims-register at
  `docs/audit-2026-07-09-claims-register.json:221-226` already flags MEMORY's
  "1.44×" as stale vs the live all-open ratio). Link `/ledger` + the raw JSON;
  the number renders live there.
- **Independence / freshness audits** —
  `valucast_raw_data_independence_audit.json` (`status:
  raw_ingestion_owned`), `valucast_milb_stat_freshness_audit.json`
  (`status: candidate_ready`), `valucast_prospect_card_data_audit.json`. Support
  rows if the editor wants "data-ingestion" subsystem entries.
- **Validation dir (2 files, `data/validation/`)** —
  `methodology_scorecard.json` (page↔artifact drift-locked, read by
  `/methodology` app.py:4717-4720) and `sensitivity_scorecard.json` (read at
  app.py:4724-4727). These are the **held-out Marcel/Steamer** and
  **sensitivity** evidence; cite them for the projection-methodology row.

**Every artifact above carries `generated_at`** (ISO). The registry's per-row
`as_of` is read from the cited artifact's `generated_at`, not authored by hand —
this is the freshness-honesty lock.

### The source modules the registry names (read-only — do NOT edit any)

- Universal prospect model: `prospects/universal.py`
- Peak projection v1: `prospects/peak_projection.py` (+ `prospects/peak_calibration.py`)
- Prospect Rank v1: `prospects/rank_v1.py` (+ `prospects/coverage_audit.py`, `prospects/calibration_report.py`)
- MiLB translation: `prospects/milb_translation.py` (pure, observe-only, "never a value input")
- Shape comps: `prospects/comps.py` (`CompPool`)
- Pitch discipline: `prospects/pitch_discipline.py` (plan 023)
- SV/HLD split targets: `projections/models/marcel_pitcher.py` (SV + HLD regressed
  separately, summed at line 184; category in `web/category_registry.py:52`) —
  **note this lives in the Marcel engine, not `prospects/`**; its evidence is the
  methodology/sensitivity scorecards, not a dedicated file.
- W-target limitation: `prospects/adapters.py:30-33` (the "no W in the label
  seasons" refusal) — the DEPRECATED/REJECTED W-preset row's on-record source.

### The methodology page structure + the trust-grammar this page must match

- **`templates/methodology.html`** is an `<article class="methodology">` of plain
  `<section>`/`<h3>` blocks; anchored sections use either `id` on the `<section>`
  (`dynasty-value-scale`, `sensitivity`, `plate-discipline`) or on an inner
  `<h3>` (`aotc-rules`, linked as `/methodology#aotc-rules`). Add the registry
  cross-link section the same way: `<section id="model-verdicts">` (id-on-section
  is the majority pattern, 3 of 4).
- **The forward-gate disclosure** (`methodology.html:343-361`) is the template for
  honest failure copy: "we lack matching archived preseason projections… ValuCast
  has **not yet proven** it beats Steamer… A live forward check is running — and
  currently losing… We publish it here rather than wait for it to look better."
  The registry inherits that voice.
- **Trust grammar / dates**: the canonical date macro is
  `{% from "partials/_editorial_date.html" import editorial_date %}`
  → `editorial_date(iso)` renders `"JULY 11, 2026"`. The stale-notice pattern is
  `templates/partials/_stale_notice.html` (`<div class="notice">Showing the most
  recent validated ValuCast snapshot…</div>`) and the page-local variant in
  `gaps.html:18-20`. The recurring device is **state the number, then state the
  limitation** ("Being different isn't being right; the ledger decides."). The
  registry uses all three.

### The nav / footer placement surfaces

- **Primary site nav** (`templates/base.html:31-37`) is a deliberately minimal
  5-link bar (Board, Backfields, Map, Intelligence Hub, Methodology). `/ledger`,
  `/gaps`, `/receipts`, `/cards` are **NOT** here. **The registry does NOT go in
  the primary nav** (matches the convention: accountability sub-pages live
  elsewhere).
- **Board-tab macro** (`templates/partials/_board_nav.html:2-20`, `.horizon-tabs`)
  is where board pages tab (…Gaps, Receipts, Buys, Trade, Ledger, Cards). Adding
  a "Models" tab here (adjacent to Ledger/Gaps — the other "here's where we're
  honest" surfaces) is the **primary discoverability placement**. It is a static
  `<a href="/models" class="htab…">Models</a>` line; no gating flag (the registry
  is always available).
- **Footer** (`templates/partials/_footer_provenance.html:22, 25-49`) carries the
  trust-surface links (The Ledger, Front Office Track, The Second Opinion) in
  both the methodology/scouting/intelligence row (L22) and the board rows
  (L25-49). Add a "Model Verdicts" link there alongside "The Ledger" in **every**
  link row (they are near-duplicates — do all of them, or the link is missing on
  half the site).
- **The methodology cross-link** is the fourth placement: the new
  `#model-verdicts` section links out to `/models`, and `/models` links back to
  `/methodology` (mutual, per the ledger↔methodology precedent).

### The board-page template + design tokens to reuse

- **Model the page on `templates/track_record.html`** (the `/ledger` page) — it is
  literally a public accountability registry: a `.buys-heading …glass` hero
  (eyebrow / `<h1>` / sub / fineprint), a status-tile funnel
  (`.ledger-tile`/`.ledger-funnel`, win=`--c-signal` teal, loss=`--c-clay`,
  open=`--c-slate`), and a filterable list of individual tagged claims. A
  verdict-count strip (VALIDATED / PROVISIONAL / DEPRECATED / REJECTED counts)
  maps directly onto the tile funnel; the verdict rows map onto the claim list.
  `templates/gaps.html` is the second model if a plainer two-column table reads
  better.
- **The verdict TABLE** reuses `.provenance-table.ledger` (`static/style.css:660`,
  the class every methodology table uses) inside a `.glass` section.
- **Design tokens** (`static/style.css:22-86` `:root`): reuse `--c-signal`
  (#34e2c4 teal, the one true accent — VALIDATED), `--c-amber` (#fbbf24
  caution/uncertainty — PROVISIONAL), `--c-clay` (#d0745c decline — REJECTED),
  `--c-slate` (#5e6678 inactive — DEPRECATED). Do NOT invent a new color scale.
  Use `--font-display`/`--font-body`/`--font-mono`, `--radius*`, `.glass`,
  `.notice` as the site does.

### There is NO existing registry route/template/artifact (clean to create)

- `grep @app.route '/models'|'/registry'` → none. `ls templates | grep
  models|registry|verdict` → none. `data/models/valucast_model_registry.json`
  does not exist. Step 1 creates all of them. If any already exist at HEAD,
  someone landed here first — STOP and reconcile.
- **Do NOT conflate with the Intelligence Hub** (`/intelligence`, app.py:4836,
  `templates/intelligence.html`). That page builds marketing "lanes" with
  statuses "Ready / Live / Next build" (app.py:4856+) — it sells the product. The
  registry is the opposite posture: it publishes what is *unproven and rejected*.
  Different page, different voice; do not merge them.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Registry-file schema/artifact validator | `python scripts/validate_model_registry.py` | prints OK, exit 0; nonzero if any cited artifact path is missing |
| Coverage lock + validator unit tests | `python -m pytest -q tests/test_model_registry.py` | all pass |
| App/route render tests | `python -m pytest -q tests/test_app.py -k "model_registry or models_page"` | all pass |
| Page renders | `python -c "import app; c=app.app.test_client(); r=c.get('/models'); print(r.status_code, b'Model Verdicts' in r.data)"` | `200 True` |
| Every cited artifact exists (manual smoke) | `python -c "import json,os; d=json.load(open('data/models/valucast_model_registry.json')); miss=[e['evidence'] for e in d['entries'] if not os.path.exists(e['evidence'])]; print('MISSING:', miss)"` | `MISSING: []` |
| Forward-gate evidence is live (failure is real) | `python -c "import json; d=json.load(open('data/models/valucast_mlb_projection_source_comparison.json')); print(d['gate']['model_score'], d['marcel_beats_steamer'], d['gate']['status'])"` | a float >1.0, `False`, `insufficient_sample` (or current values) |
| Methodology cross-link renders | `python -c "import app; c=app.app.test_client(); h=c.get('/methodology').data.decode(); print('model-verdicts' in h and '/models' in h)"` | `True` |
| Fail-soft (corrupt artifact) | temporarily point the loader at a bad path OR test with a monkeypatched empty artifact | route returns 200 "unavailable" state, never 500 |
| Full suite (final gate) | `python -m pytest -q` | ~1871+ pass, 0 fail; then restore the byproduct (below) |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | file back to HEAD (pytest dirties it — NEVER commit it) |

## Scope

**In scope** (the only files you create or modify):

- **NEW `data/models/valucast_model_registry.json`** — the **hand-maintained**
  registry (decision + justification in Step 1). One top-level object:
  `{"schema_version", "generated_at" (the hand-edit date), "verdict_definitions",
  "entries": [ {…} ]}`. Each entry:
  `{"id", "name", "subsystem_kind" (model|layer|audit|projection), "verdict"
  (VALIDATED|PROVISIONAL|DEPRECATED|REJECTED), "verdict_reason" (one honest
  sentence), "evidence" (a committed path under data/, e.g.
  "data/models/valucast_prospect_calibration_report.json"), "evidence_label"
  (human link text), "source_module" (e.g. "prospects/peak_projection.py"),
  "feeds_value" (bool), "public_page" (optional route, e.g. "/ledger")}`. The
  per-row `as_of` is NOT stored here — it is read at render time from the cited
  artifact's `generated_at` (freshness-honesty lock).
- **NEW `scripts/validate_model_registry.py`** — the build-time validator, in the
  `scripts/validate_*.py` family. Asserts: (1) the registry parses; (2) **every
  `entry.evidence` path exists on disk** (fail nonzero + name the missing path if
  not — this is the load-bearing gate); (3) every `verdict` is one of the four
  allowed labels; (4) every `entry.source_module` path exists; (5) no
  `verdict == "VALIDATED"` row cites an artifact whose own `status` field is one
  of the not-yet-proven markers (`shadow_only`, `insufficient_sample`,
  `needs_review`, `candidate_ready`) — the overclaim guard. Prints a one-line OK
  summary on success.
- **`app.py`** — one new route `@app.route("/models")` → `models_registry()`,
  modeled on `front_office_report()` (app.py:4765-4773): `_load_artifact(
  MODEL_REGISTRY_PATH)`, build a render list that joins each entry to its cited
  artifact's `generated_at` (via `_load_artifact` on the evidence path, fail-soft
  to `None` as_of), pass `entries` + a page-level `as_of` (the registry file's
  `generated_at`) + a verdict-count summary, `render_template("models.html", …)`.
  Add a module-level `MODEL_REGISTRY_PATH` constant next to the other
  `data/models` path constants. No cache/scoring/PNG region touched.
- **NEW `templates/models.html`** — the page. `{% extends "base.html" %}`, a
  `.buys-heading …glass` hero (eyebrow "ACCOUNTABILITY", `<h1>Model Verdicts</h1>`,
  sub explaining the four verdicts + the two-layer point, fineprint linking
  `/ledger`+`/receipts` as the call-level layer), the board-tab macro with
  `active='models'`, a verdict-count tile strip (reuse `.ledger-tile`/`-funnel`
  classes + the token colors), and a `.provenance-table.ledger` of rows: Model /
  Verdict badge / Reason / Evidence (link to the artifact or its public page) /
  As of (each row's cited-artifact `generated_at` via `editorial_date`). A
  `{% if not entries %}` unavailable state (never an empty shell). The
  **disclosed failures render as first-class rows**, not hidden.
- **`templates/methodology.html`** — a new `<section id="model-verdicts">`
  (mirror the `plate-discipline`/`sensitivity` section grammar) that states the
  two-layer accountability model in one short paragraph and links to `/models`.
- **`templates/partials/_board_nav.html`** — add one tab
  `<a href="/models" class="htab{% if active == 'models' %} on{% endif %}"…>Models</a>`
  adjacent to Ledger (no gating flag).
- **`templates/partials/_footer_provenance.html`** — add
  `- <a href="/models">Model Verdicts</a>` alongside `/ledger` in **every** link
  row (L22 and the board rows L25-49) — they are near-duplicates; add to all so
  the link is not missing on half the site.
- **`scripts/run_daily_public_build.py`** — add ONLY the validator to
  `VALIDATE_STEPS` (`("scripts/validate_model_registry.py",)`), so a stale/broken
  registry (a verdict whose evidence file was renamed/removed) fails the daily
  build. Do **NOT** add a build step — the registry is hand-maintained, not
  computed (Step 1 decision).
- **NEW tests**: `tests/test_model_registry.py` (validator logic on a fixture:
  missing-evidence fails, bad-verdict-label fails, VALIDATED-over-shadow_only
  fails; plus the **coverage lock** — every major surface has a row) and
  additions to `tests/test_app.py` (route renders 200 + contains the verdict
  labels + the methodology cross-link + a fail-soft empty-artifact case).

**Cut line to hold Effort (the reviewer decides at planning time):**

- **CORE (must ship): the registry JSON + the artifact-path validator + the
  `/models` page + the methodology cross-link + one footer link.** This is the
  product: honest verdicts, each artifact-backed, the disclosed failures visible.
  The validator's missing-evidence gate is NON-cuttable.
- **CUT-CANDIDATE: the "every major surface has a row" coverage lock** (Step 6's
  test that fails if a listed major surface lacks a registry entry). If the day
  runs long, ship the registry + page + the *existence* validator, and file the
  coverage lock as a fast-follow. The registry is still honest without it (it
  just isn't *guaranteed complete*). **Do not** cut the overclaim guard (no
  VALIDATED over a not-yet-proven artifact) — that is a one-line assertion and is
  core honesty.
- **Secondary cut (only if still over): the board-tab entry.** Ship the footer +
  methodology cross-link for discoverability first; add the `_board_nav.html`
  "Models" tab as a fast-follow. The page is reachable and linked either way.

**Out of scope** (do NOT touch):

- **Any model math / valuation / scoring.** The registry is *display-only* — it
  reads artifacts and prints verdicts. It NEVER changes a value, a rank, a
  projection, or a gate. Do not edit any `prospects/*.py`, `projections/*.py`,
  `web/valuation*`, or `web/category_registry.py`.
- **The frozen AOTC scoring files** — `prospects/ahead_of_consensus.py`,
  `scripts/build_ahead_of_consensus_scorecard.py` (pre-registered scoring,
  ~7/13). The registry **reads** the committed scorecard artifact and links
  `/ledger`; it does NOT re-score, re-derive, or touch those files.
- **Auto-deriving verdicts from artifact `status` fields.** The four-way verdict
  is an *editorial judgment* (Step 1). The validator may *check* that a verdict
  doesn't overclaim its artifact, but the executor does NOT write code that
  computes the verdict label from `status`. A `shadow_only` artifact could be
  PROVISIONAL *or* (if superseded) DEPRECATED — that is a human call.
- **The Intelligence Hub** (`/intelligence`, `templates/intelligence.html`). Do
  not merge, restyle, or re-lane it. It is a separate marketing surface.
- **The primary site nav** (`base.html:31-37`). The registry does not go in the
  5-link bar.
- **Any PNG / share card / `_PNG_CACHE_PARAMS`.** V1 is an HTML page only — no new
  graphic, no new share-card query param.
- **DD (`dd_*`) feeds.** ValuCast is DD-independent. The registry cites only
  ValuCast-owned artifacts. Do NOT read `data/dd/*`.
- **Restating any failure number as a literal in the registry file.** The
  forward-gate ratio and the AOTC lift are computed live where they render and
  are already stale in MEMORY. The registry links the artifact/page; it does not
  freeze a number (STOP condition).

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT
  push**: master auto-deploys valucast.app via Render. Commit locally; the
  reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — untracked `data/dd/*` and
  pytest byproducts must not be swept in). Stage each in-scope file explicitly by
  path. **Never `git stash`.**
- Do NOT stage `data/prediction_archive/.../2026-06-15.json` (pytest byproduct)
  or any untracked `data/dd/*`.
- The registry JSON is a **hand-authored committed source file** (not a
  daily-build output), so it is staged like any source file — it is NOT added to
  the `daily-public-data.yml` `git add` block.
- Commit message style (short imperative subject), e.g.
  `Add Model Verdicts registry (/models): four-way honest verdicts + artifact-backed evidence + build-time missing-evidence gate`.

## Steps

### Step 0: Confirm the reuse surfaces are live and the registry does not yet exist

```
# The fail-soft page-route model exists:
python -c "import app; print(hasattr(app,'_load_artifact'))"
# expect: True
# The forward-gate published-failure evidence is present and IS a failure:
python -c "import json; d=json.load(open('data/models/valucast_mlb_projection_source_comparison.json')); print(d['gate']['model_score'], d['marcel_beats_steamer'], d['gate']['status'])"
# expect: a float >1.0, False, 'insufficient_sample'  (values may drift; a failure is the point)
# The daily validate list exists:
python -c "import scripts.run_daily_public_build as r; print(len(r.VALIDATE_STEPS))"
# expect: an integer
# There is NO registry route/template/artifact yet:
python -c "import os; print(os.path.exists('data/models/valucast_model_registry.json'), os.path.exists('templates/models.html'))"
# expect: False False
python -c "import app; print(any(str(r)=='/models' for r in app.app.url_map.iter_rules()))"
# expect: False
```
**Verify**: all confirm the state above. If the registry artifact/route/template
already exists, someone landed here first — STOP and reconcile.

### Step 1: Decide hand-maintained vs build-assembled, then author `data/models/valucast_model_registry.json`

**Decision: HAND-MAINTAINED, and the justification is load-bearing.** The four-way
verdict is an *editorial honesty judgment*, not a computable field. The artifacts
carry a build `status` (`shadow_only`, `needs_review`, `candidate_ready`,
`insufficient_sample`, `evidence_ready`) — but those are *pipeline* states, not
*public verdicts*. `shadow_only` maps to PROVISIONAL today, but if a model is
superseded it becomes DEPRECATED with the same underlying `status`; only a human
knows that. Auto-deriving would either overclaim (promote a shadow to VALIDATED)
or lose the DEPRECATED/REJECTED distinction the page exists to make. So the
registry is authored by hand and the **validator (Step 2) is what makes it
trustworthy**: it enforces that every hand-written verdict is artifact-backed and
non-overclaiming. This is the same posture as the pre-registered AOTC targets —
human-authored, machine-enforced.

Author the entries. **Every entry MUST cite a committed artifact that exists.**
For each candidate below, first confirm the evidence file is present (Step 0's
`ls data/models`), then write the row. Minimum entry set (the "major surfaces" the
coverage lock in Step 6 will enforce):

1. **MLB Projection (H+P / Marcel)** — verdict PROVISIONAL. Reason: beats internal
   baselines (persistence, classic Marcel) on held-out data but has **not** beaten
   Steamer; the live forward check is currently losing and below the 30-day gate.
   Evidence: `data/validation/methodology_scorecard.json` +
   `data/models/valucast_mlb_projection_source_comparison.json`. Public page:
   `/methodology`. (This is the flagship *published failure*.)
2. **Prospect Rank v1** — verdict PROVISIONAL. Evidence:
   `valucast_prospect_calibration_report.json` (`needs_review`) +
   `valucast_prospect_coverage_audit.json`. Source: `prospects/rank_v1.py`.
3. **Peak Projection v1** — verdict PROVISIONAL. Evidence:
   `valucast_prospect_peak_projection_calibration.json`. Source:
   `prospects/peak_projection.py`.
4. **Universal Prospect Model** — verdict PROVISIONAL (`shadow_only` backtest).
   Evidence: `valucast_universal_prospect_index_backtest.json`. Source:
   `prospects/universal.py`.
5. **MiLB Translation** — verdict VALIDATED-as-measured (deterministic port,
   observe-only, never a value input). Evidence: the module's own independence
   note + `valucast_raw_data_independence_audit.json`. Source:
   `prospects/milb_translation.py`. `feeds_value: false`.
6. **Shape Comps** — verdict VALIDATED-as-measured (deterministic, reproducible).
   Evidence: `valucast_prospect_comps.json`. Source: `prospects/comps.py`.
7. **Pitch Discipline — exact metrics** — verdict VALIDATED (ProspectSavant-matched).
   Evidence: `valucast_pitch_discipline.json`. Source: `prospects/pitch_discipline.py`.
8. **Pitch Discipline — estimated zone metrics** — verdict PROVISIONAL (pixel
   calibration, held-out agreement 97.3% ≥ 85% bar, tagged "est."). Same evidence
   artifact (`cohorts.calibration`).
9. **AOTC divergence calls** — verdict PROVISIONAL (live ledger, sample maturing;
   the raw all-open lift is not the matured number — link, don't restate).
   Evidence: `valucast_ahead_of_consensus_scorecard.json`. Public page: `/ledger`.
10. **W target (W-inclusive preset lane)** — verdict REJECTED/DEPRECATED. Reason:
    no `W` in the label seasons → partial-coverage refusal; ValuCast cannot train
    a W target and does not fake one. Evidence:
    `valucast_prospect_adapter_backtest.json` (or the coverage audit — pick the
    artifact that actually records the coverage refusal) + source note
    `prospects/adapters.py`. **The published-failure that the site states nowhere
    else today.**
11. **Usage features** — verdict REJECTED — **CONDITIONAL**. Reason: rejected by
    the backtest gate (no lift). **Only include this row if a committed artifact
    substantiates it** (an adapter/index backtest artifact whose recorded feature
    set / rejection note, or a committed `docs/`/`plans/` decision, proves it). If
    no committed evidence exists in-repo, **OMIT this row** — do not assert it from
    MEMORY. This is the STOP-condition case: no verdict without evidence.
12. **SV/HLD split targets** — verdict VALIDATED-as-shipped (SV and HLD regressed
    separately then summed — the correct split vs a blended proxy). Evidence: the
    methodology/sensitivity scorecards (SV/HLD has no dedicated artifact). Source:
    `projections/models/marcel_pitcher.py`. Confirm the scorecard actually
    references SV_HLD before citing it; if not, cite the module + mark evidence as
    the category-registry contract, or drop to a lower-confidence verdict.

The editor picks the final verdict wording per row honestly; the *labels* must be
exactly the four allowed strings. Keep `verdict_reason` to one sentence, in the
methodology voice ("has not yet proven…", "measured, not modeled…", "cannot be
trained from the available labels…").

**Verify**:
- `python -c "import json; d=json.load(open('data/models/valucast_model_registry.json')); print(len(d['entries']), sorted({e['verdict'] for e in d['entries']}))"` → a count and a subset of `['DEPRECATED','PROVISIONAL','REJECTED','VALIDATED']`.
- Every `evidence` path exists (the smoke command in "Commands"): `MISSING: []`.

### Step 2: The build-time validator `scripts/validate_model_registry.py`

Mirror the `scripts/validate_*.py` family (thin CLI, exit-code gate). It loads the
registry and asserts, failing nonzero with a named reason on any violation:

```python
"""Validate the Model Verdicts registry: every verdict is artifact-backed and
non-overclaiming. Run in the daily build's VALIDATE_STEPS so a renamed/removed
evidence artifact fails the build instead of shipping a verdict with no evidence."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "models" / "valucast_model_registry.json"
VERDICTS = {"VALIDATED", "PROVISIONAL", "DEPRECATED", "REJECTED"}
# An artifact carrying one of these build-statuses is NOT yet proven -> a
# VALIDATED verdict over it is an overclaim.
NOT_PROVEN = {"shadow_only", "insufficient_sample", "needs_review", "candidate_ready"}

def main() -> int:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    errs = []
    for e in reg.get("entries", []):
        eid = e.get("id", "?")
        if e.get("verdict") not in VERDICTS:
            errs.append(f"{eid}: bad verdict {e.get('verdict')!r}")
        ev = e.get("evidence")
        ev_path = ROOT / ev if ev else None
        if not ev or not ev_path.exists():
            errs.append(f"{eid}: missing evidence artifact {ev!r}")
        sm = e.get("source_module")
        if not sm or not (ROOT / sm).exists():
            errs.append(f"{eid}: missing source_module {sm!r}")
        # Overclaim guard: VALIDATED must not cite a not-yet-proven artifact.
        if e.get("verdict") == "VALIDATED" and ev_path and ev_path.exists():
            try:
                st = (json.loads(ev_path.read_text(encoding="utf-8")) or {}).get("status")
            except (OSError, ValueError):
                st = None
            if st in NOT_PROVEN:
                errs.append(f"{eid}: VALIDATED over not-yet-proven artifact status {st!r}")
    if errs:
        print("MODEL REGISTRY INVALID:\n  " + "\n  ".join(errs)); return 1
    print(f"OK: model registry {len(reg.get('entries', []))} entries, all artifact-backed"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

**Verify**:
- `python scripts/validate_model_registry.py` → prints OK, exit 0.
- Temporarily rename one cited artifact (or point one `evidence` at a bogus path in a scratch copy) → the validator exits 1 and names the missing path. Restore.

### Step 3: The `/models` route in `app.py`

Model on `front_office_report()` (app.py:4765-4773). Add a `MODEL_REGISTRY_PATH`
constant near the other `data/models` path constants, then:

```python
@app.route("/models")
def models_registry():
    """Public Model Verdicts registry: every ValuCast model/subsystem with an
    honest four-way verdict, each row citing a committed evidence artifact. The
    second accountability layer next to the call-level ledgers (/ledger,
    /receipts). Fail-soft: a missing/corrupt registry renders an unavailable
    state, never a 500 (the /methodology 7/2 lesson)."""
    reg = _load_artifact(MODEL_REGISTRY_PATH) or {}
    entries = []
    for e in reg.get("entries", []):
        art = _load_artifact(Path(__file__).parent / e["evidence"]) if e.get("evidence") else None
        entries.append({**e, "as_of": (art or {}).get("generated_at")})
    counts = {}
    for e in entries:
        counts[e["verdict"]] = counts.get(e["verdict"], 0) + 1
    return render_template(
        "models.html", models_page=True,
        entries=entries, verdict_counts=counts,
        verdict_definitions=reg.get("verdict_definitions") or {},
        as_of=reg.get("generated_at"),
    )
```

Keep it fail-soft (`or {}` everywhere), no per-request fetch. Do not touch the
cache/scoring/PNG regions.

**Verify**:
- `python -c "import app; c=app.app.test_client(); r=c.get('/models'); print(r.status_code)"` → `200`.
- With the artifact temporarily unreadable, the route still returns 200 (unavailable state), never 500.

### Step 4: The `templates/models.html` page

`{% extends "base.html" %}`, `{% from "partials/_editorial_date.html" import
editorial_date %}`, `{% from "partials/_board_nav.html" import board_nav %}`.

- Hero: `.buys-heading …glass` with eyebrow "ACCOUNTABILITY", `<h1>Model
  Verdicts</h1>`, a `.buys-heading-sub` explaining the four verdicts and the
  two-layer point ("Every model here is judged VALIDATED, PROVISIONAL, DEPRECATED,
  or REJECTED — and every verdict links to the committed evidence behind it. This
  is the model-level layer; the call-level layer is the
  [Ledger](/ledger) and [Receipts](/receipts)."), a `.buys-fineprint` with the
  page `as_of` via `editorial_date`.
- `{{ board_nav(active='models') }}`.
- A verdict-count tile strip: reuse `.ledger-funnel`/`.ledger-tile`; color the
  VALIDATED tile with `--c-signal`, PROVISIONAL `--c-amber`, DEPRECATED
  `--c-slate`, REJECTED `--c-clay`.
- The `.provenance-table.ledger`: columns **Model | Verdict | Reason | Evidence |
  As of**. The Verdict cell is a badge span colored by the token map. The Evidence
  cell links to `entry.public_page` if present else to the raw artifact
  (`/{{ entry.evidence }}` is committed and served as a static file, or link the
  public page — prefer the public page when one exists). The As-of cell renders
  `{% if entry.as_of %}{{ editorial_date(entry.as_of) }}{% endif %}` (the cited
  artifact's own freshness, not a hand date).
- `{% if not entries %}` an unavailable notice (`.notice`) — never an empty shell.
- The disclosed-failure rows (forward-gate PROVISIONAL, W REJECTED) render
  **inline in the table like every other row** — they are the point, not a
  footnote.

**Verify**:
- `python -c "import jinja2; jinja2.Environment(loader=jinja2.FileSystemLoader('templates')).get_template('models.html')"` → no exception.
- Page render contains "Model Verdicts", all four verdict labels that appear in the registry, and the `/ledger` + `/receipts` cross-links.

### Step 5: Methodology cross-link + footer + board tab

**5a — Methodology** (`templates/methodology.html`): add
`<section id="model-verdicts">` (mirror the `plate-discipline` section grammar,
~end of the article) with a one-paragraph statement of the two-layer
accountability model and a link to `/models`. Keep the "state the limitation"
voice.

**5b — Footer** (`templates/partials/_footer_provenance.html`): add
`- <a href="/models">Model Verdicts</a>` next to the `/ledger` ("The Ledger")
link in **every** link row (L22 and the board rows L25-49). They are near
duplicates — add it to all.

**5c — Board tab** (`templates/partials/_board_nav.html`): add
`<a href="/models" class="htab{% if active == 'models' %} on{% endif %}"{% if active == 'models' %} aria-current="page"{% endif %}>Models</a>`
adjacent to the Ledger tab (no gating flag).

**Verify**:
- `python -c "import app; c=app.app.test_client(); h=c.get('/methodology').data.decode(); print('model-verdicts' in h and '/models' in h)"` → `True`.
- `python -c "import app; c=app.app.test_client(); print(b'/models' in c.get('/ledger').data)"` → `True` (footer/board-nav link present).

### Step 6: Wire the validator into the daily build + the coverage/CI lock

**6a — Daily validate step** (`scripts/run_daily_public_build.py`): append
`("scripts/validate_model_registry.py",)` to `VALIDATE_STEPS` (near the other
`validate_*` entries; respect the `validate_steps()` duplicate-guard if present).
Do NOT add a `BUILD_STEPS` entry — the registry is hand-maintained.

**6b — The coverage lock** (`tests/test_model_registry.py`): the CI/test lock that
makes the registry *complete*, not just *valid*. Define the set of **major model
surfaces** that MUST each have a registry entry — lock exactly this list so a new
major model can't ship unregistered:
```python
MAJOR_SURFACES = {
    "mlb_projection",        # H+P / Marcel (the forward-gate row)
    "prospect_rank_v1",
    "peak_projection_v1",
    "universal_prospect_model",
    "milb_translation",
    "shape_comps",
    "pitch_discipline_exact",
    "aotc_calls",
    # W-target and usage-features are published FAILURES, not "major model
    # surfaces" to lock on — they are honesty rows; do not require them here,
    # but DO assert the W row exists (it is the flagship on-record limitation).
    "w_target",
}
```
Assert: (1) every `id` in `MAJOR_SURFACES` appears in the registry `entries`;
(2) the validator (`scripts/validate_model_registry.py`) returns 0 on the real
registry; (3) a fixture registry with a missing-evidence row makes the validator
return 1; (4) a fixture VALIDATED row over a `shadow_only` artifact returns 1
(overclaim guard); (5) every real `entry.evidence` file exists on disk.

**6c — App/route tests** (`tests/test_app.py`): `/models` returns 200 and contains
the verdict labels + `/ledger`/`/receipts` links; the methodology cross-link
renders; a monkeypatched empty registry renders the unavailable state (200, not
500).

**Verify**:
- `python -c "import scripts.run_daily_public_build as r; print(any('validate_model_registry' in ' '.join(s) for s in r.VALIDATE_STEPS))"` → `True`.
- `python -m pytest -q tests/test_model_registry.py tests/test_app.py -k "model_registry or models_page"` → all pass.

### Step 7: Full suite + restore the byproduct

```
python -m pytest -q
git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json
git status --short
```
**Verify**: full suite green (~1871+ pass, plus the new assertions); `git status`
shows ONLY in-scope files (the registry JSON, the validator, the route in app.py,
`models.html`, the methodology/footer/board-nav edits, the daily-build validate
entry, the new tests) — the untracked `data/dd/*` is NOT staged and the archive
byproduct is restored.

## Test plan

- `tests/test_model_registry.py`:
  1. **Coverage lock**: every `MAJOR_SURFACES` id has a registry entry (a new
     major model can't ship unregistered).
  2. **Artifact-path gate**: the validator returns 0 on the real registry; a
     fixture with a bogus `evidence` path returns 1 and names it.
  3. **Verdict-label gate**: a fixture row with a verdict not in the four allowed
     strings returns 1.
  4. **Overclaim guard**: a fixture VALIDATED row citing a `status: shadow_only`
     (or `insufficient_sample`/`needs_review`/`candidate_ready`) artifact returns 1.
  5. **Source-module gate**: a fixture row whose `source_module` path is missing
     returns 1.
  6. **Real evidence exists**: every real `entry.evidence` file exists on disk.
  7. **The W-target failure row is present** (the flagship on-record limitation is
     not silently dropped).
- `tests/test_app.py` additions:
  1. **Route renders**: `GET /models` → 200, contains "Model Verdicts", every
     verdict label present in the registry, and the `/ledger`+`/receipts` links.
  2. **Fail-soft**: with an empty/missing registry (monkeypatch the loader), the
     route returns 200 (unavailable state), not 500.
  3. **Methodology cross-link**: `GET /methodology` contains `id="model-verdicts"`
     and a `/models` link.
  4. **Discoverability**: `/ledger` (a board page) contains a `/models` link
     (footer + board-nav).
  5. **As-of honesty**: a row's rendered as-of equals the cited artifact's
     `generated_at` (formatted) — the freshness is read, not authored.
- Template render smoke: `models.html` + `methodology.html` load with no
  exception.
- Final: `python -m pytest -q` all green, then restore the archive byproduct.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (~1871+ pass); the byproduct file restored after.
- [ ] `data/models/valucast_model_registry.json` exists, is hand-authored, and
      every entry cites a committed `evidence` artifact that exists on disk.
- [ ] `scripts/validate_model_registry.py` fails nonzero (naming the row) on: a
      missing evidence artifact, a bad verdict label, a missing source module, and
      a VALIDATED verdict over a not-yet-proven artifact. It is in the daily
      build's `VALIDATE_STEPS`.
- [ ] `/models` renders 200 with a verdict-count strip and a `.provenance-table`
      of rows (Model / Verdict / Reason / Evidence / As of), and is fail-soft
      (empty artifact → unavailable state, never 500).
- [ ] The **published failures render as first-class rows**: the MLB-projection
      forward-gate (PROVISIONAL, cites
      `valucast_mlb_projection_source_comparison.json`) and the W-target
      limitation (REJECTED/DEPRECATED, cites the coverage/adapter evidence). No
      failure number is hardcoded in the registry file — verdicts link the
      artifact/public page.
- [ ] The usage-features REJECTED row is present ONLY if a committed artifact
      substantiates it; otherwise it is omitted (no verdict from memory).
- [ ] No verdict overclaims its artifact (a `shadow_only`/`insufficient_sample`
      artifact is never VALIDATED — the validator enforces it).
- [ ] Per-row `as_of` is read from each cited artifact's `generated_at` (rendered
      via `editorial_date`), never hand-authored.
- [ ] The methodology page has an `#model-verdicts` section linking `/models`;
      `/models` links back to `/methodology`, `/ledger`, and `/receipts`.
- [ ] `/models` is linked from the footer (every link row) and the board-tab nav;
      it is NOT in the primary site nav.
- [ ] The coverage lock (`MAJOR_SURFACES`) asserts every major model surface has a
      registry entry (or is filed as the documented fast-follow per the cut line).
- [ ] NO model/valuation/scoring/PNG code touched;
      `prospects/ahead_of_consensus.py` and
      `scripts/build_ahead_of_consensus_scorecard.py` untouched
      (`git diff --stat` empty for them).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- **A verdict is about to render without a committed evidence artifact** (or the
  usage-features row is being asserted from MEMORY with no in-repo artifact). No
  verdict without evidence — omit the row or find the artifact. STOP.
- **An evidence-load failure is about to render as a benign empty state.** If a
  row's artifact exists in the registry but is unreadable/missing at request
  time, that row MUST render an explicit "EVIDENCE UNAVAILABLE" error state,
  visually distinct from any "pending / insufficient data" message. A reader
  must always be able to tell "no data yet" from "the evidence link is broken."
  (The live counter-example, 7/11: eephus.io marks its source-comparison claim
  `validated` while its backtest artifact 404s, and the failure renders as a
  plausible "no resolved cohorts yet" message that its own changelog
  contradicts. That disguised-empty-state pattern is the exact failure mode
  this page must make impossible.) STOP and add the error state.
- **A verdict overclaims** — a `shadow_only` / `insufficient_sample` /
  `needs_review` / `candidate_ready` artifact is being labeled VALIDATED. That is
  the exact dishonesty this page exists to prevent. STOP and downgrade to
  PROVISIONAL (the validator will also catch it).
- **A failure number is being hardcoded into the registry file** (the forward-gate
  "1.21×", the AOTC "1.44×"). Those are already stale in MEMORY and are computed
  live where they render. Link the artifact/page; do not freeze a number. STOP.
- **The registry is being auto-generated from artifact `status` fields** instead of
  hand-authored. The four-way verdict is an editorial judgment; auto-derivation
  loses the DEPRECATED/REJECTED distinction and risks promoting a shadow to
  VALIDATED. STOP — hand-author, machine-validate.
- **A model/scoring/valuation file is being edited** to make the registry work.
  The registry is display-only; it reads artifacts, it never changes a value.
  STOP.
- **The frozen AOTC scoring files are being touched** —
  `prospects/ahead_of_consensus.py` /
  `scripts/build_ahead_of_consensus_scorecard.py`. The registry only *reads* the
  committed scorecard and links `/ledger`. STOP.
- **The route can 500 on a bad/missing registry** — a corrupt daily artifact must
  render the unavailable state, not crash the page (the `/methodology` 7/2
  lesson). STOP and restore the fail-soft path.
- **`_load_artifact` / the `/front-office` route model / the footer link rows /
  the board-nav macro were refactored away** — re-locate the current fail-soft
  page-route + link surfaces before wiring; do NOT invent a parallel path.

## Non-goals (V1)

- **No auto-derived verdicts.** Hand-authored, machine-validated. A future
  helper that *proposes* a verdict from `status` is fine as a review aid, but the
  committed verdict is a human decision — not V1, and never a silent auto-write.
- **No new PNG / share card.** V1 is an HTML page. A shareable "verdict card" is a
  natural fast-follow but would reopen the `_PNG_CACHE_PARAMS` surface — separate
  plan.
- **No re-scoring of any ledger.** The registry links `/ledger` and `/receipts`
  and reads the committed scorecard; it does not compute or re-derive any call
  outcome.
- **No Intelligence Hub merge.** Separate page, opposite posture (that one sells,
  this one publishes failures). Do not consolidate.
- **No registry entry for internal-only pipeline artifacts** that have no public
  model/subsystem behind them (e.g. `dd_independence_baseline.json`,
  `pipeline_observability`). The registry lists *models/subsystems*, not every
  JSON in `data/models/`.

## Rollout order

1. **Author the registry JSON** (`data/models/valucast_model_registry.json`) —
   confirm every cited artifact exists first; the disclosed-failure rows included.
2. **The validator** (`scripts/validate_model_registry.py`) + its unit tests —
   the missing-evidence + overclaim gates green on the real registry.
3. **The route** (`/models` in app.py) — fail-soft, reads the registry + each
   cited artifact's `generated_at`.
4. **The page** (`templates/models.html`) — hero, verdict-count strip, table,
   unavailable state.
5. **Cross-links** — methodology `#model-verdicts` section, footer link (every
   row), board-tab entry.
6. **Daily-build validate step + the coverage lock** LAST (so a stale registry
   fails the build and a new major model can't ship unregistered).

## Risks

- **Verdict overclaim (the central trust risk).** A reader trusts VALIDATED to
  mean *proven*. The mitigations: hand-authored verdicts reviewed against each
  artifact's own `status`, the validator's overclaim guard (VALIDATED over a
  not-yet-proven artifact fails the build), and the PROVISIONAL default for
  anything `shadow_only`/`insufficient_sample`.
- **Stale failure numbers.** MEMORY's "1.21×" and "1.44×" are already drifted from
  the live artifacts. Mitigation: the registry NEVER restates a number — it links
  the artifact/public page where the figure renders live. The as-of comes from the
  artifact's `generated_at`.
- **Registry rot (a cited artifact renamed/removed).** Mitigation: the validator
  runs in the daily build's `VALIDATE_STEPS` — a broken evidence path fails the
  build, so a verdict can never silently outlive its evidence.
- **Completeness drift (a new major model ships unregistered).** Mitigation: the
  `MAJOR_SURFACES` coverage lock — a new major model without a registry row fails
  CI. (If the coverage lock is cut to hold Effort, this risk is accepted until the
  fast-follow lands.)
- **Reading as marketing.** The Intelligence Hub already does upbeat lane copy;
  the registry must not. Mitigation: the disclosed failures are inline table rows,
  the copy uses the methodology "we publish it rather than wait for it to look
  better" voice, and REJECTED/DEPRECATED are first-class verdicts with their own
  color.
- **Evidence for a claimed failure not actually in the repo (usage features).**
  Mitigation: the row is CONDITIONAL — included only with a committed artifact,
  omitted otherwise (STOP condition). Better a missing row than an unbacked
  verdict.

## Maintenance notes

- **The registry is hand-maintained editorial content — machine-validated.** When
  a model's status changes (a shadow graduates, a preset is deprecated), edit the
  verdict + reason by hand and bump the file's `generated_at`; the validator keeps
  it honest (artifact-backed, non-overclaiming). Do NOT wire an auto-writer.
- **Every new major model must get a registry row.** The `MAJOR_SURFACES` lock
  enforces it — when a new model surface lands, add its `id` to the set AND author
  its row in the same change, or CI fails. That coupling is intentional: it is how
  the registry stays complete.
- **Published failures are permanent content, not temporary.** When the
  forward-gate finally clears 30 days, its verdict moves PROVISIONAL → VALIDATED
  (or stays PROVISIONAL if it still loses) — the *row stays*, the history is the
  point. Same for the W-target and any gate-rejected feature: they document what
  ValuCast tried and rejected, which is the credibility core.
- **Never hardcode a metric.** Any figure a reader might quote lives in a cited
  artifact and renders live on its public page. The registry's job is the verdict
  and the link, not the number.
- **This is the model-level layer; the call-level layer is `/ledger` +
  `/receipts`.** Keep both cross-linked. The two-layer accountability is the
  competitive claim — a broken cross-link quietly undoes the pitch.
