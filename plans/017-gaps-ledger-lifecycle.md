# Plan 017: Gaps → ledger claim lifecycle — kill the survivorship bias with an append-only, two-sided claims ledger

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **EXECUTION WINDOW: post-2026-07-13.** This plan is additive to the
> ahead-of-consensus machinery whose scoring RULES are frozen (pre-registered
> 7/2) until the ~7/13 gate unlock. It touches ZERO frozen scoring code (see
> Scope), but it publishes a parallel accountability surface derived from the
> same inputs; do not land it before the AOTC gate unlocks and the frozen
> scorecard is confirmed intact.
>
> **Drift check (run first)**:
> `git diff --stat fb360066..HEAD -- prospects/consensus_gap.py prospects/ahead_of_consensus.py prospects/call_up_receipts.py scripts/run_daily_public_build.py scripts/validate_public_data_freshness.py app.py templates/gaps.html`
> If any in-scope file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch with
> the excerpts, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (new committed artifact + new daily build step + new public strip; append-only history is the load-bearing invariant)
- **Depends on**: plan 004 (adds `VALUCAST_CONSENSUS_GAP` to the freshness gate — coordinate the constant; see Scope). Not blocked by it, but if both land, they share `scripts/validate_public_data_freshness.py`.
- **Category**: feature (accountability) + honesty
- **Planned at**: commit `fb360066`, 2026-07-09
- **Execution window**: post-2026-07-13

## Why this matters

The `/gaps` board and the AOTC ledger score **arrival, not outcome**, and the trigger that resolves a call — the player being called up — is exactly the event that creates survivorship bias. A bullish over-rank that the field never catches up to and that never gets called up is **invisible**: it just sits on the board, or silently ages off, and never becomes a receipt or a miss. The receipts seed lane can only ever *add hits* (`call_up_receipts.py:_seed_receipts`), and lead time is unweighted — a 2-day-early flag scores identically to a 30-day-early one.

Two structural holes make this concrete in the live code:

1. **The fade side is entirely unaccountable.** `prospects/consensus_gap.py` publishes a `lower` (fade) list — prospects the field ranks prominently that ValuCast ranks far lower (the public Mike Sirota fade, VC #210 vs field ~#26, is on the board today) — and the artifact itself admits `"fade_scored_by_ledger": False`. Nothing anywhere resolves a fade. A fade that the field abandons (a win for us) and a fade the player validates by getting called up over our low rank (a loss) look identical: nothing.
2. **The ahead side is only tracked while it stays on the board.** The frozen AOTC scorecard (`build_ahead_of_consensus_scorecard.py`) does track the higher side's lifecycle, but its outcome buckets fire off *board presence* (still-guarded / divergence-closed / vanished). A bullish call that never resolves and never closes just sits in `open_flat` forever with no deadline. There is no "this claim went N days without resolving — expire it, count it, show it."

This plan converts **every** row that appears on `/gaps` — both sides — into a dated claim that **must visibly resolve or expire**. It is a *parallel additive ledger*: it reads the same committed inputs (the dated `valucast_prospect_rank_v1` archive + the transactions cache) and it reuses the existing divergence/call-up primitives, but it changes **nothing** in the frozen scorecard and nothing in how the model scores.

## Claim-lifecycle taxonomy (the contract)

Every claim is keyed by `(identity_key, claim_date, side)` where `side ∈ {higher, lower}` and `claim_date` is the board-observed date the row first qualified on `/gaps`. A claim is born the first day it appears on either side of the gap board and resolves into exactly ONE terminal outcome (or stays `open`):

| Outcome | Higher (bullish) side | Lower (fade) side |
|---|---|---|
| `resolved_by_callup` | Player was called up **while the gap still held** → this is the receipts-hit event for us | Player was called up while our fade still held → the field was right, we were wrong (a fade "miss") |
| `resolved_by_consensus_move` | Field median moved TOWARD our rank past the noise floor → win of a different kind (they caught up) | Field median moved TOWARD our (lower) rank → the field faded him too; our fade was right |
| `expired_unresolved` | `EXPIRY_DAYS` (60) elapsed with the gap still open and no call-up | same |
| `retracted_by_model_move` | OUR rank moved to close the gap (we backed off) before the field did | OUR rank moved up toward the field (we un-faded him) |

`open` = none of the above yet, and age `< EXPIRY_DAYS`. The lifecycle is derived deterministically each build from the committed rank archive and transactions cache; **history is never rewritten** — a claim's `claim_date` and its terminal outcome, once written, are immutable (see Step 3's merge rule).

