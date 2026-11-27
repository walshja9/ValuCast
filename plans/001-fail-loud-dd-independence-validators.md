# Plan 001: Fail-loud validators so a ValuCast score/value can never silently come from DD or external boards

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c8d8a22..HEAD -- web/public_snapshot_store.py quality/valucast_governor.py prospects/rank_v1.py scripts/build_public_dynasty_snapshot.py tests/test_public_dynasty_snapshot.py tests/test_valucast_quality_governor.py tests/test_public_surfaces_smoke.py scripts/run_daily_public_build.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (do this FIRST — it guards every later DD-removal change)
- **Category**: tests / tech-debt
- **Planned at**: commit `c8d8a22`, 2026-06-17

## Why this matters

ValuCast's public promise is "fully independent of Diamond Dynasties (DD)." Today
that promise is **asserted, not enforced**. Every model artifact writes
`source_policy: {dd_values_used: False, dd_ranks_used: False}` as a hardcoded
literal, and the only validation (`web/public_snapshot_store.py:103-105`) checks
that the *literal* equals `False` — it never inspects the actual per-row
`score_source`/`value_source`. So if a future change made a prospect's score come
from a DD rank/value, every gate would still pass green: the builder keeps
writing `False`, the validator accepts it, and the governor's published
independence flags are likewise static literals backed by no scan.

This plan converts "we wrote False" into "the build fails loud if any served
score/value originates from DD or an external/consensus/market board." It is the
keystone for the DD-removal work in Plan 002: once these guards exist, no later
change can quietly reintroduce a DD valuation path. The checks are additive over
data that is already clean, so they pass on today's snapshot and only fire on a
regression.

This also enforces the product decision that external prospect boards
(CFR/HKB/Pipeline) stay strictly comparison-only: they may be displayed but must
never influence ValuCast rank, value, buy score, peak projection, or model score.

## Current state

- `web/public_snapshot_store.py` — loads and validates the public snapshot.
  `validate_public_snapshot_payload(payload)` (lines 93-148) is data-only, runs
  both in the store load path AND in `scripts/validate_public_dynasty_snapshot.py`
  (wired into `run_daily_public_build.py` VALIDATE_STEPS). Today its only
  source-policy guard is:
  ```python
  PROHIBITED_TRUE_FLAGS = (              # lines 41-46
      "dd_values_used",
      "dd_ranks_used",
      "external_rankings_used_for_score",
      "market_values_used_for_score",
  )
  ...
  source_policy = payload.get("source_policy") or {}   # lines 102-105
  for flag in PROHIBITED_TRUE_FLAGS:
      if source_policy.get(flag) is not False:
          problems.append(f"source_policy.{flag} must be false")
  ```
  Per-row loop already exists at lines 116-131 (it checks `rank` is int, `value`
  is numeric, dedups ids/identities). The snapshot row carries
  `value_source` (top-level) and, for prospects, `score_source` — see below.

- `scripts/build_public_dynasty_snapshot.py:392-394` — every row's served value
  provenance:
  ```python
  "value": row.get("score"),
  "value_scale": "0_100_valucast_prospect_score",
  "value_source": row.get("score_source"),
  ```
  and prospects also carry top-level `"score_source": row.get("score_source")`
  (line 401). Legit ValuCast `score_source` values in production include
  `universal_fallback`, `identity_only_fallback`, `prospect_pedigree_v0_7`
  (see `quality/valucast_governor.py` `FALLBACK_SCORE_SOURCES`/`PEDIGREE_SCORE_SOURCE`).
  A DD regression would look like `score_source = "dd_dynasty_value"`.

- `quality/valucast_governor.py` — data-only quality gate (pure functions over
  snapshot dicts; no HTTP). Check helper and registry:
  ```python
  def _check(check_id: str, passed: bool, message: str, **metrics: Any) -> dict:   # line 119
      return {"id": check_id, "status": "passed" if passed else "blocked",
              "message": message, "metrics": metrics}
  ...
  board_checks = [                       # line 1417
      _top_mlb_value_gap(players),
      _mlb_projection_stability_outliers(players),
      ...
      _prospect_availability_risk_pricing(players),
  ]
  public_board_ready = all(check["status"] == "passed" for check in board_checks)  # line 1444
  ```
  `players` is `_player_rows(...)` (line 1397). The governor publishes static
  `source_policy: {feeds_model_score: False, ...}` at lines 1470+ that nothing
  currently derives. Models follow the `_check(...)` pattern and are appended to
  `board_checks` — a blocked check sets `ready_for_public_snapshot = False`.

