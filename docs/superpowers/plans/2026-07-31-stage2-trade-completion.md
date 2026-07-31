# Stage 2 Trade Completion Implementation Plan

**Goal:** Verify the shipped league-aware trade analyzer and preserve each
day's existing research-only prospect league-adapter output for the registered
future Stage 2 evaluation.

**Constraints:** No score, rank, value, trade math, model flag, workflow
dispatch, public claim, or Plan 034 result changes.

## Task 1: Add failing archive tests

**Files:**

- Modify: `tests/test_prospect_league_adapters.py`

Add tests proving that `run_adapters`:

1. writes the serving artifact unchanged;
2. writes an exact compact archive at `<archive_dir>/<generated-date>.json`;
3. reports `archive_changed=False` on an identical same-day rerun;
4. atomically replaces only that date when the payload changes; and
5. preserves the `research_only`, `feeds_live_value: false`, and
   `is_dynasty_value: false` contract.

Run:

```powershell
python -m pytest tests/test_prospect_league_adapters.py -q
```

Expected first result: failure because `run_adapters` does not yet accept or
write an archive directory.

## Task 2: Reuse the existing atomic archive pattern

**Files:**

- Modify: `prospects/adapters.py`
- Modify: `scripts/build_prospect_league_adapters.py` only if its existing
  result output needs the new archive fields

Add one `ARCHIVE_DIR`, one small `archive_adapters` function matching
`prospects.rank_v1.archive_rank`, and the minimum `run_adapters` wiring.
Derive the archive date from `generated_at` in UTC. Serialize the exact payload
compactly and atomically. Return `archive_path` and `archive_changed`.

Run the Task 1 tests until green.

## Task 3: Commit the archive in the daily refresh

**Files:**

- Modify: `.github/workflows/daily-public-data.yml`
- Modify: `tests/test_public_data_refresh.py`

First add a failing contract assertion for:

```text
data/prediction_archive/valucast_prospect_league_adapters
```

Then add that single directory to the existing explicit `git add` list beside
the current adapter artifact. Do not alter workflow triggers, permissions,
ordering, timeout, or dispatch behavior.

Run:

```powershell
python -m pytest tests/test_public_data_refresh.py -q
```

## Task 4: Validate the existing trade analyzer

Do not edit trade code unless a test exposes a real contract failure.

Run the focused league-aware trade tests in `tests/test_app.py`, including
legacy parity, depth, MLB-only preset, prospect/mixed fail-closed behavior,
inert context controls, invalid fallbacks, guard cases, and page/PNG/cache
parity. Then run a 390x844 browser check of the live-equivalent local page.

## Task 5: Final verification

Run:

```powershell
python -m pytest tests/test_prospect_league_adapters.py tests/test_public_data_refresh.py -q
python -m pytest -q
git diff --check
git status --short
```

Review the final diff against the approved design. Confirm the existing Stage
2 readiness artifact and all frozen model/publication files are unchanged.
Commit in logical units and push only after all checks pass.