This is the taxonomy the mandate requires; it is deliberately a SEPARATE vocabulary from the frozen scorecard's `funnel` buckets (`open_toward` / `closed_caught_up` / `retired_we_backed_off` / …) so the two never get conflated and the frozen one is never touched.

## Current state

Verified at `fb360066`:

- `prospects/consensus_gap.py` — builds `data/models/valucast_consensus_gap.json`. Reuses AOTC primitives verbatim (`_divergence_row`, `_conviction`, `_public_source_consensus` via `_public_source_ranks`, `FEATURED_MIN_BOARDS=3`, `MIN_DIVERGENCE=25`, `MAX_VALUCAST_RANK=300`). `MAX_ROWS_PER_SIDE = 15` (:50). Output keys: `higher` and `lower`, each a list of `_display_row` dicts (:87-99) carrying `identity_key, mlbam_id, name, team, role, valucast_rank, consensus_rank, board_count, divergence`. `_qualifies_ahead` (:67, `divergence >= MIN_DIVERGENCE`) and `_qualifies_fade` (:77, `divergence <= -MIN_DIVERGENCE`), both require `board_count >= FEATURED_MIN_BOARDS`, `_within_depth`, and `not in_mlb`. **CRITICAL**: the `higher`/`lower` lists are TRUNCATED to 15/side, but `_qualifies_*` runs over ALL rows — today `ahead_qualified=51`, `fade_qualified=46`, only 15 each shown. The ledger must enroll every **qualified** claim, not just the 15 displayed (otherwise it re-introduces survivorship bias at the display cutoff). Refactor `build_consensus_gap_board` to expose the full qualified sets (see Step 1).
- `prospects/ahead_of_consensus.py` — divergence engine. `_divergence_row` (:126), `_public_source_ranks`/`_public_source_consensus` (:97, :112, ported verbatim from `web/public_snapshot_models.py`), `_is_guarded` (:160), guard constants (`MIN_DIVERGENCE=25`, `MAX_VALUCAST_RANK=300`, `CONSENSUS_RANK_CAP=600`, `FEATURED_MIN_BOARDS=3`). `ARCHIVE_DIR = data/prediction_archive/valucast_prospect_rank_v1` (:30). Rows carry `active_mlb_roster` from 7/4 on; `_divergence_row` maps that to `in_mlb`. **This file is imported-from, never edited.**
- `prospects/call_up_receipts.py` (rewritten today, `fb360066` — the at-promotion standard) — has exactly the transaction-parsing machinery this plan reuses:
  - `_actual_call_up_dates(transactions_cache) -> dict[str, str]` (:113) — earliest genuine call-up date per `mlbam_id` (str), 40-man-paperwork-aware. **Import and reuse — do not reimplement.**
  - `_archive_by_date_key(archive_payloads) -> dict[date -> {identity_key: row}]` (:311), `_archive_payloads(path)` (:576), `_identity_key(row)` (:149), `_date_part(value)` (:77), `_load_json` (:69), `TRANSACTIONS_CACHE_PATH` (:56), `RANK_ARCHIVE_DIR` (:22), `_write_json` (:589, atomic tmp+replace), `archive_call_up_receipts`-style archiver (:597). Reuse these helpers.
  - `LAUNCH_DATE = "2026-06-16"` (:66) — the public board's launch. A claim whose real call-up predates launch has no "ahead of the field" story; mirror this exclusion.