- `prospects/rank_v1.py:1309-1327` — already computes the residual DD factual
  fallback counts (display path), reported but **not enforced**:
  ```python
  dd_factual_fallback = {
      "translated_valucast_owned": translated_owned,
      "translated_dd_feed_fallback": translated_dd_fallback,
      "translated_absent": translated_absent,
      "mlb_stat_line_from_dd_feed": mlb_stat_line_dd,
      "factual_path_fully_valucast_owned": translated_dd_fallback == 0 and mlb_stat_line_dd == 0,
  }
  ```
  This block is surfaced into the snapshot `validation` (the snapshot validator
  payload exposes `validation.dd_factual_fallback`). NOTE: confirm the exact key
  path with `grep -rn "dd_factual_fallback" scripts/build_public_dynasty_snapshot.py`
  before writing the ratchet (Step 3).

- Existing validator-script pattern to copy (`scripts/validate_raw_data_independence_audit.py`):
  module-level `ROOT`, a `validate_X(path) -> (payload, problems)` function, and a
  `main()` that prints `... FAILED` + each problem and `return 1`, else prints an
  OK line and `return 0`. Wired by appending a `("scripts/validate_X.py",)` tuple
  to `VALIDATE_STEPS` in `scripts/run_daily_public_build.py:74-117`.

- Existing test pattern (`tests/test_public_dynasty_snapshot.py:1045-1047`) already
  flips a flag and asserts the failure message — model new validator tests on it:
  ```python
  payload["source_policy"]["dd_values_used"] = True
  assert "source_policy.dd_values_used must be false" in validate_public_snapshot_payload(payload)
  ```

- Route/source selection (read-only context for Step 4): `app.py:332-334` sets
  the module global `dynasty_data_source` from `_select_dynasty_store(...)`; values
  today are `"valucast_public_snapshot"` (snapshot live) or `"dd_feed"` (fallback).
  Plan 002 will ADD a `"valucast_public_snapshot_stale"` value. Write the Step 4
  assertion against an allowlist of ValuCast-snapshot sources, NOT an exact
  string, so Plan 002 does not break it.

## Commands you will need

| Purpose | Command (run from repo root) | Expected on success |
|---------|------------------------------|---------------------|
| Run a test file | `python -m pytest -q tests/test_public_dynasty_snapshot.py` | all pass |
| Run governor tests | `python -m pytest -q tests/test_valucast_quality_governor.py` | all pass |
| Run smoke tests | `python -m pytest -q tests/test_public_surfaces_smoke.py` | all pass |
| Run a new validator | `python scripts/validate_dd_independence_ratchet.py` | exit 0, prints OK line |
| Run snapshot validator | `python scripts/validate_public_dynasty_snapshot.py` | exit 0 |
| Lint touched files | `ruff check <files you changed>` | exit 0 |
| Full suite (final) | `python -m pytest -q` | all pass, 2 skips OK |

## Scope

**In scope** (modify only these):
- `web/public_snapshot_store.py` (Step 1)
- `quality/valucast_governor.py` (Step 2)
- `scripts/validate_dd_independence_ratchet.py` (Step 3, create)
- `scripts/run_daily_public_build.py` (Step 3, wire the new validator into VALIDATE_STEPS)
- `data/models/dd_independence_baseline.json` (Step 3, create — the ratchet baseline)
- `tests/test_public_dynasty_snapshot.py` (Step 1 test)
- `tests/test_valucast_quality_governor.py` (Step 2 test)
- `tests/test_dd_independence_ratchet.py` (Step 3 test, create)
- `tests/test_public_surfaces_smoke.py` (Step 4 test)

**Out of scope** (do NOT touch):
- `scripts/build_public_dynasty_snapshot.py` — do not change what the builder
  emits; this plan validates existing output, it does not reshape it.
- `prospects/rank_v1.py` — `dd_factual_fallback` is already computed; only READ it.
- `app.py` selection/health/boot logic — that is Plan 002. Step 4 only ADDS a
  read-only test assertion; it must not modify `app.py`.
- The external-board panel template and `source_ranks` emission — comparison-only
  display is allowed and is handled (kept) per the product decision; this plan
  only forbids those ranks from feeding a *score*.

## Git workflow

- Branch: `advisor/001-dd-independence-validators`
- Commit per step (4 commits) or one logical commit; match the repo's terse,
  imperative message style (see `git log --oneline -5`).
- Do NOT push or open a PR. The reviewer (Fable) runs verification and decides.

## Steps

### Step 1: Derive the snapshot independence flags from real row sources

