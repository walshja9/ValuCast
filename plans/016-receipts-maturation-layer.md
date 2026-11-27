# Plan 016: Receipts maturation layer — resolve every receipt PENDING → CONFIRMED / DECAYED at +60/90d

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **EXECUTION WINDOW: post-2026-07-13.** This layer is additive machinery that
> mirrors the AOTC v2 scorecard pattern (pre-registered, frozen targets). It
> does NOT touch the frozen AOTC scoring files, but it borrows their discipline,
> and the board is small — the first receipts don't mature until ~2026-09-09
> (Cooper Ingle's 6/26 call-up + 60d + the AOTC-style publish horizon). There is
> nothing to display before then, so building it before the AOTC gate unlock buys
> nothing and risks colliding with 7/13 work. If run before 7/13, STOP.
>
> **Drift check (run first)**:
> `git diff --stat fb360066..HEAD -- prospects/call_up_receipts.py scripts/build_valucast_call_up_receipts.py scripts/validate_valucast_call_up_receipts.py scripts/archive_valucast_actuals_snapshot.py app.py templates/receipts.html`
> `prospects/call_up_receipts.py` changed on 2026-07-08 (the at-promotion
> standard). Re-read it fresh regardless. If the "Current state" excerpts below
> no longer match live code, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M (one new pure function + builder wiring + summary counts + one template chip + tests)
- **Risk**: LOW (append-only, display-only; never feeds score/rank/value; gated behind `RECEIPTS_HOLD`)
- **Depends on**: none in code. Sequencing: the daily build already writes the
  actuals-snapshot archive (`scripts/run_daily_public_build.py:23`) BEFORE the
  receipts build (`:63`), so the maturation reader has today's snapshot in hand.
- **Category**: feature (honesty / accountability)
- **Planned at**: commit `fb360066`, 2026-07-08

## Why this matters

The receipts board today scores **arrival, not outcome**. Its trigger is the
call-up itself, and that trigger creates survivorship bias: a bullish over-rank
only ever becomes a receipt if the player *reaches MLB* — the over-ranks that
never resolve (the prospect who was hyped and stalled in AAA) are structurally
invisible. The seed lane can only add hits. Lead time is unweighted, so a
2-day-early flag reads identically to a 30-day-early one. And once a row lands,
nothing ever revisits it: "ValuCast had Owen Murphy #26 vs the field's #146"
is booked as a permanent win the day he debuts, even if he throws one inning
and is optioned back the next day (which is exactly what the transactions cache
shows — SE 7/06, OPT 7/07).

The receipt is a claim that ValuCast saw an MLB-caliber player before the field
did. **Arrival is necessary but not sufficient evidence for that claim.** A
maturation layer closes the loop: every receipt opens `PENDING` and, at a
pre-registered horizon, resolves to `CONFIRMED` (the player actually stuck and
produced real MLB innings/plate appearances) or `DECAYED` (a cup-of-coffee — he
bounced back to the minors having barely played). This makes the board's
positive claims *testable and falsifiable from ValuCast's own archived data*,
the same standard the AOTC scorecard already holds itself to. It does NOT undo
the two-sided misses ledger or the neither-bucket (those handle the *behind* and
*no-claim* sides); it adds the resolution dimension the *ahead* side is missing.

## Current state

Verified at `fb360066`, 2026-07-08 (re-verify against the drift check):

- **Receipts builder** — `prospects/call_up_receipts.py`. `build_call_up_receipts(...)`
  (`:609`) takes `archive_payloads`, `roster_payload`, `existing_log`, `seed_rows`,
  `generated_at`, `transactions_cache` (all keyword-only). It merges receipts/misses,
  runs `_revalidate_existing` (`:533`) to re-score committed AUTO rows under the
  at-promotion standard, merges seeds, attaches `actual_call_up_date`, applies the
  `LAUNCH_DATE` guard, computes the neither bucket, and returns a payload dict whose
  `summary` (`:734`) already carries `receipt_count`, `miss_count`, `seed_count`,
  `no_claim_call_up_count`, `archive_dates_scanned`, `pre_launch_excluded_count`,
  `pre_launch_excluded_names`. Receipt rows carry: `identity_key`, `mlbam_id`, `role`,
  `name`, `team`, `pos`, `level`, `valucast_rank`, `consensus_rank`, `divergence`,
  `call_up_date` (board-observed), `actual_call_up_date` (real transaction date),
  `logged_at`, and `seed: True` on curated rows.
- **INCREMENTAL contract** — `build_call_up_receipts` reads `existing_log`
  (`run_call_up_receipts` passes `_load_json(artifact_path)` at `:765`); existing rows
  win the merge (`_detect_call_ups` at `:434`: `merged = {row["identity_key"]: row for row in existing_rows}`).
  Any change to what a *committed* row means requires a re-validation pass — the file
  already has the template for this in `_revalidate_existing` (`:533`), which the
  builder calls at `:657-658`. **Your maturation write must be idempotent across
  rebuilds and must never silently un-confirm a confirmed row** (see append-only
  rule in Step 2).
- **Maturation evidence source** — `data/prediction_archive/valucast_actuals_snapshot/<date>.json`.
  Verified shapes:
  - It is a **list** of rows, each `{"id", "metadata": {"as_of", "mlbam_id", ...}, "name", "pool", "positions", "stats", "team"}`. The mlbam id is at `row["metadata"]["mlbam_id"]` (a string), NOT `row["mlbam_id"]`.
  - Stats are **cumulative season totals**, not daily deltas (verified: Cooper Pratt 806198 `G` went 17 → 18 → 21 across 7/05/7/07/7/09; `PA` 60 → 64 → 77).
  - **Hitters** carry `stats.G` and `stats.PA`. **Pitchers** appear under `pool` in `{"reliever","starter"}` (verified label `"reliever"`) carrying `stats.G` and `stats.IP`. A two-way / DH'ing pitcher can appear as BOTH a `hitter`-pool row and a `reliever`-pool row for the same mlbam id (verified: Owen Murphy 702566 has a `hitter` row `G=1,PA=0` and a `reliever` row `G=1,IP=1.0`). Match on mlbam id and take the MAX games / MAX (PA or IP) across all rows for that id so a pitcher's real workload isn't read off his empty batting line.
  - The snapshot's `as_of` is `row["metadata"]["as_of"]` (a `YYYY-MM-DD` string); the archive file is named `<as_of>.json`. There are ~1,394 rows in the latest snapshot; the archive currently spans 2026-07-05 → today (older snapshots exist for the receipts window via the same dir).
  - **DO NOT use `data/prediction_archive/valucast_mlb_roster_status/<date>.json` for roster-days** — those dated files are THIN (`contract_version`, `generated_at`, `validation` only; `profiles` is empty). The actuals snapshot is the only per-player daily archive with real workload.
- **Archive reader helper** — `_archive_by_date_key` (`:311`) already walks the RANK archive; write a *separate* small reader for the actuals-snapshot dir (different shape: list, not `{"board": [...]}`). Model the file walk on `_archive_payloads` (`:576`, `sorted(path.glob("*.json"))`).
- **Public render** — `app.py` `_build_receipts_page_context` (`:7081`) returns `receipts`/`misses`/`no_claim_call_up_count`/etc.; the page is gated by `RECEIPTS_HOLD = True` (`:78`) — receipts/misses are blanked to `[]` when held (`:7083-7084`). Row rendering is in `templates/receipts.html`: the AHEAD list at `:60-79` renders each `p` with `#{{ p.valucast_rank }}`, name link, tags, `+{{ p.divergence }}`, and `<span class="trend-chip buys-chip">ahead</span>` (`:77`).
- **Validator** — `scripts/validate_valucast_call_up_receipts.py`. `_validate_call_up`
  checks required fields and consensus/divergence math; `validate_file` checks
  `summary.receipt_count == len(receipts)` etc. It does NOT currently look at any
  maturation field. `SIGNAL_VERSION` is imported from `prospects.call_up_receipts`
  and asserted equal (`:79` in the builder module: `SIGNAL_VERSION = "0.1.0"`).
- **AOTC v2 pattern to mirror** (do NOT edit these files): `scripts/build_ahead_of_consensus_scorecard.py` shows the discipline — `MATURITY_DAYS = 14` (`:52`), a `definitions` block with `"frozen": "2026-07-02, ..."` (`:374`), and `targets` marked `"display-only; the model never optimizes toward this scorecard"` (`:376-380`). Copy that *shape* (module-level frozen constants + a `maturation` definitions/targets block), not that file.
- **Full-suite baseline**: `1776 passed 0 failed`. Tests that assert `summary` keys: `tests/test_call_up_receipts.py` asserts `receipt_count`, `miss_count`, `no_claim_call_up_count` (grep-verified at lines 226/247/488/514/563/591). Adding NEW summary keys is safe; do not rename or drop existing ones.

## PRE-REGISTERED MATURATION THRESHOLDS (frozen at implementation)

Write these as module-level constants in `prospects/call_up_receipts.py` and a
`"frozen"` stamp in the payload's `definitions.maturation`, exactly as the AOTC
scorecard freezes its noise floor. **Do not tune these after seeing the first
resolutions** — that is the entire point of pre-registration. The values below
are chosen from what the receipt is claiming (a real MLB-caliber player), the
data actually available (cumulative G/PA/IP from the snapshot archive), and the
board's cadence (first row matures ~9/09).

- `MATURATION_HORIZON_DAYS = 60` — a receipt is ELIGIBLE to resolve once
  `today >= actual_call_up_date (or call_up_date if no real date) + 60 days`.
  Before that it is `PENDING`.
- `MATURATION_FINAL_DAYS = 90` — the resolution taken at the 90-day mark is the
  terminal one for a still-`PENDING`/`DECAYED` row (see append-only rule). 60d is
  the first look; 90d forces a final call so nothing sits `PENDING` forever.
- **CONFIRMED thresholds (either the player's role bar, measured on the LATEST
  snapshot that has him):**
  - hitter: `max_games >= 20` **OR** `max_PA >= 60`
  - pitcher: `max_games >= 12` **OR** `max_IP >= 20.0`
  Constants: `CONFIRM_HITTER_GAMES = 20`, `CONFIRM_HITTER_PA = 60`,
  `CONFIRM_PITCHER_GAMES = 12`, `CONFIRM_PITCHER_IP = 20.0`. (Rationale to bake
  into the definitions block: these are "he stuck and actually played" floors,
  roughly a month of everyday reps for a hitter or a starter's ~4 turns / a
  reliever's regular usage — comfortably above a cup-of-coffee, comfortably
  below "must be a star.")
- **DECAYED**: eligible (past horizon) AND below the CONFIRMED bar AND the player
  is NOT on today's active roster snapshot (reuse `active_roster_lookup` /
  `roster_lookup`, already built in `build_call_up_receipts` at `:619`). "Stuck"
  = still accruing but under the bar while OFF the active roster = a cup of
  coffee that ended. Constant: define "back in the minors" strictly as
  `str(mlbam_id) not in roster_lookup`.
