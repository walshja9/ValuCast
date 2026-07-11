# Plan 026: Board Time Machine — a public, self-serve `/board/<date>` view that reconstructs ValuCast's prospect board as it stood on any committed archive date, server-rendered from the daily `valucast_prospect_rank_v1` snapshots, with per-date quality flags (clean / pre-baseline / unavailable) so contaminated states are disclosed, not hidden

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> ```
> git log -1 --format=%h    # baseline for this plan is <FILL AT EXECUTION: git log -1 --format=%h>
> git status --short
> git diff --stat -- app.py web/public_snapshot_models.py prospects/ahead_of_consensus.py prospects/buys.py prospects/movers.py web/buy_score.py templates/index.html templates/partials/rankings_table_dynasty.html
> ```
> This plan was written on 2026-07-11 against the archive + reuse surfaces then
> live. All "Current state" line refs are accurate to that read. If any in-scope
> file changed since, re-read the cited excerpt against the live code before
> proceeding; on a mismatch with an excerpt, treat it as a STOP condition. In
> particular the consensus-median logic
> (`web/public_snapshot_models.py:137-155`), the frozen archive-read pattern
> (`prospects/ahead_of_consensus.py:207-217`), the epoch constant
> (`prospects/buys.py:32`), and the step/gap guard (`web/buy_score.py:80-106`)
> are the load-bearing reuse surfaces — re-verify them at HEAD.
>
> **This is a NEW-FEATURE / new-read-surface plan.** It adds ONE new route, ONE
> fail-soft reader, ONE thin template, and a small quality-flag helper. It writes
> NO new build script and NO new committed artifact — it reads archives that are
> **already committed** by the daily pipeline. Nothing here is frozen-file-blocked
> (the frozen files are READ-ONLY reuse references, never edited). Master
> auto-deploys valucast.app via Render, so do NOT push; the reviewer gates the
> push.

## Status

- **Priority**: **P2** (product depth / competitive gap + a receipts-honesty
  amplifier — not a correctness or honesty leak in the shipped product). It is a
  natural extension of the receipts/ledger program: those prove *specific* calls;
  the Time Machine lets a reader audit the *whole board* on any past date without
  asking us. Competitive origin: eephus.io ships reconstructable monthly board
  states back to 2018; ValuCast already **commits daily** board snapshots and
  exposes none of them — this surfaces what we already keep.
- **Effort**: **S–M**. No backfill, no network, no new artifact, no new build step
  in the daily pipeline. The work is: a fail-soft archive reader (model on
  `StatcastStore`/`PitchDisciplineStore`), a date-resolution + quality-flag helper
  (reusing the epoch constant + the empirical missing-date derivation), one Flask
  route, one thin server-rendered template, a small methodology/honesty note, and
  tests. The **cut-to-S lever** is the per-row consensus column: ship the core
  board (rank / name / score / level / team / age) + the quality banner + the
  as-of grammar first; the aggregate-consensus-per-row column is a clean add-on
  that can be deferred without touching the core (see "Scope" cut line).
- **Risk**: **LOW–MEDIUM**. Serving stays network-free (reads committed JSON only
  — the Statcast/FanGraphs precedent). The sharp edges are all honesty/ToS, not
  correctness: (a) **contamination disclosure** — pre-epoch board dates
  (6/13–6/21, before the 6/22 role-normalization re-baseline) MUST render a
  "pre-baseline: scores not directly comparable to today" flag, and any
  missing/unreadable date MUST fail soft to an explicit "unavailable" state, never
  a blank or a silently-substituted neighbor served *as if* it were the requested
  date; (b) **the aggregate-only consensus rule** — a historical board may show
  consensus **median + board count ONLY**, never per-source ranks, exactly as the
  live board does (hard ToS invariant, no historical exception); (c) **performance**
  — an archive JSON is ~7 MB and there are ~29 of them (growing daily); a naive
  read-per-request of the full board is acceptable at this size with mtime caching,
  but an unbounded slice or loading *all* dates per request is not (Render ~30s /
  2-worker ceiling). See "Performance decision" for the read-per-request vs
  nightly-index call.
- **Depends on**: none in flight. Reads `data/prediction_archive/valucast_prospect_rank_v1/*.json`
  (committed daily by the existing pipeline) and imports read-only constants from
  `prospects/buys.py`, `web/buy_score.py`, `web/public_snapshot_models.py`.
  Coordinates with nothing frozen (it *reads* the frozen `ahead_of_consensus.py`
  archive pattern as a reference; it does not import or edit it).
- **Category**: feature (product — new public read surface over existing archives).
- **Planned at**: 2026-07-11 (fill the baseline commit at execution).
- **Execution window**: **post-7/13** (repo-wide batch-3 convention — no new public
  surface lands before the 7/13 ledger-week unlock, even though this plan has no
  direct frozen-file dependency). When it runs, wire the route + reader LAST so a
  reader bug can never affect the existing board/pipeline.

## Why this matters

ValuCast's whole differentiator is receipts: dated, reproducible claims. Today a
reader can see *today's* board and a handful of *specific* ledgered calls, but has
no way to answer "what did ValuCast's board actually say on June 20?" — even though
we commit that exact board every single day to
`data/prediction_archive/valucast_prospect_rank_v1/2026-06-20.json`. eephus.io made
reconstructable historical board states a visible feature; we already do the hard
part (committing the daily snapshots) and expose none of it. The Time Machine turns
the archive we already keep into a self-serve audit surface: pick a date, see the
board as it stood, with the as-of date stated prominently and a link back to today.

The honesty bar is the same as everywhere on the site, with two hard edges baked in:

1. **Contaminated / non-comparable states are flagged, not hidden.** The board
   archive begins 2026-06-13; dates **before the 2026-06-22 role-normalization
   epoch** (`prospects.buys.PROSPECT_BUYS_EPOCH`) were scored on a pre-re-baseline
   scale and are NOT directly comparable to today's numbers. Those dates render a
   visible "pre-baseline" flag. A requested date with **no archive** (a future/too-
   early date, a gap day, or an unreadable file) renders an explicit **unavailable**
   state that lists the dates that DO exist — never a blank board, never a silent
   substitution of the nearest neighbor presented as the requested date.
2. **Consensus stays aggregate-only, historically too.** The ToS rule "aggregate
   median + board count ONLY, never per-source ranks" is not relaxed for past
   dates. The historical consensus column reuses the exact same filter/median/min-
   boards logic the live board uses (`_INTERNAL_SOURCES`, cap 600, min 2 boards)
   and surfaces only `~P#<median>` + `<N> boards`.

## Current state

Verified against the live files/archives on 2026-07-11. Read each cited line
yourself before building on it.

### The archive this reads is already committed daily — its shape is the raw rank_v1 board

