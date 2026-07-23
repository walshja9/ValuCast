# Stage 2 Quality-Starts Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce a complete, reconciled, research-only QS sidecar for the
exact committed prospect input snapshot without changing live inputs, models,
ranks, values, or publication behavior.

**Architecture:** Add one importable builder script. Reuse
`scraper.mlb_actuals.fetch_game_logs` and `derive_qs_from_games`, collapse
pitcher rows to `(mlbam_id, season)`, use the existing completed-season GS
artifact to skip proven relievers, and write one input-hash-bound validation
artifact atomically. Tests inject synthetic game logs; the real run uses the
existing bounded-retry StatsAPI client.

**Tech Stack:** Python standard library, existing scraper helpers, pytest.

## Global Constraints

- Preserve the model freeze and failed-decay flag.
- Preserve the pitcher publication veto.
- Do not edit `prospect_model_inputs.json` or
  `mlb_prospect_seasons_cache.json`.
- Do not change Stage 1, Rank v1, values, caps, Role Watch, workflows, public
  copy, or production serving.
- Do not add dependencies or a new package-level abstraction.
- Do not push, merge, deploy, or dispatch workflows during implementation.

---

### Task 1: Lock the pure sidecar contract with RED tests

**Files:**
- Create: `tests/test_stage2_quality_starts.py`
- Create later: `scripts/build_stage2_quality_starts.py`

- [ ] **Step 1: Add a complete synthetic happy-path test**

The fixture must include:

- duplicate team and aggregate rows for one player-season;
- a completed-season starter with missing QS;
- a completed-season zero-start pitcher with missing QS;
- a completed-season starter with an existing QS value;
- a current-season positive-IP row; and
- a current-season game after the bound cutoff.

Assert:

- one output row per `(mlbam_id, season)`;
- maximum duplicate IP is used without summing;
- zero-start rows do not call the fetcher;
- current games after the cutoff do not count;
- existing and derived QS values reconcile;
- rows are deterministically sorted;
- coverage reports every raw row resolved; and
- the input dictionaries remain unchanged.

- [ ] **Step 2: Add fail-closed tests**

Cover:

- conflicting existing QS values on duplicate rows;
- completed-season game-log GS mismatch;
- derived QS mismatch against an existing QS value;
- exhausted fetch failure; and
- a checkpoint whose input hash does not match the current build.

- [ ] **Step 3: Run RED**

```powershell
python -m pytest tests/test_stage2_quality_starts.py -q
```

Expected: collection fails because
`scripts.build_stage2_quality_starts` does not exist.

---

### Task 2: Implement the minimum pure builder

**Files:**
- Create: `scripts/build_stage2_quality_starts.py`
- Modify only as tests require: `tests/test_stage2_quality_starts.py`

- [ ] **Step 1: Reuse the existing QS code**

Import:

```python
from scraper.mlb_actuals import derive_qs_from_games, fetch_game_logs
```

Do not copy the innings parser, retry client, endpoint, or QS formula.

- [ ] **Step 2: Add the input collector**

Collapse pitcher entries from `historical_mlb_seasons` by
`(mlbam_id, season)`. Retain:

- maximum IP;
- the set of non-null existing QS values;
- raw source-row count.

Record a blocker when the existing QS set has more than one value.

- [ ] **Step 3: Add the derivation loop**

For each unique player-season:

- use completed-season GS when present;
- skip fetch and set zero only for proven no-start/zero-IP cases;
- otherwise fetch regular-season pitching game logs;
- filter current-season games at the input cutoff;
- count starts from the filtered log;
- call the existing QS derivation helper;
- reconcile completed-season starts and existing QS;
- record explicit blockers on failure; and
- emit no resolved row for a failed identity.

- [ ] **Step 4: Add deterministic report construction**

Return the schema from the approved design with:

- input path, SHA-256, and cutoff;
- coverage counts;
- reconciliation details;
- sorted rows;
- blockers and `ready`/`blocked` status; and
- a content hash calculated without the `content_sha256` field.

- [ ] **Step 5: Run GREEN**

```powershell
python -m pytest tests/test_stage2_quality_starts.py -q
```

Expected: all focused tests pass.

---

### Task 3: Add resumable, atomic CLI behavior

**Files:**
- Modify: `scripts/build_stage2_quality_starts.py`
- Modify: `tests/test_stage2_quality_starts.py`

- [ ] **Step 1: Test checkpoint and output behavior**

Add a temporary-directory test proving:

- successful fetch results persist in the checkpoint;
- a matching checkpoint avoids another fetch;
- a mismatched checkpoint hash is ignored;
- the final JSON is written to a temporary sibling then replaced; and
- neither input file changes.

- [ ] **Step 2: Add the CLI**

Support only:

```text
--input
--history
--output
--checkpoint
--delay
```

Default to the approved input, history, and validation artifact paths. When
`--checkpoint` is omitted, use an input-hash-specific file in
`tempfile.gettempdir()`.

Requests run serially with the specified short delay. Save the checkpoint
after each successful request. Write the final artifact atomically.

- [ ] **Step 3: Verify focused GREEN**

```powershell
python -m pytest tests/test_stage2_quality_starts.py -q
```

---

### Task 4: Build and inspect the sealed real artifact

**Files:**
- Create generated: `data/validation/valucast_stage2_quality_starts.json`

- [ ] **Step 1: Record production-input hashes before the run**

```powershell
Get-FileHash data/prospects/prospect_model_inputs.json -Algorithm SHA256
Get-FileHash data/prospects/raw/mlb_prospect_seasons_cache.json -Algorithm SHA256
```

- [ ] **Step 2: Run the resumable backfill**

```powershell
python scripts/build_stage2_quality_starts.py
```

Expected: approximately 3,019 official game-log requests on the July 23 input.
The checkpoint makes interruption safe.

- [ ] **Step 3: Inspect, do not rationalize**

Require:

- `status == "ready"`;
- no blockers or reconciliation mismatches;
- exact input hash match;
- 5,283 unique resolved player-seasons on the July 23 snapshot;
- 6,296 post-join source rows with QS on the July 23 snapshot; and
- a deterministic content hash.

If any expectation differs, stop and report the actual result. Do not weaken a
gate or edit a source fact to force readiness.

- [ ] **Step 4: Prove production inputs are byte-identical**

Repeat the two `Get-FileHash` commands and compare exact values.

---

### Task 5: Final verification and logical commits

**Files:**
- `docs/superpowers/specs/2026-07-23-stage2-quality-starts-backfill-design.md`
- `docs/superpowers/plans/2026-07-23-stage2-quality-starts-backfill.md`
- `scripts/build_stage2_quality_starts.py`
- `tests/test_stage2_quality_starts.py`
- `data/validation/valucast_stage2_quality_starts.json`

- [ ] **Step 1: Run focused and adjacent tests**

```powershell
python -m pytest `
  tests/test_stage2_quality_starts.py `
  tests/test_prospect_realized_value_readiness.py `
  tests/test_valucast_raw_input_builder.py -q
```

- [ ] **Step 2: Run hygiene checks**

```powershell
git diff --check
git status --short
```

Only the named files may differ.

- [ ] **Step 3: Commit in two logical commits**

1. plan/spec documentation;
2. builder, tests, and sealed artifact.

Do not push until separately authorized.

## Success Condition

The selected input snapshot has a complete, official, reconciled QS sidecar;
the focused and adjacent tests pass; and the production inputs, model, ranks,
values, workflows, and publication gates remain unchanged.