In `web/public_snapshot_store.py`, add a module constant naming the DD/external
source tokens that must never appear in a served value/score source:

```python
DD_DERIVED_SOURCE_TOKENS = (
    "dd_", "dd-", "dynasty_value", "external", "consensus",
    "market", "cfr", "hkb", "pipeline",
)
```

In `validate_public_snapshot_payload`, inside the existing per-row loop
(lines 116-131), scan each row's `value_source` and (for prospects) `score_source`:
lowercase the string and fail if it contains any token in `DD_DERIVED_SOURCE_TOKENS`.
Collect the offending row indices/sources. After the loop, if any row tripped it,
append a clear problem, e.g.
`f"players[{i}].value_source '{src}' is DD/external-derived; ValuCast scores must be ValuCast-owned"`.
Additionally, if any row tripped the scan while `source_policy.dd_values_used` is
`False`, that literal is now a lie — append
`"source_policy.dd_values_used is False but a row score is DD-derived"` so the
mismatch is impossible to miss.

**Verify**: `python -m pytest -q tests/test_public_dynasty_snapshot.py` → all pass.
Then add a regression test (model on the `1045-1047` pattern): build a valid
payload, set one prospect row's `score_source = "dd_dynasty_value"`, assert the
new problem string is returned by `validate_public_snapshot_payload(payload)`; and
assert a clean payload returns no DD-source problem. Re-run the file → all pass.

### Step 2: Add a governor row-source audit check

In `quality/valucast_governor.py`, add a data-only check function following the
`_check(...)` pattern (line 119), e.g.:

```python
def _dd_score_source_audit(players: list[dict]) -> dict:
    offenders = [
        (str(row.get("id")), src)
        for row in players
        for src in (str(row.get("value_source") or ""), str(row.get("score_source") or ""))
        if any(tok in src.lower() for tok in DD_DERIVED_SOURCE_TOKENS)
    ]
    return _check(
        "dd_score_source_audit",
        passed=not offenders,
        message=("no served score/value originates from DD or an external board"
                 if not offenders else
                 f"{len(offenders)} row score/value source is DD/external-derived"),
        offenders=offenders[:10],
        offender_count=len(offenders),
    )
```

Reuse the same token list as Step 1 — define `DD_DERIVED_SOURCE_TOKENS` once and
import it (put it in `web/public_snapshot_store.py` and import into the governor,
OR a small shared spot — pick the option that keeps the import graph clean; if the
governor must stay import-light, duplicate the tuple with a comment pointing at
the canonical copy). Append `_dd_score_source_audit(players)` to the `board_checks`
list (line 1417). A blocked check correctly flips `ready_for_public_snapshot`
False, which the snapshot validator already gates on (public_snapshot_store.py:140).

**Verify**: `python -m pytest -q tests/test_valucast_quality_governor.py` → all
pass. Add a test: feed `evaluate_quality_governor` a players list with one
`value_source = "dd_dynasty_value"` row → assert the `dd_score_source_audit` check
status is `"blocked"` and `ready_for_public_snapshot` is `False`; a clean list →
check `"passed"`. Re-run → all pass.

### Step 3: Ratchet the residual factual DD-fallback counts so they can never grow

The display path still has a measured residual DD dependency
(`validation.dd_factual_fallback.mlb_stat_line_from_dd_feed` and
`.translated_dd_feed_fallback` — see Current state). It must not silently increase.

Create `data/models/dd_independence_baseline.json` capturing today's counts
(read them from the committed snapshot's `validation.dd_factual_fallback` — get the
real numbers with
`python -c "import json;print(json.load(open('data/public/public_dynasty_snapshot.json'))['validation']['dd_factual_fallback'])"`):

```json
{
  "artifact": "dd_independence_baseline",
  "note": "Ratchet ceiling. These residual DD display-fallback counts may only DECREASE. Lower a value here only when the snapshot legitimately reduced it; never raise.",
  "max_mlb_stat_line_from_dd_feed": <today's value>,
  "max_translated_dd_feed_fallback": <today's value>
}
```

Create `scripts/validate_dd_independence_ratchet.py` (copy the structure of
`scripts/validate_raw_data_independence_audit.py`): load the public snapshot's
`validation.dd_factual_fallback` and the baseline; fail (`return 1`, print
`DD INDEPENDENCE RATCHET FAILED:` + each problem) if either count EXCEEDS its
baseline ceiling. On success print the current vs. ceiling counts and `return 0`.