- **STILL PENDING past horizon but on the active roster and under the bar**: keep
  `PENDING` (he's up and playing, just hasn't crossed the counting bar yet) until
  `MATURATION_FINAL_DAYS`, at which point resolve on the counting bar alone
  (`CONFIRMED` if he cleared it by then, else `DECAYED`). This prevents a slow
  accumulator from being wrongly `DECAYED` at 60d while he's still an active
  big-leaguer.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Targeted tests | `python -m pytest -q tests/test_call_up_receipts.py` | all pass (existing 22 + your new ones) |
| Validator self-check | `python scripts/validate_valucast_call_up_receipts.py` | exit 0 against the committed artifact |
| Rebuild-idempotence smoke | `python scripts/build_valucast_call_up_receipts.py` then rerun it | second run leaves `data/models/valucast_call_up_receipts.json` byte-identical except `generated_at`/`logged_at` timestamps; no `maturation_status` flips PENDING→CONFIRMED→PENDING |
| Full suite (final gate) | `python -m pytest -q` | all pass; then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` (pytest dirties it — NEVER commit it) |

## Scope

**In scope** (the only files you modify):
- `prospects/call_up_receipts.py` — the maturation function, its constants, and the wiring into `build_call_up_receipts` + `run_call_up_receipts`.
- `scripts/validate_valucast_call_up_receipts.py` — accept + shape-check the new fields.
- `app.py` — pass maturation summary counts through `_build_receipts_page_context`.
- `templates/receipts.html` — render the per-row status chip + a summary line.
- `tests/test_call_up_receipts.py` — extend.

**Out of scope** (do NOT touch):
- `prospects/ahead_of_consensus.py`, `scripts/build_ahead_of_consensus_scorecard.py` — AOTC scoring is FROZEN (pre-registered 7/2) until the ~7/13 gate. This plan only borrows their *pattern*; it must be additive to receipts only.
- The seed lane (`_seed_receipts`, `SEED_PATH`) — seeds mature too (Step 1 handles them via the same resolver keyed on mlbam id), but do NOT change seed row *ingestion* or the seed JSON.
- `scripts/archive_valucast_actuals_snapshot.py` — it is the producer of your evidence source, read-only here.
- `RECEIPTS_HOLD` — leave it `True`; the maturation UI ships behind the same hold as the rest of the board.
- The misses side and the neither bucket — maturation resolves the **ahead (receipts) side only**. A miss is already an outcome against ValuCast; a no-claim has no row. (If a reviewer later wants miss-maturation, that's a separate plan.)

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**: master auto-deploys valucast.app via Render. Commit locally; the reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — parallel sessions leave untracked files). Stage each file explicitly.
- Commit message style (short imperative subject), e.g.: `Add receipts maturation layer: PENDING -> CONFIRMED/DECAYED at +60/90d`.

## Steps

### Step 1: Actuals-snapshot workload reader

In `prospects/call_up_receipts.py`, add a constant for the snapshot dir next to
the other archive paths (`:19-26`):
```python
ACTUALS_SNAPSHOT_DIR = ROOT / "data" / "prediction_archive" / "valucast_actuals_snapshot"
```
and a reader that returns, per mlbam id (string), the player's peak observed MLB
workload across the whole snapshot archive:
```python
def _mlb_workload(snapshot_dir: Path = ACTUALS_SNAPSHOT_DIR) -> dict[str, dict]:
    """{mlbam_id: {"games": int, "pa": int, "ip": float, "as_of": str}} — cumulative
    season MLB workload per player, read from the archived actuals snapshots. Stats
    are already season-cumulative, so the MAX over the archive is the peak observed.
    A pitcher can appear under a hitter row (empty batting line) AND a reliever/starter
    row; take the max across all rows for the id so his real IP/G isn't read as zero."""