- **Directory**: `data/prediction_archive/valucast_prospect_rank_v1/` — one JSON per
  day, filename = ISO date (`2026-06-20.json`). On 2026-07-11 there are **29 files,
  2026-06-13 → 2026-07-11, no missing calendar days**. Each file is ~7 MB. The
  daily pipeline commits a new one every morning (a `2026-07-11.json` already
  existed at plan time — same-day writer confirmed).
- **Top-level keys** of each archive: `board` (the list of rows), `candidate_count`,
  `date` (== the filename stem, an ISO date), `generated_at` (ISO timestamp),
  `rank_version` (e.g. `"0.2.8"`; the earliest file 6/13 is `"0.2.0"`),
  `ranked_count`, `validation`. **`date` and `rank_version` are the honesty-grammar
  fields** — surface the as-of date and the model version from the archive itself.
- **Each `board[i]` row** carries: `rank`, `name`, `role` (`"hitter"`/`"pitcher"`),
  `mlbam_id`, `mlb_team`, `level` (e.g. `"A+"`), `age`, `positions` (list), `score`
  (float, ~0–72 range — this is the ValuCast model score, NOT a dollar value),
  `score_source`, `confidence` (`"medium"` etc.), `eta`, `eta_window`,
  `dynasty_signal` (dict of probabilities), and **`context_only`** (a dict holding
  `source_ranks` (e.g. `{"fg_ord":15,"hkb":8,"pipeline":3,"pl":17,"sts":3}`), plus
  stat lines). **There is no `id`, no `value`/`value_scale`, no top-level `team`,
  and no top-level `source_ranks`** — the archive row is shaped like the RAW
  `valucast_prospect_rank_v1.json` model artifact, **not** like the live
  `PublicSnapshotRow`. This is why the live board template cannot be reused verbatim
  (next section).

### The LIVE board serves a DIFFERENT (curated) artifact via `dd_store` — do NOT try to reuse its template as-is

- The live prospect board is `mode=prospects` on `/` (`index()`, app.py:~4539) and
  `/rankings` (`rankings()`, app.py:4566), rendering
  `templates/partials/rankings_table_dynasty.html`. It reads through **`dd_store`**
  (a `PublicSnapshotStore` over the curated `data/public/public_dynasty_snapshot.json`,
  app.py:~605/759) and yields `PublicSnapshotRow` dataclass instances
  (`web/public_snapshot_models.py:61`).
- **The live row template depends on things the archive row does NOT have**:
  `templates/partials/rankings_table_dynasty.html` iterates `{% for row in dd_rows %}`
  (line 71) and references `row.id` (DOM key / compare checkbox / detail toggle),
  `row.value_for(_ap)` / `row.dynasty_value` (dollar-scaled value), `row.why_rank_chips`
  (line 110), `row.factual_context_stat_items` (line 140), `row.eta_display`
  (line 166), plus a dozen context maps keyed by `row.id` (`tiers`, `call_up_by_id`,
  `momentum_by_id`, `dyn_z_map`, `dynasty_dollars`, …) assembled by
  `_apply_prospect_board_context` (app.py:1361) / `_prospect_rows` (app.py:1094).
  **None of that context exists for a historical archive read**, and there is no
  single-row partial to reuse (the row markup is inline in the `{% for %}`).
  **Conclusion: the Time Machine renders its OWN thin template over a thin
  archive-row view — it does NOT reuse `rankings_table_dynasty.html` and does NOT
  construct `PublicSnapshotRow` objects.** Keep the historical row minimal (the
  fields the archive actually carries): rank, name, position(s), level, team, age,
  model score, confidence, ETA window, and the aggregate consensus.

### The archive-read pattern to mirror is the frozen `ahead_of_consensus.py` (READ-ONLY reference)

- `prospects/ahead_of_consensus.py` is **frozen (READ-ONLY until the ~7/13 unlock;
  never edit it)**, but it is the canonical example of reading this exact archive:
  `ARCHIVE_DIR = ROOT/"data"/"prediction_archive"/"valucast_prospect_rank_v1"`
  (line 30); `files = sorted(ARCHIVE_DIR.glob("*.json"))` ascending (line 207);
  `date = path.stem` (line 215); `board = (json.loads(path.read_text(...)) or {}).get("board") or []`
  with `except (OSError, ValueError): continue` (line 216-219). **Mirror this idiom
  in the new reader** (glob, stem-as-date, `.get("board")`, fail-soft) — do NOT
  import from the frozen module; re-implement the ~4-line pattern in the new reader
  so the frozen file is untouched. NOTE: `ahead_of_consensus.py` iterates ALL files
  (it computes a streak); the Time Machine instead resolves ONE date — so it does
  NOT need to read every file per request (see Performance).

### The consensus-median logic (aggregate-only, ToS-safe) — reuse the EXACT filter/median

- `web/public_snapshot_models.py` on `PublicSnapshotRow`:
  `public_source_ranks` (line 137-145) drops `_INTERNAL_SOURCES` (line 27) and any
  rank `> _CONSENSUS_RANK_CAP` (600, line 30); `public_source_consensus`
  (line 146-155) returns `None` when fewer than `_MIN_CONSENSUS_BOARDS` (2, line 34)
  boards remain, else the rounded median. The **identical** logic is also in the
  frozen `ahead_of_consensus.py:97-123` (`_public_source_ranks`,
  `_public_source_consensus`).
- **The archive row's per-source ranks live at `row["context_only"]["source_ranks"]`**
  (a plain dict), NOT at a top-level `source_ranks`. Feed THAT dict through the same
  filter+median. **Reuse strategy**: the cleanest non-frozen reuse is a small pure
  helper in the new reader that copies the ~15-line filter+median from
  `public_snapshot_models.py` (which is NOT frozen) — or, if the reviewer prefers,
  hoist `_INTERNAL_SOURCES`/`_CONSENSUS_RANK_CAP`/`_MIN_CONSENSUS_BOARDS` +
  `_public_source_consensus` into a tiny shared module both can import. **Do NOT
  edit the frozen `ahead_of_consensus.py` to share code.** Whatever the choice, the
  output is aggregate-only: `~P#<median>` + `<N> boards`, never the raw dict.
- **Live display grammar to match** (`templates/partials/player_detail_dynasty.html:536-544`):
  `~P#{{ consensus }}` + `{{ count }} boards`; a single board renders
  "1 board (not a consensus)". The same grammar recurs on `/gaps` and `/receipts`.
  The historical board follows it exactly.

### The per-date quality flags — reuse code-derived facts, NOT memory

Memory records "6/3-6/10 noisy, 5/31+6/10 contaminate trends (spike-revert
denylist, epoch-masked)". **That phrasing is imprecise; the code/data say
something more specific, which this plan encodes instead of hardcoding memory:**