Wire it into `scripts/run_daily_public_build.py` by adding
`("scripts/validate_dd_independence_ratchet.py",)` to `VALIDATE_STEPS` (after
`scripts/validate_public_dynasty_snapshot.py`, around line 104).

**Verify**: `python scripts/validate_dd_independence_ratchet.py` → exit 0, prints
counts ≤ ceiling. Add `tests/test_dd_independence_ratchet.py`: a snapshot whose
counts equal the baseline passes; a count one above the baseline fails with the
expected message. `python -m pytest -q tests/test_dd_independence_ratchet.py` →
all pass.

### Step 4: Assert the live dynasty source is ValuCast-owned (positive test)

In `tests/test_public_surfaces_smoke.py`, add a test that imports the app with a
ready snapshot fixture and asserts the served source is ValuCast-owned, not DD:

```python
import app as app_module
assert app_module.dynasty_data_source in {
    "valucast_public_snapshot", "valucast_public_snapshot_stale",
}
assert app_module.dynasty_data_source != "dd_feed"
```

Use the same import/fixture approach the existing smoke tests use (they already
import `from app import app`). If the existing smoke setup does not guarantee a
ready snapshot, assert conditionally: skip with a clear reason when
`public_snapshot_store.ready_for_live_consumers` is False, but FAIL if the source
is `"dd_feed"` regardless. The allowlist (not an exact-string equality) is
deliberate — Plan 002 adds the `_stale` source and must not break this test.

**Verify**: `python -m pytest -q tests/test_public_surfaces_smoke.py` → all pass.

### Step 5: Full-suite gate

**Verify**: `python -m pytest -q` → all pass (2 pre-existing skips are fine).
`ruff check` on every file you changed → exit 0.

## Test plan

- `tests/test_public_dynasty_snapshot.py`: clean payload → no DD-source problem;
  a row with `score_source="dd_dynasty_value"` → returns the new problem string;
  the flag-mismatch problem fires when a DD row coexists with `dd_values_used:False`.
- `tests/test_valucast_quality_governor.py`: DD-source row → `dd_score_source_audit`
  blocked + `ready_for_public_snapshot` False; clean → passed.
- `tests/test_dd_independence_ratchet.py` (new): counts == baseline pass; count >
  baseline fails. Model structurally on `tests/test_public_dynasty_snapshot.py`.
- `tests/test_public_surfaces_smoke.py`: live source is in the ValuCast allowlist
  and never `"dd_feed"`.
- Verification: `python -m pytest -q` → all pass.

## Done criteria

ALL must hold:
- [ ] `python -m pytest -q` exits 0 (pre-existing skips allowed).
- [ ] `python scripts/validate_dd_independence_ratchet.py` exits 0.
- [ ] `python scripts/validate_public_dynasty_snapshot.py` exits 0.
- [ ] New `dd_score_source_audit` appears in `board_checks` and is `passed` on the live snapshot.
- [ ] `("scripts/validate_dd_independence_ratchet.py",)` is in `VALIDATE_STEPS`.
- [ ] `ruff check` clean on every changed file.
- [ ] Only in-scope files modified (`git status`).
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report (do not improvise) if:
- The "Current state" excerpts don't match the live code (codebase drifted).
- The live snapshot already trips the new DD-source scan (`value_source`/`score_source`
  contains a banned token) — that means a real DD score leak EXISTS today; report
  it as a finding rather than weakening the check to make it pass.
- `validation.dd_factual_fallback` is not at the key path described — re-locate it
  (`grep -rn "dd_factual_fallback"`) and report the actual path before guessing.
- A token in `DD_DERIVED_SOURCE_TOKENS` causes a false positive on a legitimate
  ValuCast source name (e.g. a real source legitimately contains "market") — STOP
  and report; tighten the token, do not delete the check.

## Maintenance notes

- The `DD_DERIVED_SOURCE_TOKENS` list is a denylist; if ValuCast ever adds a new
  legitimate score source, confirm its name shares no banned token. If a future
  feature legitimately needs an external benchmark *displayed* (never scored),
  that is fine — these checks only scan `value_source`/`score_source`.
- The ratchet baseline (`dd_independence_baseline.json`) is a ceiling: lower it
  when the snapshot legitimately reduces DD fallback (e.g. after Plan 002 / the
  deferred `mlb_stat_line` ownership work), never raise it. Reaching 0 on both
  counts is the point at which `factual_path_fully_valucast_owned` becomes True.
- A reviewer should scrutinize: that the per-row scan covers BOTH `value_source`
  and prospect `score_source`, and that Step 4's assertion uses the allowlist
  (so Plan 002's `_stale` source is accepted).