```
Implementation notes (verify each against the shapes in "Current state"):
- Walk `sorted(snapshot_dir.glob("*.json"))`; skip unreadable files (fail-soft, like `_archive_payloads`).
- Each file is a **list**. For each row, `mid = str((row.get("metadata") or {}).get("mlbam_id") or "")`; skip if empty.
- `stats = row.get("stats") or {}`. Accumulate `games = max(games, int(stats.get("G") or 0))`, `pa = max(pa, int(stats.get("PA") or 0))`, `ip = max(ip, float(stats.get("IP") or 0.0))` into the per-id record; keep the latest `as_of` seen.
- Return `{}` if the dir is absent (fail-soft; PENDING everywhere then).

**Verify**: add a unit test that feeds a `tmp_path` snapshot dir with two dated
files (cumulative G growing) and one player who appears as both a hitter and a
reliever row → the reader returns the max games and the reliever's IP. `python -m pytest -q tests/test_call_up_receipts.py -k workload` passes.

### Step 2: The maturation resolver (append-only)

Add module-level constants (the frozen thresholds above) and a pure function that
takes a receipt row + the workload map + roster lookup + today's date and returns
its status string. The four legal statuses: `"PENDING"`, `"CONFIRMED"`, `"DECAYED"`.

```python
MATURATION_HORIZON_DAYS = 60
MATURATION_FINAL_DAYS = 90
CONFIRM_HITTER_GAMES = 20
CONFIRM_HITTER_PA = 60
CONFIRM_PITCHER_GAMES = 12
CONFIRM_PITCHER_IP = 20.0