- **There is NO literal date denylist in this repo.** The 6/2 + 6/10 masking that
  memory refers to happens **upstream in the DD repo** (`player_trends.py`,
  `_mask_rebaseline_steps`/`REBASELINE_DATES`, not checked out here) and survives
  only as *absent dates* in `data/dd/dd_dynasty_feed.json`'s `value_history`. **That
  masking is about the DD-fed sparkline, NOT about the `valucast_prospect_rank_v1`
  board archive** the Time Machine reads. The board archive is a separate,
  DD-independent, ValuCast-owned scored pipeline. So the DD 6/2/6/10 dates do
  **not** apply here directly.
- **The relevant contamination boundary for the BOARD archive is the epoch:**
  `prospects/buys.py:32` `PROSPECT_BUYS_EPOCH = "2026-06-22-role-normalization"`
  (date form `"2026-06-22"`, derived as `"-".join(PROSPECT_BUYS_EPOCH.split("-")[:3])`,
  exactly as `prospects/movers.py:23` and `scripts/build_public_dynasty_snapshot.py:45`
  do). Board archive dates **before 2026-06-22** (the 9 files 6/13–6/21) were scored
  on the pre-role-normalization scale — comparable *among themselves* but **not
  directly comparable to post-6/22 scores**. Those dates get a `"pre-baseline"`
  quality flag. **Import `PROSPECT_BUYS_EPOCH` from `prospects.buys` and derive the
  date the same way — do NOT hardcode "2026-06-22".**
- **Missing / unreadable dates** are derived empirically at load time, NOT from a
  list: for a requested date, if no archive file exists (future date, gap day, or a
  file that fails `json.loads`), the state is `"unavailable"`. (At plan time there
  are zero gap days in-range, but the flag system must handle future gaps and
  unreadable files — the fail-soft path is the same one `ahead_of_consensus.py`
  uses: `except (OSError, ValueError)`.)
- **The step/gap guard** (`web/buy_score.py:80-106` `clean_tail`, `STEP_THRESHOLD=6.0`,
  `MAX_POINT_GAP_DAYS=3`) is a trend-cleaning tool for value *history*, not a
  board-date flag — it is NOT needed for V1 (the Time Machine shows a single-date
  board snapshot, not a multi-date trend). Noted here only so the executor does not
  reach for it: V1's quality flags are `clean` (>= epoch), `pre-baseline` (< epoch),
  `unavailable` (no readable file).

### The fail-soft store precedent + the as-of grammar already exist