- `scripts/build_consensus_gap_board.py` — thin runner calling `prospects.consensus_gap.run`.
- `scripts/run_daily_public_build.py` — `BUILD_STEPS` (:16) runs `build_consensus_gap_board.py` at :91 (right after AOTC + AOTC scorecard). `VALIDATE_STEPS` (:99). The new build + validate steps slot in here (Step 4).
- `scripts/validate_public_data_freshness.py:86` — already defines `VALUCAST_CONSENSUS_GAP = ROOT / "data" / "models" / "valucast_consensus_gap.json"` (constant present; plan 004 wires it into `dated_artifacts`). Your new claims artifact needs its own path constant + freshness/row entry here OR in its own validator (Step 4 picks the validator route to avoid colliding with plan 004's edit to the same file).
- `app.py`:
  - `CONSENSUS_GAP_PATH` (:569), `/gaps` route (:7109-7128) renders `gaps.html` with `gaps_higher`, `gaps_lower`, `gaps_summary`, `gap_count`, `gaps_generated_at`.
  - `RECEIPTS_HOLD = True` (:78) gates the receipts page; the gaps page is NOT gated (it's live). `_load_artifact(Path)` is the artifact loader used throughout.
  - `/ledger` (:7131) renders `track_record.html` from the frozen AOTC scorecard — leave it alone; the claims counts *feed* a link/strip, they don't replace the ledger.
- `templates/gaps.html` — two sections, `WE'RE HIGHER 🔭` and `WE'RE LOWER 🧊`, each with a `buys-fineprint` line. The higher line links `/ledger`; the lower line says "published, not ledger-scored yet." That fineprint is the honest hook the new resolved/expired strip replaces/augments (Step 5).
- **No claims artifact exists yet.** `ls data/models | grep -iE 'claim|ledger'` → only `valucast_consensus_gap.json`. `data/prediction_archive/` has no gap/claims dir. You are creating both.

Repo conventions: stdlib-only (`json`, `os`, `pathlib`, `datetime`); artifacts written atomically (tmp + `os.replace`, `sort_keys=True`); validators are standalone `scripts/validate_*.py` that read the artifact and return `(payload, problems)`; tests are plain pytest with `tmp_path`, no fixtures. Source-policy dicts on every artifact declare `feeds_model_score/feeds_public_rank/feeds_buy_score = False`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| New module tests | `python -m pytest -q tests/test_gaps_claim_ledger.py tests/test_consensus_gap.py` | all pass |
| Build the claims ledger | `python scripts/build_gaps_claim_ledger.py` | prints claim counts; writes artifact + archive; exit 0 |
| Validate the ledger | `python scripts/validate_gaps_claim_ledger.py` | exit 0 |
| Daily-build wiring test | `python -m pytest -q tests/test_consensus_gap.py -k "workflow or steps"` | build step ordered after gap board; validate step present |
| Full suite (final gate) | `python -m pytest -q` | 1776+ pass, 0 fail; then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` (pytest dirties it — NEVER commit it) |

Baseline before you start: `python -m pytest -q` → 1776 passed, 0 failed.

## Scope

**In scope** (the only files you create or modify):
- `prospects/gaps_claim_ledger.py` (NEW) — the lifecycle engine.
- `scripts/build_gaps_claim_ledger.py` (NEW) — runner.
- `scripts/validate_gaps_claim_ledger.py` (NEW) — validator.
- `prospects/consensus_gap.py` — SMALL refactor only: expose the full qualified `higher`/`lower` sets (before the 15-row truncation) so the ledger enrolls every qualified claim. Do NOT change any qualification threshold, ordering, display shape, or the truncated public lists.
- `scripts/run_daily_public_build.py` — add one build step + one validate step.
- `app.py` — add a claims-ledger load helper + pass resolved/expired counts (and a small resolved list) into the `/gaps` render context. No new route required (reuse `/gaps`); an optional read-only `/gaps-ledger.json` passthrough is allowed if it mirrors the existing `/aotc-scorecard.json` pattern exactly.
- `templates/gaps.html` — add the resolved/expired strip (or link) fed by the new counts.
- Tests: `tests/test_gaps_claim_ledger.py` (NEW), extend `tests/test_consensus_gap.py`.
- `data/models/valucast_gaps_claim_ledger.json` + `data/prediction_archive/valucast_gaps_claim_ledger/<date>.json` — the committed artifact + its archive (generated by the build step, committed like the sibling artifacts).

**Out of scope** (do NOT touch — hard freeze / not this plan):
- `prospects/ahead_of_consensus.py` and `scripts/build_ahead_of_consensus_scorecard.py` — the AOTC scorecard scoring RULES are FROZEN (pre-registered 7/2) until ~7/13. Import primitives from `ahead_of_consensus.py`; add nothing to it and change nothing in the scorecard. Your ledger's outcome vocabulary is DELIBERATELY DISJOINT from the scorecard's `funnel` buckets.
- `prospects/call_up_receipts.py` — import its helpers (`_actual_call_up_dates`, `_archive_by_date_key`, `_archive_payloads`, `_identity_key`, `_date_part`, `LAUNCH_DATE`); do NOT change receipt/miss row semantics or its incremental merge.
- `/ledger` / `track_record.html` / the AOTC scorecard JSON — untouched.
- `web/public_snapshot_models.py` — the consensus math source of truth; read-only reference.

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**: master auto-deploys valucast.app via Render. Commit locally; the reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — parallel sessions leave untracked files dirty). Stage each file explicitly, INCLUDING the two new committed data files.
- Commit message style (from git log — short imperative): `Add two-sided gaps claim ledger: every gap claim resolves or expires`.

## Steps

### Step 0: Confirm the boundary before writing anything

Read `scripts/build_ahead_of_consensus_scorecard.py` end to end and confirm: it consumes ONLY the rank archive, it owns the `funnel`/`open_*`/`decided_rate` vocabulary, and it is frozen. Your ledger must not import from it, not mutate its artifact, and not reuse its bucket names. If the scorecard has changed shape since `fb360066` such that the fade side is now scored there, **STOP and report** — the hole may already be closed and this plan would duplicate it.

**Verify**: `grep -n "fade_scored_by_ledger" prospects/consensus_gap.py` still shows `False`. If it shows `True`, STOP.

### Step 1: Expose the full qualified gap sets (tiny refactor to `consensus_gap.py`)

`build_consensus_gap_board` currently sorts `ahead`/`fade` then truncates to `MAX_ROWS_PER_SIDE` only inside the return dict. Add the full qualified sets to the payload so the ledger enrolls every qualified claim, not just the 15 shown, WITHOUT changing the public `higher`/`lower` lists:

- Add two keys to the returned dict: `"higher_all": [_display_row(r) for r in ahead]` and `"lower_all": [_display_row(r) for r in fade]` (full, untruncated). The existing `"higher"`/`"lower"` stay truncated to `MAX_ROWS_PER_SIDE` exactly as today.
- Keep `_display_row` shape identical (do not add per-source `boards`).

This is the ONLY change to `consensus_gap.py`. Thresholds, ordering, `_within_depth`, `in_mlb` exclusion, and the truncated public lists are untouched.

**Verify**: `python -m pytest -q tests/test_consensus_gap.py` → all pass (existing tests assert `higher`/`lower`; they still hold). Add one test: `higher_all` length ≥ `len(higher)` and every `higher` row's `identity_key` is in `higher_all`. `python scripts/build_consensus_gap_board.py` then `python -c "import json; p=json.load(open('data/models/valucast_consensus_gap.json')); print(len(p['higher']), len(p['higher_all']), len(p['lower']), len(p['lower_all']))"` → shown ≤ all on both sides.

### Step 2: Write the lifecycle engine — `prospects/gaps_claim_ledger.py`

New stdlib-only module. Core shape mirrors `call_up_receipts.py` (incremental-from-committed-artifact, existing rows win the merge, atomic write). Key design:

**Constants** (module-level, documented like the AOTC guard block):
```python
EXPIRY_DAYS = 60                 # a claim with no resolution after this many days from claim_date -> expired_unresolved
CONSENSUS_MOVE_FLOOR_SPOTS = 10  # min field-median move (spots) to count resolved_by_consensus_move; mirrors the scorecard NOISE_FLOOR_SPOTS *value* but is redeclared here, NOT imported (frozen file)
MODEL_MOVE_FLOOR_SPOTS = 10      # min OUR-rank move to count retracted_by_model_move
SIDES = ("higher", "lower")
```
Redeclare the floor (do not import `NOISE_FLOOR_SPOTS` from the frozen scorecard) — a comment must say WHY (the frozen file must not become a dependency of a post-freeze surface). Do NOT copy the gap-fraction floor; a single spots floor is enough for a display-only claim resolver and keeps the taxonomy legible.

**Enrollment** (`_enroll_claims`): for each dated rank archive snapshot (walk `_archive_payloads(RANK_ARCHIVE_DIR)` in date order), rebuild the qualified gap sets **for that snapshot's board** using `build_consensus_gap_board(payload, roster_status=...)` and read `higher_all` / `lower_all`. Each qualified `(identity_key, side)` seen on snapshot date `d` that is not already an open/closed claim opens a new claim `{identity_key, side, claim_date: d, claim_valucast_rank, claim_consensus_rank, claim_divergence, name, mlbam_id, ...}`. `claim_date` is board-observed and immutable. A claim opens ONCE per `(identity_key, claim_date, side)`; if the same player re-qualifies on the same side after a terminal outcome, that is a NEW claim on a later `claim_date` (never resurrect a resolved one). Enrollment starts at `LAUNCH_DATE` — a claim can't predate the public board.

**Resolution** (`_resolve_claim`), evaluated against the LATEST archive snapshot + the transactions cache, in priority order (first match wins, terminal):
1. `resolved_by_callup` — `actual_call_up_dates.get(str(mlbam_id))` exists, is `>= claim_date`, and (for a clean read) the call-up is not pre-`LAUNCH_DATE`. Record `resolved_date = actual_call_up_date`.
2. `retracted_by_model_move` — OUR rank at the latest snapshot moved to CLOSE the gap by `>= MODEL_MOVE_FLOOR_SPOTS` (higher: our rank rose toward consensus; lower: our rank fell toward consensus) *before* the field moved. This is the "we backed off" outcome; it must be checked against the model's own rank delta from the claim snapshot, using `_archive_by_date_key` to fetch the claim-date row and the latest row.
3. `resolved_by_consensus_move` — the field median moved TOWARD our rank by `>= CONSENSUS_MOVE_FLOOR_SPOTS` since `claim_date` (higher: consensus_now < consensus_then; lower: consensus_now > consensus_then). The field converged on us.
4. `expired_unresolved` — `days_between(claim_date, latest_date) >= EXPIRY_DAYS` and none of the above. Counted and shown.
5. else `open`.

Compute `lead_time_days` on `resolved_by_callup` claims = `days_between(claim_date, resolved_date)` — this is the field the mandate flags as currently unweighted; surface it per-row so a 2-day-early flag is visibly distinguished from a 30-day-early one (the display can bucket or sort by it; the value is stored regardless).

**Merge invariant** (`build_gaps_claim_ledger`): load the committed artifact; for every claim already carrying a TERMINAL outcome, keep it verbatim (immutable). Re-resolve only `open` claims + newly enrolled ones. A terminal outcome, once written, is never recomputed or rewritten — this is the append-only history the mandate demands. Include a `_revalidate`-style guard ONLY if a re-scan would change an OPEN claim's `claim_date` (it must not — assert it doesn't).

**Payload shape** (`build_gaps_claim_ledger(...) -> dict`), sort_keys, atomic write:
```python
{
  "artifact": "valucast_gaps_claim_ledger",
  "signal_name": "ValuCast Gaps Claim Ledger",
  "signal_version": "0.1.0",
  "generated_at": ...,
  "status": "candidate_ready" | "blocked",
  "source_policy": {  # every flag False except the two rank/transaction inputs
    "kind": "valucast_gaps_claim_ledger",
    "inputs": "valucast_prospect_rank_v1_dated_archive + transactions_cache",
    "feeds_model_score": False, "feeds_public_rank": False, "feeds_buy_score": False,
    "dd_values_used": False, "dd_ranks_used": False,
    "external_rankings_used": False, "market_values_used": False,
    "scored_by_frozen_aotc_scorecard": False,  # explicitly disjoint from the frozen ledger
  },
  "taxonomy": { "resolved_by_callup": "...", "resolved_by_consensus_move": "...",
                "expired_unresolved": "...", "retracted_by_model_move": "...", "open": "..." },
  "summary": {
    "higher": {"open": n, "resolved_by_callup": n, "resolved_by_consensus_move": n,
               "expired_unresolved": n, "retracted_by_model_move": n, "total": n},
    "lower":  {  ...same keys... },
    "expiry_days": EXPIRY_DAYS,
  },
  "validation": {"ready": bool, "blockers": [...]},
  "claims": [ ...every claim row, both sides, sorted deterministically... ],
}
```
Blockers: `< 2` dated rank archives; no transactions cache (call-up resolution impossible → still build, but flag). `status="blocked"` only when the ledger cannot be built at all (no archives), matching the sibling artifacts.

Archive the payload to `data/prediction_archive/valucast_gaps_claim_ledger/<generated_date>.json` with the same skip-if-identical archiver as `archive_call_up_receipts` (:597).

**Verify**: `python -m pytest -q tests/test_gaps_claim_ledger.py` → all pass (tests written in Step 6). Then `python scripts/build_gaps_claim_ledger.py` (Step 3 runner) on real data → prints a summary; inspect the artifact: every claim has a `side`, a `claim_date >= LAUNCH_DATE`, and an outcome in the taxonomy.

### Step 3: Runner — `scripts/build_gaps_claim_ledger.py`

Thin `sys.path.insert` + `from prospects.gaps_claim_ledger import run` runner (mirror `scripts/build_consensus_gap_board.py`). `run()` loads the rank archive, roster status, transactions cache, and the existing committed ledger; calls `build_gaps_claim_ledger(...)`; writes the artifact + archive; prints per-side counts. Return a small dict like the receipts runner (`artifact_path`, per-side totals, `open`/`resolved`/`expired` tallies).

**Verify**: `python scripts/build_gaps_claim_ledger.py` → exit 0, prints counts, `git status` shows the new artifact + a new dated archive file.

### Step 4: Wire into the daily build + add a validator

1. `scripts/run_daily_public_build.py` — add `("scripts/build_gaps_claim_ledger.py",)` to `BUILD_STEPS` **immediately after** `("scripts/build_consensus_gap_board.py",)` (:91) — the ledger reads the gap board's logic and must run after it. Add `("scripts/validate_gaps_claim_ledger.py",)` to `VALIDATE_STEPS` after `("scripts/validate_ahead_of_consensus_scorecard.py",)`.
2. `scripts/validate_gaps_claim_ledger.py` (NEW) — standalone validator mirroring `scripts/validate_ahead_of_consensus.py`: read the artifact, assert `artifact`/`signal_version`/`generated_at` parseable/`status` in `{blocked, candidate_ready}`; assert `summary.higher.total == count of higher claims` and same for lower; assert **every** claim's outcome ∈ the taxonomy and `claim_date >= LAUNCH_DATE`; assert `source_policy` feeds-flags are all `False`; assert **no terminal outcome is missing a resolution field** (`resolved_by_callup` → `resolved_date` present; `expired_unresolved` → age `>= EXPIRY_DAYS`). Return `(payload, problems)`; exit non-zero on problems, printing each.

Do NOT add the new artifact to `scripts/validate_public_data_freshness.py` — that file is plan 004's edit surface and a second freshness entry there would collide. The standalone validator + the daily build's own freshness of committed data covers it. (If plan 004 has already landed and you want a freshness floor too, add the row in the SAME style as its three new entries and note the coordination in your commit body — but the standalone validator is the required deliverable.)

**Verify**: `python scripts/validate_gaps_claim_ledger.py` → exit 0 against the just-built artifact. `python -c "import ast; ast.parse(open('scripts/run_daily_public_build.py').read())"` → no error. `python -m pytest -q tests/test_consensus_gap.py -k "steps or workflow"` → the build-order test still passes; extend it to assert the ledger step is ordered after the gap-board step.

### Step 5: Render the resolved/expired strip on `/gaps`

1. `app.py` — add `GAPS_CLAIM_LEDGER_PATH = Path(__file__).parent / "data" / "models" / "valucast_gaps_claim_ledger.json"` next to `CONSENSUS_GAP_PATH` (:569). Add a loader `_load_gaps_ledger()` (mirror `_load_scorecard_payload`, fail-soft to `{}`). In the `/gaps` route, load it and pass into the template: `gaps_ledger_summary=ledger.get("summary") or {}`, plus a short `gaps_ledger_resolved` list (the most recent N `resolved_by_callup`/`resolved_by_consensus_move`/`expired_unresolved` claims, both sides, for the strip). Guard fail-soft: if the ledger is absent, the strip simply doesn't render (`gaps_ledger_available = bool(summary)`).
2. `templates/gaps.html` — replace the two static fineprint lines' "not ledger-scored yet" framing with an honest, data-backed strip: a compact "Claim ledger" block under the gap sections showing, per side, `open / resolved (by call-up + by field move) / expired / retracted` counts from `gaps_ledger_summary`, and a small "recently resolved" list from `gaps_ledger_resolved` that shows `lead_time_days` on call-up resolutions (so the previously-invisible fades-that-expired and the lead-time weighting are both visible). Keep the aggregate-consensus-only rule: NEVER print per-source board ranks. If `gaps_ledger_available` is false, keep today's fineprint text unchanged.

**Verify**: `python -m pytest -q tests/test_public_surfaces_smoke.py -k gaps` (or the nearest gaps smoke test) → passes; the `/gaps` route renders with and without the ledger artifact present. Manually: `python -c "from app import app; c=app.test_client(); r=c.get('/gaps'); print(r.status_code); assert b'ledger' in r.data.lower()"` → `200`.

### Step 6: Tests — `tests/test_gaps_claim_ledger.py`

Plain pytest, `tmp_path`, synthetic dated archive payloads (list of `{"date": ..., "board": [rows]}` dicts) + a synthetic transactions cache. Cover:
1. **Enrollment (both sides)**: a synthetic board with one qualifying `higher` row and one qualifying `lower` row → two claims open, correct `side`, `claim_date` = first qualifying snapshot date.
2. **`resolved_by_callup` higher**: player called up (transactions cache has a genuine call-up `>= claim_date`) while gap holds → outcome `resolved_by_callup`, `resolved_date` set, `lead_time_days` correct.
3. **`resolved_by_callup` lower (fade miss)**: fade player called up → outcome `resolved_by_callup` on the `lower` side (the symmetric accountability the mandate demands).
4. **`resolved_by_consensus_move`**: no call-up, but the later snapshot's consensus median moved toward our rank past `CONSENSUS_MOVE_FLOOR_SPOTS` → that outcome, on the correct side.
5. **`retracted_by_model_move`**: our rank moved to close the gap before the field → that outcome.
6. **`expired_unresolved`**: `EXPIRY_DAYS+` between `claim_date` and latest with no resolution → expired, counted.
7. **Append-only merge**: build once → a terminal claim; build AGAIN with a later archive where that player's board row would now classify differently → the terminal claim is UNCHANGED (verbatim), and no `claim_date` mutates. (The load-bearing invariant.)
8. **`LAUNCH_DATE` guard**: a synthetic call-up dated before `LAUNCH_DATE` never mints a claim.

**Verify**: `python -m pytest -q tests/test_gaps_claim_ledger.py` → all pass.

### Step 7: Full-suite gate + restore the pytest byproduct

**Verify**:
1. `python -m pytest -q` → 1776+ passed, 0 failed (your new tests add to the count).
2. `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` (pytest dirties it — NEVER commit it).
3. `git status` → only in-scope files: the 3 new modules/scripts, the `consensus_gap.py` refactor, `run_daily_public_build.py`, `app.py`, `templates/gaps.html`, the 2 new tests, the new committed artifact + its dated archive file. Nothing else.

## Test plan

- `tests/test_gaps_claim_ledger.py` (NEW): 8 cases above (enrollment both sides, four resolution outcomes, expiry, append-only merge, launch guard).
- `tests/test_consensus_gap.py` (extend): +1 `higher_all`/`lower_all` completeness; +1 build-order (ledger step after gap-board step).
- Validators exercised by running `scripts/validate_gaps_claim_ledger.py` against the freshly built artifact (Step 4 verify).
- Smoke: `/gaps` renders with and without the ledger artifact (Step 5 verify).
- Final: `python -m pytest -q` all green, then restore the peak-projection byproduct file.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (byproduct file restored after).
- [ ] `python scripts/build_gaps_claim_ledger.py` writes `data/models/valucast_gaps_claim_ledger.json` + a dated archive; `python scripts/validate_gaps_claim_ledger.py` exits 0.
- [ ] `grep -n "higher_all\|lower_all" prospects/consensus_gap.py` → both present; `grep -n "MAX_ROWS_PER_SIDE" prospects/consensus_gap.py` → truncation of `higher`/`lower` unchanged.
- [ ] `grep -n "resolved_by_callup\|resolved_by_consensus_move\|expired_unresolved\|retracted_by_model_move" prospects/gaps_claim_ledger.py` → all four outcomes implemented; the SAME four appear in `scripts/validate_gaps_claim_ledger.py`.
- [ ] `grep -n "lead_time_days" prospects/gaps_claim_ledger.py` → lead time computed on call-up resolutions.
- [ ] `grep -rn "NOISE_FLOOR_SPOTS\|from scripts.build_ahead_of_consensus_scorecard\|import build_ahead_of_consensus_scorecard\|funnel" prospects/gaps_claim_ledger.py` → NO hits (frozen scorecard is not a dependency; disjoint vocabulary).
- [ ] `grep -n "build_gaps_claim_ledger.py" scripts/run_daily_public_build.py` → build step present, ordered after `build_consensus_gap_board.py`; validate step present.
- [ ] `git diff --stat fb360066..HEAD -- prospects/ahead_of_consensus.py scripts/build_ahead_of_consensus_scorecard.py` → EMPTY (frozen files untouched).
- [ ] `grep -n "ledger" templates/gaps.html` → the resolved/expired strip renders from `gaps_ledger_summary`.
- [ ] `git status` shows only in-scope files; the pytest byproduct file is restored.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Step 0: `consensus_gap.py` now shows `"fade_scored_by_ledger": True`, or the frozen scorecard now scores the fade side — the hole may already be closed; report instead of duplicating.
- Any change would be required inside `prospects/ahead_of_consensus.py` or `scripts/build_ahead_of_consensus_scorecard.py` to make the ledger work — that means you are extending frozen machinery, not building a parallel additive one. Stop and rethink the design so it reads inputs and reuses helpers WITHOUT editing frozen files.
- The append-only merge test (case 7) cannot be made to pass without recomputing a terminal outcome — the design is wrong; the ledger must never rewrite decided history.
- Today is on or before 2026-07-13 (the AOTC gate is still closed) — do not land this plan; report that the execution window hasn't opened.
- The `consensus_gap.py` refactor changes any threshold, ordering, or the truncated public `higher`/`lower` lists (it must only ADD `higher_all`/`lower_all`).

## Maintenance notes

- **Why a separate ledger instead of extending the AOTC scorecard**: the scorecard is frozen and pre-registered, and it only covers the *higher* side's board-presence lifecycle. Fades are the unaccounted hole. Building this as a parallel artifact keeps the frozen accountability number honest (untouched) while adding the two-sided claim lifecycle the mandate requires. When the AOTC gate unlocks (~7/13), the two can be cross-linked in copy, but they must stay as separate artifacts and separate vocabularies.
- **`EXPIRY_DAYS = 60` is a product dial**, not a law. The mandate mentions 60/90; 60 is the default because the external boards refresh ~monthly (see the scorecard's `MIN_PUBLISH_HORIZON_DAYS=30` rationale), so 60 gives a claim two refresh cycles to resolve. If Alex wants a 90-day tier, add it as a second expiry bucket rather than moving the floor.
- **Lead-time weighting**: this plan STORES `lead_time_days` and surfaces it; it does not yet weight a headline number by it (that would be a scored metric, and scored metrics near the AOTC surface stay frozen-adjacent). A future plan can add a lead-time-weighted hit rate ONCE the AOTC gate is open and a pre-registration exists for it.
- Reviewer scrutiny: confirm (a) no terminal claim is ever recomputed across two builds; (b) the ledger enrolls from `higher_all`/`lower_all` (the full qualified sets), not the 15-row public lists, or survivorship bias sneaks back in at the display cutoff; (c) the frozen files show an empty diff.
```