def _maturation_status(
    row: dict,
    workload: dict[str, dict],
    roster_lookup: dict[str, dict],
    today: str,
    *,
    prior_status: str | None = None,
) -> str:
```
Rules (implement exactly; each rule maps to a threshold above):
1. **APPEND-ONLY FLOOR**: if `prior_status == "CONFIRMED"`, return `"CONFIRMED"`
   immediately. A CONFIRMED row NEVER reverts — a later demotion after
   confirmation is career noise, not a receipt reversal. Document this in a
   comment: the receipt claimed ValuCast saw an MLB-caliber player early; once he
   demonstrably played at MLB level, the claim is settled regardless of what his
   career does afterward.
2. Resolve the anchor date: `anchor = row.get("actual_call_up_date") or row.get("call_up_date")`. If unparseable, return `"PENDING"` (don't guess).
3. `age = _days_between(anchor, today)` — reuse the existing helper if present, else compute with `datetime.date.fromisoformat`. If `age < MATURATION_HORIZON_DAYS`, return `"PENDING"`.
4. Look up workload: `w = workload.get(str(row.get("mlbam_id"))) or {}`. Role = `row.get("role")`.
5. Compute `confirmed_bar`: hitter → `w.games >= CONFIRM_HITTER_GAMES or w.pa >= CONFIRM_HITTER_PA`; pitcher → `w.games >= CONFIRM_PITCHER_GAMES or w.ip >= CONFIRM_PITCHER_IP`.
6. If `confirmed_bar`: return `"CONFIRMED"`.
7. Not over the bar. `on_roster = str(row.get("mlbam_id")) in roster_lookup`.
   - If `age >= MATURATION_FINAL_DAYS`: terminal → return `"DECAYED"` (90d elapsed, bar never cleared).
   - Elif `on_roster`: return `"PENDING"` (up and playing, slow accumulator, not yet 90d).
   - Else (off roster, under bar, past 60d): return `"DECAYED"`.

Write the status onto each receipt row as `row["maturation_status"]` inside
`build_call_up_receipts`, AFTER the final `receipts` list is assembled (after the
`EXCLUDED_IDENTITY_KEYS` filter at `:670` and the `actual_call_up_date` attach at
`:676-680`, before the `return`). Pass `prior_status=row.get("maturation_status")`
read from the SAME row object (it came from `existing_log` through the merge, so a
previously-CONFIRMED row carries its status forward → the append-only floor holds
across rebuilds). Seeds get resolved by the same call (they carry `mlbam_id`,
`role`, `call_up_date`; seeds have no `actual_call_up_date`, so the anchor falls
back to `call_up_date` — correct).

Compute `today` from `generated_at[:10]` (already available in the builder).

**Verify**: unit tests below. `python -m pytest -q tests/test_call_up_receipts.py -k maturation` passes.

### Step 3: Summary counts

In the payload's `summary` dict (`:734`), add three counts computed from the
resolved receipts (NOT misses):
```python
"maturation": {
    "pending": <count>,
    "confirmed": <count>,
    "decayed": <count>,
},
```
and add a `definitions.maturation` block mirroring the AOTC `definitions`/`targets`
discipline — the four thresholds, the 60/90 horizons, an `"append_only": "a CONFIRMED
receipt never reverts; a later demotion is career noise, not a receipt reversal"`
note, and `"frozen": "<YYYY-MM-DD of implementation>, pre-registered before the first
row matures (~2026-09-09)"`. Do not add a `targets` numeric goal unless you can
defend a specific confirm-rate number; the honest default is to publish the counts
and the thresholds, no aspirational rate (the sample is tiny). If you DO add a
target, freeze it here and mark it display-only exactly like AOTC.