- **Fail-soft reader precedent**: `web/statcast_store.py:73-149` (`StatcastStore`,
  `_ensure_loaded` at 83-97, degrades to empty on `OSError`/`ValueError`) and its
  clone `web/pitch_discipline_store.py:46` (`_ensure_loaded` at 56-76, "modeled on
  StatcastStore"). **Model the new reader on these** — but note the difference: those
  read ONE fixed artifact once; the Time Machine reader takes a **date parameter**
  and reads a per-date file, so it caches per-date (bounded — see Performance) and
  also exposes an `available_dates()` method (glob the dir once, cache by dir mtime).
- **The generic cached loader** `_load_artifact(path)` (app.py:4778-4793) is
  mtime-keyed and fail-soft — usable directly for a single date's file if the reader
  is a plain function rather than a class. Either is fine; do NOT add a new caching
  mechanism.
- **As-of / freshness grammar**: `editorial_date()` (Jinja global; Python twin
  `_editorial_date` app.py:341-351) renders `"JUNE 20, 2026"`; the `freshness-badge`
  markup (`templates/index.html:21-28`) is the "Updated <date>" widget; the stale
  banner is `{% if snapshot_stale %}` (`templates/index.html:12-14` /
  `templates/partials/_stale_notice.html`). **For the Time Machine, do NOT reuse the
  `snapshot_stale` copy** ("today's refresh hasn't published yet") — that means a
  *late live refresh*, a different condition. A historical page is *intentionally*
  past: render a distinct "Board as of {{ editorial_date(date) }}" banner + a "View
  today's board" link. Reuse `editorial_date()` for the date rendering.

### No route collision

- `grep` for `/board`, `/timemachine`, `/time-machine`, `time_machine` in `app.py`
  returns nothing — the route path is free. Pick ONE canonical path (see Scope).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Reader unit tests | `python -m pytest -q tests/test_board_time_machine_store.py` | all pass |
| Quality-flag unit tests | `python -m pytest -q tests/test_board_time_machine_store.py -k "flag or quality or epoch or unavailable"` | all pass |
| Route/render tests | `python -m pytest -q tests/test_app.py -k "board_time_machine or timemachine or board_date"` | all pass |
| Reader returns a board for a known date | `python -c "import app; b=app.board_time_machine_store.board_for('2026-06-20'); print(bool(b), b.get('quality') if b else None, len(b.get('rows',[])) if b else 0)"` | `True`, a quality flag string, and a row count > 0 |
| Pre-epoch date is flagged | `python -c "import app; print(app.board_time_machine_store.board_for('2026-06-15')['quality'])"` | `pre-baseline` (or the plan's chosen label) |
| Unavailable date fails soft | `python -c "import app; print(app.board_time_machine_store.board_for('2026-01-01'))"` | `None` (or an explicit `{'quality':'unavailable', 'rows':[]}` — pick one, keep consistent) |
| Available dates listed | `python -c "import app; d=app.board_time_machine_store.available_dates(); print(len(d), d[0], d[-1])"` | count + earliest + latest ISO dates |
| Consensus is aggregate-only | `python -c "import app; b=app.board_time_machine_store.board_for('2026-07-08'); r=[x for x in b['rows'] if x.get('consensus')][0]; print(r['consensus'], 'source_ranks' not in r)"` | a `{median, board_count}`-shaped consensus and `True` (raw dict NOT exposed) |
| Page renders with as-of + link | `python -c "import app; c=app.app.test_client(); r=c.get('/board/2026-06-20'); print(r.status_code, b'as of' in r.data.lower() or b'June 20' in r.data, b'today' in r.data.lower())"` | `200 True True` |
| Unavailable page is honest | `python -c "import app; c=app.app.test_client(); r=c.get('/board/2026-01-01'); print(r.status_code, b'unavailable' in r.data.lower() or b'no board' in r.data.lower())"` | a 200 (or 404 — pick one) and the honest copy + the list of available dates |
| Network-free serving proof | `python -c "import web.board_time_machine_store as m, inspect; s=inspect.getsource(m); print(not any(t in s for t in ('urllib','requests','http.client','socket')))"` | `True` |
| No per-source leak in rendered HTML | `python -c "import app; c=app.app.test_client(); h=c.get('/board/2026-07-08').data.decode(); print('fg_ord' not in h and 'hkb' not in h and 'pipeline' not in h.lower().replace('pipeline 100',''))"` | `True` (individual board NAMES never rendered) |
| Frozen files untouched | `git diff --stat prospects/ahead_of_consensus.py scripts/build_ahead_of_consensus_scorecard.py` | empty |
| Full suite (final gate) | `python -m pytest -q` | pass count at/above the pre-change baseline, 0 fail; then restore the byproduct (below) |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | file back to HEAD (pytest dirties it — NEVER commit it) |

> Adjust the exact date strings above at execution to dates that exist in the
> archive at that time (the archive grows daily; `2026-06-15`/`2026-06-20`/`2026-07-08`
> are illustrative and were present at plan time).

## Scope

**In scope** (the only files you create or modify):

- **NEW `web/board_time_machine_store.py`** — the fail-soft reader (model on
  `StatcastStore`/`PitchDisciplineStore`). Public surface:
  - `available_dates() -> list[str]` — sorted ISO dates that have a readable archive
    file (glob `ARCHIVE_DIR/*.json`, cache by directory mtime; NEVER load the files
    just to list them — stat/stem only).
  - `board_for(date: str) -> dict | None` — for one ISO date, read that single
    archive file, build the thin card-ready view:
    `{"date","generated_at","rank_version","quality","rows":[...],"available_dates_hint":...}`.
    Each row is the minimal archive-derived view:
    `{"rank","name","role","team"(<-mlb_team),"level","age","positions","score",
    "confidence","eta_window","consensus":{"median","board_count"} | None}`.
    Fail-soft: unreadable/missing file → `None` (or the explicit unavailable dict —
    pick one, keep consistent with the route). NO network, NO per-source ranks
    exposed.
  - `quality_flag(date: str) -> str` — pure: `"unavailable"` if no readable file,
    `"pre-baseline"` if `date < EPOCH_DATE`, else `"clean"`. `EPOCH_DATE` derived
    from `prospects.buys.PROSPECT_BUYS_EPOCH` (imported), never hardcoded.
  - A pure `_consensus(source_ranks: dict) -> dict | None` helper that applies the
    exact `_INTERNAL_SOURCES` / cap-600 / min-2-boards median (copied from
    `web/public_snapshot_models.py`, NOT the frozen module) and returns
    `{"median":int,"board_count":int}` or `None`. **Never returns the raw dict.**
  - Optional `_row_limit` (default e.g. 300, matching the live board's top-slice)
    so a 2800-row board doesn't render 2800 `<tr>`s — bound the rendered rows.
- **`app.py`** — (i) instantiate `board_time_machine_store = BoardTimeMachineStore()`
  at module load (next to `statcast = StatcastStore()`, app.py:410, and
  `pitch_discipline_store` at 414); (ii) ONE new route (pick the canonical path
  below) that resolves the date param, calls the reader, and renders the new
  template. No cache/scoring/PNG/`dd_store` region touched.
- **NEW `templates/board_time_machine.html`** (full page; may `{% extends %}` the
  site base if there is one, else mirror another standalone page like
  `templates/track_record.html`). Renders: a prominent **as-of banner**
  ("Board as of {{ editorial_date(date) }}" + the `rank_version` + a "View today's
  board" link to `/`); the **quality notice** when `quality != "clean"`
  (pre-baseline: "scored before the 6/22 re-baseline — not directly comparable to
  today's scale"); a **date picker / available-dates control** (a plain `<select>`
  or `<input type=date min=... max=...>` of `available_dates()` — server-rendered,
  no JS framework); and the **thin board table** (rank / name / pos / level / team /
  age / score / confidence / ETA / consensus). The **unavailable state** lists the
  available date range and links to the nearest available date and to today. Obeys
  the aggregate-only consensus rule.
- **`templates/methodology.html`** — a short anchored section (e.g.
  `id="board-time-machine"`) stating: these are the exact daily board snapshots we
  commit; the as-of date is the snapshot date; pre-6/22 dates predate the
  role-normalization re-baseline and are not directly comparable to current scores;
  consensus shown is aggregate median + board count only. The page's quality-notice
  and/or footer links here.
- **NEW tests**: `tests/test_board_time_machine_store.py` (reader fail-soft, quality
  flags, aggregate-only consensus, available-dates, row bound) and additions to
  `tests/test_app.py` (route renders as-of + today link; unavailable is honest;
  network-free structural; no per-source leak in HTML). Use a small **fixture
  archive dir** (tmp dir with 2–3 tiny hand-built board JSONs spanning the epoch)
  so tests do not depend on the real ~7 MB files or their drifting dates.

**Performance decision (state it, then implement one):**

- **DEFAULT (recommended for V1): read-per-request with mtime caching.** One archive
  file is ~7 MB; parsing one on demand and slicing to `_row_limit` rows is well
  under the Render ~30s ceiling. Cache the parsed board per-date keyed on file
  mtime (like `_load_artifact`), and **bound the cache** to the last ~K distinct
  dates requested (an `OrderedDict`/LRU of small size, e.g. 8) so a crawler hitting
  every date can't pin ~29×7 MB in each of 2 workers. `available_dates()` caches on
  directory mtime (cheap — stat only). **Never load all dates in one request.**
- **ALTERNATIVE (only if the reviewer wants zero per-request parse cost): a nightly
  compact index.** A build step could pre-extract a slim per-date board
  (rank/name/score/level/team/age/consensus, top-N) into ONE small
  `data/models/valucast_board_time_machine_index.json`, wired into the daily build +
  the YAML `git add` block (the plan-023 pattern). This trades a new committed
  artifact + a daily-build step for O(1) reads. **Do NOT build this for V1 unless
  the measured read-per-request latency is a problem** — it adds a build step, a
  committed artifact, and the size-growth question, for a page that will get modest
  traffic. Record the decision in the status row.

**Cut line to hold Effort (the reviewer decides at planning time):**

- **CORE (must ship)**: the reader (`board_for`/`available_dates`/`quality_flag`),
  the route, the thin table (rank/name/pos/level/team/age/score/confidence/ETA), the
  **as-of banner + today link**, the **quality notice** (pre-baseline / unavailable),
  the date picker, methodology note, tests. This is the product and the honesty.
- **CUT-CANDIDATE (to hold S): the per-row aggregate consensus column.** If the day
  runs long, ship the board WITHOUT the consensus column (the `_consensus` helper +
  its template column) and file it as a one-step fast-follow — the core board +
  quality flags stand alone. **If you DO ship it, aggregate-only is mandatory, not
  optional.**
- **Never cut**: the quality flags / as-of disclosure / unavailable-fail-soft / the
  aggregate-only consensus rule *if the consensus column ships*. Those are the
  reasons the feature is honest.

**Out of scope** (do NOT touch):

- **The frozen files** — `prospects/ahead_of_consensus.py`,
  `scripts/build_ahead_of_consensus_scorecard.py` (pre-registered AOTC scoring,
  ~7/13 unlock). READ them as reference for the archive pattern; NEVER edit or
  import from them.
- **The live board / `dd_store` / `PublicSnapshotStore` / `rankings_table_dynasty.html`
  / `_apply_prospect_board_context` / `_prospect_rows`** — the Time Machine is a
  SEPARATE surface reading the archive. Do NOT modify the live board path, do NOT
  construct `PublicSnapshotRow` objects for it, do NOT reuse the live row template.
- **PNG / share cards / `_PNG_CACHE_PARAMS`** — V1 adds NO new PNG and NO new
  share-card query param (the historical page is not param-driven by a share card).
  A `/board/<date>.png` share card is a natural fast-follow, but it is explicitly
  out of V1 **because** any new share-card query param must be added to the
  `_PNG_CACHE_PARAMS` allowlist (app.py:154, plan 007's invariant) — that surface
  stays untouched here. (See Non-goals.)
- **Per-source board ranks — ever, including historically.** Aggregate median +
  board count only.
- **The value/scoring/ranking math** — display-only replay of a committed artifact;
  NEVER a value input, and this plan computes no new score (it renders the archived
  `score` verbatim).
- **The DD feed / `data/dd/*` / the DD-side 6/2+6/10 masking** — irrelevant to the
  board archive; do not read `data/dd/*` and do not try to import a DD denylist
  (there is none in this repo).
- **Value-history / trends / sparklines** — V1 is a single-date board *state*, not a
  per-player trend line. The `clean_tail` step/gap guard and the epoch step-masking
  are NOT invoked (see "per-date quality flags" note). A "diff two dates" or
  "player's rank over time" view is a fast-follow, not V1.
- **A new build script or committed data artifact** — V1 reads the already-committed
  archives (unless the reviewer opts into the nightly-index alternative above, which
  is the only path that adds an artifact + build step).

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**:
  master auto-deploys valucast.app via Render. Commit locally; the reviewer gates
  the push.
- NEVER `git add -A` or `commit -am` (repo guardrail). Stage each in-scope file
  explicitly by path. **Never `git stash`.**
- Do NOT stage `data/prediction_archive/.../2026-06-15.json` (pytest byproduct — the
  tests dirty it; restore via `git checkout --`) or any untracked `data/dd/*` or
  `data/snapshots/<today>.json`.
- This plan writes **no new committed data artifact** in the default (read-per-
  request) path — only source files + templates + tests get staged. (If the reviewer
  opts into the nightly-index alternative, THEN the index artifact + the YAML
  `git add` line get staged, plan-023 style.)
- Commit message style (short imperative subject), e.g.
  `Add board Time Machine: public /board/<date> historical board replay from committed rank_v1 archives, with per-date quality flags`.

## Steps

### Step 0: Confirm the reuse surfaces + archive are live before building

```
# The archive dir exists with dated files:
python -c "import glob,os; f=sorted(glob.glob('data/prediction_archive/valucast_prospect_rank_v1/*.json')); print(len(f), os.path.basename(f[0]), os.path.basename(f[-1]))"
# expect: a count (>=29) and an ISO-date range e.g. 2026-06-13.json ... today.json
# A board row has the expected raw shape (score, mlb_team, context_only.source_ranks; NO id/value/team):
python -c "import json,glob; d=json.load(open(sorted(glob.glob('data/prediction_archive/valucast_prospect_rank_v1/*.json'))[-1])); r=d['board'][0]; print('score' in r, 'mlb_team' in r, 'source_ranks' in (r.get('context_only') or {}), 'id' not in r, 'value' not in r)"
# expect: True True True True True
# The epoch constant is importable + its date form:
python -c "from prospects.buys import PROSPECT_BUYS_EPOCH as E; print(E, '-'.join(E.split('-')[:3]))"
# expect: 2026-06-22-role-normalization 2026-06-22
# The consensus-median logic exists to copy (non-frozen):
python -c "from web.public_snapshot_models import PublicSnapshotRow; print(hasattr(PublicSnapshotRow,'public_source_consensus'))"
# expect: True
# The fail-soft store precedent exists:
python -c "from web.statcast_store import StatcastStore; print(hasattr(StatcastStore(),'display_groups'))"
# expect: True
# Route path is free + no reader exists yet:
python -c "import importlib.util as u; print(u.find_spec('web.board_time_machine_store'))"   # expect: None
grep -rn "board_time_machine\|/board/\|/timemachine" app.py || echo "no collision"
```
**Verify**: all confirm the state above. If `web.board_time_machine_store` already
exists or a `/board/<date>` route is already wired, someone landed here first —
STOP and reconcile. If the board-row shape check returns any `False` (the raw
archive schema drifted), re-read a live archive file before building the reader on
a guess — STOP-and-reconcile.

### Step 1: The fail-soft reader `web/board_time_machine_store.py`

Model on `StatcastStore` / `PitchDisciplineStore`, but date-parameterized. NO
network, NO write I/O. Sketch:

```python
"""Public board Time Machine: read the committed daily rank_v1 board archive and
render any past date's board state. Fail-soft, network-free (reads committed JSON
only — the StatcastStore precedent). Display-only replay of an archived artifact:
NEVER a value input, computes no new score. Consensus is aggregate median + board
count ONLY (ToS — no per-source ranks, historically or otherwise)."""
from __future__ import annotations
import json
from collections import OrderedDict
from pathlib import Path

from prospects.buys import PROSPECT_BUYS_EPOCH  # read-only import (not frozen)

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"
EPOCH_DATE = "-".join(PROSPECT_BUYS_EPOCH.split("-")[:3])   # "2026-06-22"

# Consensus filter — copied from web/public_snapshot_models.py (NOT the frozen
# ahead_of_consensus.py). Keep in sync with that file; aggregate-only.
_INTERNAL_SOURCES = frozenset({"milb_perf", "milb_breakout", "cfr", "cfr_raw"})
_CONSENSUS_RANK_CAP = 600
_MIN_CONSENSUS_BOARDS = 2
_ROW_LIMIT = 300
_CACHE_MAX = 8   # bound the per-date parsed-board cache (2 workers × 8 × ~board)


def _consensus(source_ranks: dict | None) -> dict | None:
    ranks = sorted(
        r for s, r in (source_ranks or {}).items()
        if s not in _INTERNAL_SOURCES and isinstance(r, (int, float)) and r <= _CONSENSUS_RANK_CAP
    )
    if len(ranks) < _MIN_CONSENSUS_BOARDS:
        return None
    mid = len(ranks) // 2
    median = ranks[mid] if len(ranks) % 2 else (ranks[mid - 1] + ranks[mid]) / 2
    return {"median": round(median), "board_count": len(ranks)}


class BoardTimeMachineStore:
    def __init__(self, archive_dir: Path = ARCHIVE_DIR):
        self._dir = archive_dir
        self._dates_cache: tuple[float, list[str]] | None = None      # (dir mtime, dates)
        self._board_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()

    def available_dates(self) -> list[str]:
        try:
            m = self._dir.stat().st_mtime
        except OSError:
            return []
        if self._dates_cache and self._dates_cache[0] == m:
            return self._dates_cache[1]
        dates = sorted(p.stem for p in self._dir.glob("*.json"))
        self._dates_cache = (m, dates)
        return dates

    def quality_flag(self, date: str) -> str:
        path = self._dir / f"{date}.json"
        try:
            if not path.exists():
                return "unavailable"
        except OSError:
            return "unavailable"
        return "pre-baseline" if date < EPOCH_DATE else "clean"

    def board_for(self, date: str) -> dict | None:
        path = self._dir / f"{date}.json"
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return None                          # unavailable -> fail soft
        cached = self._board_cache.get(date)
        if cached and cached[0] == stamp:
            self._board_cache.move_to_end(date)
            return cached[1]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None                          # unreadable -> fail soft (like ahead_of_consensus)
        board = (payload or {}).get("board") or []
        rows = []
        for r in board[:_ROW_LIMIT]:
            if not isinstance(r, dict):
                continue
            src = (r.get("context_only") or {}).get("source_ranks")
            rows.append({
                "rank": r.get("rank"), "name": r.get("name"), "role": r.get("role"),
                "team": r.get("mlb_team"), "level": r.get("level"), "age": r.get("age"),
                "positions": r.get("positions") or [], "score": r.get("score"),
                "confidence": r.get("confidence"), "eta_window": r.get("eta_window"),
                "consensus": _consensus(src),      # aggregate-only or None; raw dict NEVER kept
            })
        view = {
            "date": payload.get("date") or date,
            "generated_at": payload.get("generated_at"),
            "rank_version": payload.get("rank_version"),
            "quality": "pre-baseline" if date < EPOCH_DATE else "clean",
            "rows": rows,
        }
        self._board_cache[date] = (stamp, view)
        self._board_cache.move_to_end(date)
        while len(self._board_cache) > _CACHE_MAX:
            self._board_cache.popitem(last=False)
        return view
```

**Verify**:
- `python -c "from web.board_time_machine_store import BoardTimeMachineStore as S; s=S(); ds=s.available_dates(); print(len(ds)>0, s.board_for(ds[-1]) is not None, s.board_for('1999-01-01') is None)"` → `True True True`.
- `python -c "from web.board_time_machine_store import _consensus; print(_consensus({'fg_ord':15,'hkb':8,'pipeline':3,'pl':17,'sts':3}), _consensus({'pl':17}))"` → an aggregate `{median,board_count}` (5 boards) and `None` (single board).
- A pre-epoch date's `board_for(...)['quality'] == 'pre-baseline'`; a post-epoch date → `'clean'`.

### Step 2: Instantiate the store + add the route in app.py

**2a — Instantiate** next to the other stores (app.py ~410-418):
```python
board_time_machine_store = BoardTimeMachineStore()
```

**2b — Route.** Pick ONE canonical path — recommended **`/board/<date>`** (clean,
shareable, one URL per date) with a **`/board`** (no date) landing that redirects
to the latest available date or shows the picker. Sketch:
```python
@app.route("/board")
@app.route("/board/<date>")
def board_time_machine(date=None):
    dates = board_time_machine_store.available_dates()
    if not dates:
        return render_template("board_time_machine.html", unavailable=True,
                               available_dates=[], date=None), 200
    if date is None:
        date = dates[-1]                       # /board -> latest
    # validate shape (ISO date) cheaply; do NOT trust arbitrary path input
    board = board_time_machine_store.board_for(date)
    if board is None:
        return render_template("board_time_machine.html", unavailable=True,
                               requested=date, available_dates=dates,
                               nearest=_nearest_available(date, dates), date=date), 200
    return render_template("board_time_machine.html", board=board, date=date,
                           quality=board["quality"], available_dates=dates)
```
- **Guard the `<date>` param**: accept only an ISO `YYYY-MM-DD` shape (regex or
  `datetime.date.fromisoformat` in a try) so a junk path is treated as unavailable,
  not an exception. Do NOT build the file path from unsanitized input beyond the
  `ARCHIVE_DIR / f"{date}.json"` join (the reader already constrains it; still
  reject a `date` containing `/`, `\`, or `..` — path-traversal belt).
- Decide 200-with-honest-body vs 404 for unavailable; **200 with the available-date
  list is friendlier** (the reader for an audit surface should teach the visitor
  which dates exist). Keep it consistent with the test.
- Do NOT touch `dd_store`, the PNG region, or `_PNG_CACHE_PARAMS`.

**Verify**:
- `python -c "import app; c=app.app.test_client(); print(c.get('/board').status_code, c.get('/board/2026-06-20').status_code, c.get('/board/not-a-date').status_code)"` → three `200`s (or your chosen unavailable code), no traceback.

### Step 3: The template `templates/board_time_machine.html`

Server-rendered, no JS framework. Sections:
1. **As-of banner (prominent)**: "Board as of {{ editorial_date(date) }}" +
   "· model {{ board.rank_version }}" + a **"View today's board" link to `/`**.
   Reuse `editorial_date()`. Do NOT reuse the `snapshot_stale` copy.
2. **Quality notice** when `quality != "clean"`: pre-baseline →
   "This board predates the June 22 role-normalization re-baseline — scores are on
   an older scale and are not directly comparable to today's." Link to
   `/methodology#board-time-machine`.
3. **Date control**: a server-rendered `<select>` (or `<input type="date"
   min="{{ available_dates[0] }}" max="{{ available_dates[-1] }}">`) of
   `available_dates`, each option a link/submit to `/board/<that-date>`. No client
   framework; a plain form GET is fine.
4. **Board table**: rank / name / position(s) / level / team / age / score /
   confidence / ETA window / **consensus** (`~P#{{ row.consensus.median }}` +
   "{{ row.consensus.board_count }} boards" when present; otherwise blank or a "—").
   **Never render per-source board names** — only the aggregate. Cap at the reader's
   `_ROW_LIMIT`.
5. **Unavailable state** (`{% if unavailable %}`): "No board was published for
   {{ requested }}." + "ValuCast's archive runs {{ available_dates[0] }} →
   {{ available_dates[-1] }}." + a link to `nearest` and to today. NEVER a blank
   board.

**Verify**:
- `python -c "import jinja2; jinja2.Environment(loader=jinja2.FileSystemLoader('templates')).get_template('board_time_machine.html')"` → no exception.
- `/board/<pre-epoch date>` HTML contains the pre-baseline notice + the methodology
  link; `/board/<clean date>` does not.
- `/board/<clean date>` HTML contains `~P#` and "boards" for at least one row and
  contains NONE of the raw source names (`fg_ord`, `hkb`, `pipeline`, `sts`, `pl`).

### Step 4: Methodology section

In `templates/methodology.html`, add an anchored section
(`id="board-time-machine"`) stating plainly:
1. These are the **exact daily board snapshots** ValuCast commits — the page is a
   replay of a committed artifact, not a reconstruction.
2. The **as-of date** is the snapshot date; the archive currently runs from its
   first committed day to today.
3. **Pre-June-22 dates** predate the role-normalization re-baseline and are on an
   older score scale — comparable among themselves, not directly to current numbers.
4. **Consensus** shown is the aggregate median + board count across external boards
   (min 2 boards) — never individual board ranks (the same rule as the live board).

Match the methodology page's existing section grammar. The page's quality-notice
links here.

**Verify**:
- `python -c "import app; c=app.app.test_client(); h=c.get('/methodology').data.decode(); print('board-time-machine' in h and 're-baseline' in h.lower())"` → `True`.

### Step 5: Tests

Build a **fixture archive dir** (a tmp dir with 2–3 tiny hand-authored board JSONs —
one pre-epoch date e.g. `2026-06-15.json`, one post-epoch e.g. `2026-06-25.json`,
each with 2–3 rows carrying `score`/`mlb_team`/`context_only.source_ranks`, plus one
deliberately malformed file to prove fail-soft). Point a `BoardTimeMachineStore(fixture_dir)`
at it. Do NOT depend on the real ~7 MB files or their drifting dates.

- `tests/test_board_time_machine_store.py`:
  1. **available_dates**: returns the fixture dates sorted; caches on dir mtime.
  2. **quality flags**: pre-epoch date → `"pre-baseline"`; post-epoch → `"clean"`;
     absent date → `"unavailable"`; `EPOCH_DATE` derived from the imported constant
     (assert it equals `"2026-06-22"` via the split, not a hardcode).
  3. **board_for happy path**: returns the thin view with `date`/`rank_version`/
     `quality`/`rows`; each row has the expected keys and NO `source_ranks` key.
  4. **aggregate-only consensus**: `_consensus` with 5 boards → a `{median,board_count}`;
     with 1 board → `None`; the raw dict is never present on a row.
  5. **fail-soft**: missing file → `None`; malformed JSON file → `None` (no
     exception).
  6. **row bound**: a fixture board with > `_ROW_LIMIT` rows renders exactly
     `_ROW_LIMIT`.
  7. **network-free (structural)**: the module source imports no
     `urllib`/`requests`/`http.client`/`socket`.
- `tests/test_app.py` additions:
  1. **route renders as-of + today link**: `GET /board/<clean fixture-ish date>` →
     200, HTML has the as-of date and a link to `/`. (Use monkeypatch to point the
     app's store at the fixture dir, or assert against a real archive date that
     exists at test time — prefer the monkeypatch so the test is date-stable.)
  2. **pre-baseline notice**: a pre-epoch date renders the notice; a clean date does
     not.
  3. **unavailable is honest**: a nonexistent date → the honest body listing the
     available range, never a blank board.
  4. **no per-source leak**: rendered HTML for a clean date contains none of the raw
     board names.
  5. **path-traversal belt**: `GET /board/..%2f..%2fetc` (and a `date` with `/`) does
     NOT 500 and does NOT read outside `ARCHIVE_DIR`.

**Verify**: `python -m pytest -q tests/test_board_time_machine_store.py tests/test_app.py -k "board"` → all pass.

### Step 6: Full suite + restore the byproduct

```
python -m pytest -q
git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json
git status --short
git diff --stat prospects/ahead_of_consensus.py scripts/build_ahead_of_consensus_scorecard.py
```
**Verify**: full suite green (pre-change baseline + the new assertions); the frozen
files show an EMPTY diff; `git status` shows ONLY in-scope files (the new reader,
the template, the app route/instantiation, the methodology edit, the tests) — no
`data/dd/*`, no `data/snapshots/<today>.json`, and the archive byproduct restored.
No new committed data artifact (default path).

## Test plan

Summarized in Step 5. The load-bearing assertions:
- **Quality flags are code-derived**: the epoch boundary comes from the imported
  `PROSPECT_BUYS_EPOCH`, not a hardcoded string; a date exactly at the epoch is
  `"clean"` (>= boundary), the day before is `"pre-baseline"`.
- **Aggregate-only consensus, historically**: a row's consensus is `{median,
  board_count}` or `None`; the raw `source_ranks` dict is never on the row and never
  in the HTML.
- **Fail-soft everywhere**: missing file, malformed JSON, junk/path-traversal date,
  and empty archive dir all degrade to an honest state, never a 500.
- **Network-free**: structural import check on the reader.
- **Date-stable tests**: use a fixture archive dir (not the real drifting files) so
  the suite doesn't break as the archive grows or the earliest date ages out.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (pre-change baseline + new assertions); the
      byproduct file restored after.
- [ ] `web/board_time_machine_store.py` is network-free (structural test), reads
      ONE archive file per requested date, caches per-date on mtime with a bounded
      LRU, and fails soft (missing/malformed/junk → `None`/unavailable, never an
      exception).
- [ ] Per-date **quality flag** is derived from the imported `PROSPECT_BUYS_EPOCH`
      (pre-baseline < 2026-06-22, else clean; no readable file → unavailable) — NOT
      hardcoded from memory.
- [ ] The page states its **as-of date prominently**, shows the archive's
      **`rank_version`**, links **today's board**, and renders a **quality notice**
      on pre-baseline / unavailable states.
- [ ] The **unavailable** state lists the available date range + a nearest-date link
      — never a blank board, never a silent nearest-neighbor substitution presented
      as the requested date.
- [ ] Historical **consensus is aggregate median + board count ONLY** — no
      per-source board names in the reader output or the rendered HTML (verified).
- [ ] Serving is **network-free** and adds **no new build step / no new committed
      artifact** (default read-per-request path). (If the nightly-index alternative
      was chosen, the artifact is in the YAML `git add` block and the build step is
      wired LAST.)
- [ ] **No new PNG / no new `_PNG_CACHE_PARAMS` param**; `dd_store` / the live board
      path untouched.
- [ ] `prospects/ahead_of_consensus.py` and
      `scripts/build_ahead_of_consensus_scorecard.py` untouched (`git diff --stat`
      empty for them).
- [ ] The methodology section explains the snapshot-replay nature, the pre-6/22
      comparability caveat, and the aggregate-only consensus rule.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- **A pre-epoch (< 2026-06-22) board would render WITHOUT the pre-baseline notice** —
  that presents a non-comparable score scale as current. Add the notice or do not
  ship that date.
- **A requested date with no readable archive would render a blank board, or would
  silently serve the nearest neighbor presented AS the requested date** — the
  unavailable state must be explicit and must list the real available dates. STOP.
- **Any per-source board rank / board name would reach the reader output or the HTML**
  (historically or otherwise) — aggregate median + board count only. STOP.
- **The `<date>` path param reaches the filesystem unsanitized** (a `date` with `/`,
  `\`, or `..` builds a path outside `ARCHIVE_DIR`) — reject non-ISO shapes before
  the file join. STOP-and-fix.
- **The reader loads ALL archive dates in one request, or an unbounded number of
  ~7 MB boards accumulate in the cache** (a crawler pins memory across the 2
  workers) — bound the per-date cache and never glob-load the file bodies to list
  dates. STOP.
- **The epoch date is being hardcoded** (`"2026-06-22"` typed as a literal) instead
  of derived from `prospects.buys.PROSPECT_BUYS_EPOCH` — a future re-baseline would
  silently drift. STOP and import the constant.
- **The plan is about to edit or import from `prospects/ahead_of_consensus.py`** to
  share code — it is frozen. Re-implement the ~4-line archive-read idiom / copy the
  ~15-line consensus median from the NON-frozen `web/public_snapshot_models.py`
  instead. STOP.
- **The raw archive schema changed** (a board row no longer carries `score` /
  `mlb_team` / `context_only.source_ranks`, or the top-level `date` / `board` keys
  moved) — re-verify against a live archive file before building the reader on a
  guess. STOP-and-reconcile.
- **Effort is clearly exceeding the S–M window** — invoke the cut line: drop the
  per-row consensus column (the `_consensus` helper + its template column) FIRST,
  then defer any polish, before cutting the quality flags / as-of disclosure /
  unavailable fail-soft (never cut those). Report what was cut.

## Non-goals (V1)

- **No PNG share card / no new share-card query param.** The historical page renders
  in HTML only; a `/board/<date>.png` is a fast-follow and would reopen the
  `_PNG_CACHE_PARAMS` surface (plan 007's invariant) — explicitly deferred.
- **No date-diff / "board changed between X and Y" view, and no per-player
  rank-over-time trend.** V1 is a single-date board *state*. A diff/trend view is a
  natural fast-follow (and would then engage the `clean_tail`/epoch step-masking that
  V1 deliberately does not touch).
- **No reconstruction of dates before the archive begins.** ValuCast only commits
  from its archive start; the page is honest that older dates do not exist (unlike
  eephus's back-to-2018 reconstruction, we replay only what we committed).
- **No live-board changes.** The Time Machine never modifies the current board path,
  its store, or its template.
- **No new build step / committed artifact** in the default path — reads the
  already-committed archives.
- **No per-source board ranks** — aggregate only, historically and always.

## Rollout order

1. **Reader + fixture-based unit tests** (`web/board_time_machine_store.py`,
   `tests/test_board_time_machine_store.py`) — the fail-soft contract, quality flags,
   and aggregate-only consensus, fully unit-tested before any route.
2. **Route + app instantiation** (app.py) — one route, guarded date param,
   200-with-honest-body for unavailable.
3. **Template** (`templates/board_time_machine.html`) — as-of banner + today link +
   quality notice + date picker + thin table (+ consensus column unless cut).
4. **Methodology** section.
5. **App/route tests** (`tests/test_app.py`) LAST — render, pre-baseline notice,
   unavailable honesty, no per-source leak, path-traversal belt.

Wire the route + reader so nothing touches the live board or the daily pipeline — a
reader bug can only ever break `/board/<date>`, never the existing board.

## Risks

- **Contamination mislabeled or hidden.** The single biggest trust risk is serving a
  pre-6/22 board *as if* its scores were on today's scale. The imported-epoch quality
  flag + the mandatory pre-baseline notice are the defense; the STOP condition
  enforces it. The empirical missing-date derivation (not a hardcoded list) means a
  future gap day is disclosed as unavailable automatically.
- **ToS leak of per-source ranks.** The archive row carries the raw `source_ranks`
  dict; the reader must reduce it to aggregate median + count and never pass the raw
  dict to the template. The `_consensus` helper + the "no per-source name in HTML"
  test are the defense.
- **Memory rot: the plan reflects code/data, not the CLAUDE.md memory.** Memory said
  "6/3-6/10 noisy, clean since ~6/11, spike-revert denylist" — the code/data say the
  board archive is a separate DD-independent pipeline starting 6/13, and the real
  comparability boundary is the 6/22 role-normalization epoch (importable constant),
  with the DD-side 6/2/6/10 masking irrelevant to this archive. The plan encodes the
  code-derived facts; if a future reader trusts memory over the constant, the epoch
  import + its test are the guardrail.
- **Performance / memory under a crawler.** ~29 (growing) × ~7 MB files. Read-per-
  request with an mtime-keyed, LRU-bounded per-date cache keeps any single request to
  one parse and caps resident memory; `available_dates()` never loads file bodies.
  The nightly-index alternative exists if measured latency ever bites, but is not V1.
- **Archive schema drift.** The reader depends on `board[i]` carrying `score` /
  `mlb_team` / `positions` / `context_only.source_ranks` and the top-level `date` /
  `rank_version`. Step 0's shape check + the STOP condition catch a drift before it
  ships a wrong board.
- **Route-input abuse.** An arbitrary `<date>` path segment must be shape-validated
  (ISO only) and never build a path outside `ARCHIVE_DIR`; the path-traversal belt +
  its test are the defense.

## Maintenance notes

- **The epoch is the comparability contract.** `PROSPECT_BUYS_EPOCH` (currently
  `2026-06-22-role-normalization`) is the boundary between pre-baseline and clean
  board dates. If a future re-baseline moves it, the flag follows automatically
  **because the plan imports the constant** — never hardcode the date. If a *second*
  re-baseline epoch is ever added, the quality flag may need to distinguish more than
  two eras; extend `quality_flag` then, keeping it code-derived.
- **Aggregate-only is permanent.** The historical consensus obeys the same ToS rule
  as the live board — median + board count, never per-source. Any future "richer
  historical consensus" idea is still bounded by that rule.
- **Replay, not reconstruction.** The page renders exactly what was committed on that
  date (`score`, `rank`, etc. verbatim) — it computes no new number and is never a
  value input. If a later plan wants a *derived* historical metric (a diff, a trend),
  that is a new surface with its own honesty gate, not a quiet addition here.
- **The archive is the source of truth and it grows daily.** The reader lists dates
  from the directory (mtime-cached) so new days appear automatically; tests use a
  fixture dir so they stay date-stable. If the retention decision (plans/README
  batch-2 note, plan 009 post-7/13) ever prunes old archive files, the Time Machine's
  earliest available date moves forward automatically and the unavailable state stays
  honest — no code change needed.
- **Frozen-file discipline.** The archive-read idiom and the consensus median were
  *copied* from non-frozen sources (`web/public_snapshot_models.py`) or re-implemented
  from the frozen `ahead_of_consensus.py` reference — never imported from the frozen
  module. If the frozen files unlock (~7/13) and a shared archive/consensus helper is
  later extracted, the Time Machine can migrate to it, but that is a follow-up, not a
  reason to edit the frozen files now.