**Verify**: `python -m pytest -q tests/test_call_up_receipts.py` — the existing
`summary` assertions still pass (you only ADDED keys). Validator (Step 4) green.

### Step 4: Validator accepts + shape-checks maturation

In `scripts/validate_valucast_call_up_receipts.py`:
1. In `_validate_call_up`, for RECEIPTS only (not misses — pass a flag or check `label == "receipt"`), require `row.get("maturation_status") in {"PENDING", "CONFIRMED", "DECAYED"}`, else a problem `f"{label} {index} maturation_status must be PENDING/CONFIRMED/DECAYED"`.
2. In `validate_file`, check `summary["maturation"]` is a dict with integer `pending`/`confirmed`/`decayed` whose sum equals `len(receipts)` (every receipt resolves to exactly one bucket) — problem otherwise.

**Verify**: `python scripts/validate_valucast_call_up_receipts.py` → exit 0
against the freshly built artifact. Temporarily hand-edit one receipt's
`maturation_status` to `"BOGUS"` in a copy and point `--path` at it → it FAILS
naming that row; discard the copy.

### Step 5: Render the chip (behind the existing hold)

`app.py` `_build_receipts_page_context` (`:7087`): add
`"maturation": summary.get("maturation") or {"pending": 0, "confirmed": 0, "decayed": 0}`
to the returned dict.

`templates/receipts.html`: in the AHEAD list row (after the `ahead` chip at `:77`),
add a status chip driven by `p.maturation_status`, e.g.:
```jinja
{% if p.maturation_status == 'CONFIRMED' %}<span class="trend-chip buys-chip">confirmed ✅</span>
{% elif p.maturation_status == 'DECAYED' %}<span class="trend-chip">cup of coffee</span>
{% else %}<span class="trend-chip">pending</span>{% endif %}
```
(reuse existing chip classes — do NOT invent new CSS unless a class genuinely
doesn't exist; match the `buys-chip`/`trend-chip` styling already on the page).
Add a one-line summary under the AHEAD `<h2>` showing the counts, e.g.
`{{ maturation.confirmed }} confirmed · {{ maturation.pending }} pending · {{ maturation.decayed }} cup-of-coffee` — only when `maturation` has any nonzero count. Keep it mobile-clean (the receipts page is a public growth surface; the CLAUDE.md mobile-first rule applies — single row, no wide table).

**Verify**: `python -m pytest -q tests/test_call_up_receipts.py -k "page or render or hold"`
→ the two existing page tests (`test_receipts_page_shows_hold_message...`,
`test_receipts_page_renders_normally_when_not_held`) still pass. RECEIPTS_HOLD
stays True, so the chip only shows once the board is unheld — that's intended.

## Test plan

Extend `tests/test_call_up_receipts.py` (model on the existing 22 tests):

1. **`_mlb_workload` reader** (Step 1): tmp snapshot dir, cumulative G across two
   dates, a dual hitter+reliever row for one pitcher → max games + reliever IP
   returned; missing dir → `{}`.
2. **Resolver — PENDING before horizon**: a receipt with `actual_call_up_date`
   14 days before `today` → `"PENDING"` regardless of workload.
3. **Resolver — CONFIRMED by games**: past 60d, hitter with `games >= 20` → `"CONFIRMED"`.
4. **Resolver — CONFIRMED by IP**: past 60d, pitcher with `ip >= 20.0`, `games` under bar → `"CONFIRMED"`.
5. **Resolver — DECAYED (off roster, under bar, past 60d)**: past 60d, hitter
   `games = 4`, mlbam id NOT in `roster_lookup` → `"DECAYED"`.
6. **Resolver — slow accumulator stays PENDING**: past 60d but under 90d, under
   bar, mlbam id IN `roster_lookup` → `"PENDING"`.
7. **Resolver — 90d terminal DECAY**: past 90d, under bar, ON roster → `"DECAYED"`
   (final look resolves on the bar alone).
8. **Append-only floor**: `prior_status="CONFIRMED"` with today's workload BELOW
   the bar and player off the roster → still `"CONFIRMED"` (never reverts).
9. **End-to-end idempotence**: build once with a workload map that confirms a row,
   feed the resulting artifact back as `existing_log`, rebuild with a workload map
   that would now say DECAYED → the row stays `"CONFIRMED"`, and
   `summary["maturation"]["confirmed"]` unchanged. (This is the receipts-INCREMENTAL
   contract check the house rules demand.)
10. **Summary sum invariant**: `pending + confirmed + decayed == receipt_count`.
11. **Seed maturity**: a seed row (no `actual_call_up_date`) past 60d with a
    confirming workload → `"CONFIRMED"` (anchor falls back to `call_up_date`).

Final: `python -m pytest -q` all green, then
`git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`.

## Done criteria (grep-checkable)

- [ ] `python -m pytest -q` exits 0; the pytest byproduct file is restored.
- [ ] `grep -n "MATURATION_HORIZON_DAYS\|MATURATION_FINAL_DAYS\|CONFIRM_HITTER_GAMES\|CONFIRM_PITCHER_IP" prospects/call_up_receipts.py` → all four constants defined.
- [ ] `grep -n "_maturation_status\|_mlb_workload" prospects/call_up_receipts.py` → both defined and called inside `build_call_up_receipts`.
- [ ] `grep -n "prior_status\|CONFIRMED" prospects/call_up_receipts.py` → the append-only floor (`prior_status == "CONFIRMED"` early-return) is present.
- [ ] `grep -n "maturation" prospects/call_up_receipts.py` → `summary["maturation"]` + `definitions.maturation` (with a `"frozen"` stamp) present.
- [ ] `grep -n "maturation_status" scripts/validate_valucast_call_up_receipts.py` → validator enforces the enum + the sum invariant.
- [ ] `grep -n "maturation_status\|maturation\b" templates/receipts.html` → per-row chip + summary line present.
- [ ] `grep -n "maturation" app.py` → passed through `_build_receipts_page_context`.
- [ ] `git status` shows only the 5 in-scope files modified; nothing under `data/` staged.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- **It is before 2026-07-13.** This plan's execution window is post-7/13 — STOP and report.
- `prospects/call_up_receipts.py`'s `build_call_up_receipts` return/summary shape no longer matches the `:734` excerpt (someone refactored the summary first) — re-read and reconcile before writing.
- The actuals-snapshot archive rows no longer key mlbam id at `row["metadata"]["mlbam_id"]`, or the stats stop being cumulative (verify the Pratt-style growth on two dated files before trusting the reader) — the maturation evidence source has changed; STOP.
- Any change you'd need to make lands inside `prospects/ahead_of_consensus.py` or `scripts/build_ahead_of_consensus_scorecard.py` — those are FROZEN. If maturation appears to require touching AOTC scoring, you've mis-scoped it; STOP.
- A receipt row lacks BOTH `actual_call_up_date` and `call_up_date` (no anchor) — the resolver returns PENDING, but if this is widespread it means the row shape drifted; note it, don't force a status.

## Maintenance notes

- **The thresholds are pre-registered and frozen.** When the first rows mature
  (~2026-09-09) and the confirm/decay split looks off, the honest move is NOT to
  retune 60/90 or the counting bars — it's to document what you learned and, if a
  change is truly warranted, bump `SIGNAL_VERSION` and freeze the NEW thresholds
  with a new date, keeping the old ones on record (same as AOTC v1 → v2). Silent
  tuning after seeing outcomes destroys the accountability the whole layer exists for.
- **Why the actuals snapshot, not roster-days**: the dated roster-status archive
  is thin (no `profiles`), so cumulative MLB games/PA/IP from the actuals snapshot
  is the only honest per-player workload signal in the repo. If a real dated
  roster archive with profiles ever lands, roster-days could become a cleaner
  "stuck" signal — but that's a future change, frozen-and-versioned like the rest.
- **Two-way / DH-ing pitchers**: the max-across-rows logic in `_mlb_workload` is
  load-bearing (Owen Murphy is the live proof case). If a future snapshot format
  splits pitchers differently, re-verify the reader against a known pitcher before
  trusting DECAYED calls.
- **Append-only is a promise, not a convenience**: reviewer scrutiny should
  confirm no code path can flip a CONFIRMED row back to PENDING/DECAYED across a
  rebuild — test #9 guards this, but the `prior_status` plumbing from `existing_log`
  is where it could silently break if the merge order changes.
