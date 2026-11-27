# Plan 004: Make the daily pipeline fail loud, never lie — season/offseason guards + gates for ungated surfaces

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 72e68864..HEAD -- scripts/refresh_milb_season_stats.py scraper/refresh.py scraper/mlb_actuals.py scripts/validate_public_data_freshness.py scripts/validate_mlb_roster_status.py mlb/roster_status.py .github/workflows/roster-pulse.yml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M (five S-sized fixes batched)
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug (pipeline honesty)
- **Planned at**: commit `72e68864`, 2026-07-08

## Why this matters

ValuCast's brand promise is that the freshness stamp never lies and a bad build never publishes. A 7/8 audit found five verified holes in that promise, two with calendar dates attached: (1) the MiLB tiny-refresh guard will fail-close the ENTIRE daily publish every day of the offseason (~Oct–May) because it has no escape hatch; (2) the actuals fetcher hardcodes `season=2026` while re-stamping `as_of=today`, so after Jan 1 the site would serve 2026 stats labeled fresh and the validator structurally cannot catch it; (3) the two newest public surfaces (prospect comps, /gaps) and the core prospect board artifact publish with zero freshness/row-count validation — the exact "succeeds-but-empty" class that already bit this pipeline once; (4) the 4pm roster-pulse workflow can commit+deploy a degraded roster artifact (feeds board graduation + the AOTC active-MLB guard) because it runs no roster validation; (5) a statsapi 200-with-empty-roster response for one team silently overwrites that team's good cached roster.

## Current state

Files and their roles:

- `scripts/refresh_milb_season_stats.py` — MiLB stats fetch; `_assert_not_tiny_refresh` (lines 288–298) raises with no bypass:
  ```python
  def _assert_not_tiny_refresh(payload: dict, path: Path) -> None:
      prior = _prior_row_count(path)
      if prior <= 0:
          return
      rows = _row_count(payload)
      floor = max(500, int(prior * 0.5))
      if rows < floor:
          raise ValueError(
              "refusing to write tiny MiLB stats refresh: "
              f"rows={rows} prior_rows={prior} floor={floor}"
          )
  ```
- `scraper/blend.py:205` — the repo's existing escape-hatch convention, COPY THIS PATTERN:
  ```python
  if os.environ.get("VALUCAST_SKIP_BLEND_ZERO_GUARD") == "1":
      return  # end-of-season ROS feeds can legitimately zero out; see below
  ```
  and its raise message ends with `"(legitimate end-of-season ROS zeroes? set VALUCAST_SKIP_BLEND_ZERO_GUARD=1)"` — the flag is discoverable from the failure.
- `scraper/refresh.py:30-39` — `def refresh(..., season: int = 2026)` then `as_of = date.today().isoformat()`. The daily workflow (`.github/workflows/daily-public-data.yml:110`) invokes `python -m scraper.refresh` argless, so the literal is production. `scraper/mlb_actuals.py` — `fetch_actuals(season: int = 2026)` (:245), `fetch_qs(..., season: int = 2026)` (:257), `build_actuals(season: int = 2026, ...)` (:274).
- `scripts/validate_public_data_freshness.py` — the freshness gate. `dated_artifacts` list at :105-141 (34 artifacts, each `(PATH_CONST, "generated_at"|"as_of")`); `min_rows` dict at :145-150:
  ```python
  min_rows = {
      MLB_DYNASTY_LAYER: ("players", 300),
      MLB_ROSTER_STATUS: ("profiles", 300),
      PROSPECT_MODEL_V07: ("candidates", 500),
      PROSPECT_PEAK_PROJECTION: ("projections", 500),
  }
  ```
  and the loop at :151-170 does `n = len(payload.get(key) or [])` per entry. The actuals check at :184-197 asserts only `metadata.as_of == today` (re-stamped daily → can never catch a stale season). Neither `valucast_prospect_comps.json`, `valucast_consensus_gap.json`, nor `valucast_prospect_rank_v1.json` appears anywhere in the file.
- Artifact shapes (verified 7/8): `data/models/valucast_prospect_comps.json` → dict key `players` (104 entries today), has `generated_at`. `data/models/valucast_consensus_gap.json` → list keys `higher` (15) and `lower` (15), has `generated_at`. `data/models/valucast_prospect_rank_v1.json` → list key `board` (2,803 rows), has `generated_at`.
- `scripts/validate_mlb_roster_status.py` — contract validator; only floor today is `active_roster_profile_count > 0` (fully-empty check). The daily freshness gate separately floors profiles at 300, but the roster-pulse workflow never runs that gate.
- `.github/workflows/roster-pulse.yml` — 20:00 UTC workflow; steps run `build_mlb_roster_status.py`, `build_call_up_pulse.py`, then ONLY `validate_call_up_pulse.py`, then commit `valucast_mlb_roster_status.json` + `mlb_roster_status_cache.json` + archive + pulse, then deploy.
- `mlb/roster_status.py` — `_fetch_active_roster` (:69-77) returns `[]` on a 200-with-empty-roster; the per-team loop (:275-288) calls `_load_or_fetch(key=f"team:{team_id}:rosterType=active", cache=cache, fetcher=..., refresh=refresh, ...)` and `_load_or_fetch` (:101-115) unconditionally overwrites `queries[key] = {"fetched_at": ..., "rows": rows}` with whatever the fetcher returned, then `_save_cache` persists it. A blocker is raised only when profiles is FULLY empty (:187-188). `build_mlb_roster_status(...)` accepts injectable `teams_fetcher` / `roster_fetcher` — use these in tests.

Repo conventions: stdlib-only scripts (no new deps); guard env flags named `VALUCAST_SKIP_*` with the flag named in the raise message; tests are plain pytest, no fixtures beyond tmp_path.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Targeted tests | `python -m pytest -q tests/test_refresh_milb_season_stats.py tests/test_refresh.py tests/test_mlb_roster_status.py tests/test_public_data_refresh.py` | all pass |
| Freshness gate self-check | `python scripts/validate_public_data_freshness.py` | exit 0 against today's committed artifacts (run only on a day the daily refresh has already landed; if it fails on artifacts you did NOT touch, that's pre-existing — note it, don't chase it) |
| Roster validator | `python scripts/validate_mlb_roster_status.py` | exit 0, prints `active_profiles=<n>` with n ≥ 300 |
| Full suite (final gate) | `python -m pytest -q` | all pass; then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` (pytest dirties it as a byproduct — NEVER commit it) |

## Scope

**In scope** (the only files you should modify):
- `scripts/refresh_milb_season_stats.py`
- `scraper/refresh.py`, `scraper/mlb_actuals.py`
- `scripts/validate_public_data_freshness.py`
- `scripts/validate_mlb_roster_status.py`
- `mlb/roster_status.py`
- `.github/workflows/roster-pulse.yml`
- Tests: `tests/test_refresh_milb_season_stats.py`, `tests/test_refresh.py`, `tests/test_mlb_roster_status.py` (extend existing files)

**Out of scope** (do NOT touch):
- `prospects/ahead_of_consensus.py`, `scripts/build_ahead_of_consensus_scorecard.py` — the AOTC scorecard rules are FROZEN (pre-registered 7/2) until the ~7/13 gate unlock.
- `scraper/blend.py` — it is the pattern to copy, not a file to change.
- `.github/workflows/daily-public-data.yml` — the gates you add run inside the existing validate step; no workflow edit needed there.
- Any builder under `scripts/build_*.py` — gates live in validators, not builders.

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**: master auto-deploys valucast.app via Render, and pushing also triggers workflow changes live. Commit locally; the reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — parallel sessions leave untracked files). Stage each file explicitly.
- Commit message style (from git log): short imperative subject, e.g. `Fail loud on stale actuals season; gate comps, gaps, and board artifacts`.

## Steps

### Step 1: MiLB tiny-refresh escape hatch

In `scripts/refresh_milb_season_stats.py`, add to the top of `_assert_not_tiny_refresh`:
```python
if os.environ.get("VALUCAST_SKIP_MILB_TINY_GUARD") == "1":
    return  # offseason/season-rollover windows legitimately go tiny
```
(add `import os` if absent) and extend the raise message with `" (legitimate offseason/rollover shrink? set VALUCAST_SKIP_MILB_TINY_GUARD=1)"`.

**Verify**: `python -m pytest -q tests/test_refresh_milb_season_stats.py` → all pass, including your 1 new test (flag set → tiny write allowed; use existing `test_write_refuses_tiny_refresh_against_existing_file` as the pattern, `monkeypatch.setenv`).

### Step 2: Derive the actuals season; record it; validate it

1. `scraper/refresh.py`: change `season: int = 2026` to `season: int | None = None` and resolve at the top of `refresh()`:
   ```python
   season = season or int(os.environ.get("VALUCAST_ACTUALS_SEASON") or date.today().year)
   ```
   (add `import os`). Update the `print(f"Fetching 2026 actuals...")` literal to use `{season}`.
2. Same `2026` → `None`-with-derivation treatment for the three defaults in `scraper/mlb_actuals.py` (`fetch_actuals`, `fetch_qs`, `build_actuals`) — or have them require the season from the caller; pick whichever keeps existing tests passing with the smallest diff.
3. In `refresh()`, add `"season": season` to the `metadata` dict written to `metadata.json`.
4. In `scripts/validate_public_data_freshness.py`, where REDRAFT_METADATA is loaded (it's in `dated_artifacts` with field `as_of`), add a check: `metadata["season"]` must equal `int(expected_date[:4])` unless env `VALUCAST_ACTUALS_SEASON` is set. Missing `season` key → problem (fail loud; every fresh build will write it after this change).

**Verify**: `python -m pytest -q tests/test_refresh.py` → all pass, including 2 new tests (season derived from today's year; env override respected).

### Step 3: Freshness + row floors for comps, gaps, and the board

In `scripts/validate_public_data_freshness.py`:
1. Add three path constants next to the existing ones: `VALUCAST_PROSPECT_COMPS`, `VALUCAST_CONSENSUS_GAP`, `VALUCAST_PROSPECT_RANK_V1` (all under `data/models/`).
2. Append all three to `dated_artifacts` with field `generated_at`.
3. Refactor `min_rows` values from a single `(key, floor)` tuple to a tuple of pairs, so one artifact can floor multiple keys, and update the checking loop accordingly. Then add:
   - comps: `(("players", 20),)` — dict, `len()` works the same
   - gap board: `(("higher", 3), ("lower", 3))`
   - rank_v1: `(("board", 1500),)`

**Verify**: `python scripts/validate_public_data_freshness.py` → exit 0 on today's artifacts. Then a self-test: temporarily point one floor at an impossible value (e.g. `board ≥ 999999`), rerun, confirm it FAILS with the named artifact, revert. Also `python -m pytest -q tests/test_public_data_refresh.py` → all pass.

### Step 4: Roster floor + roster validation in the pulse workflow

1. In `scripts/validate_mlb_roster_status.py`, add after the `active_roster_profile_count` positivity check: profiles count < 300 → problem `f"active roster has {n} profiles (< 300) — degraded fetch"` (match the freshness gate's existing 300 floor for this artifact).
2. In `.github/workflows/roster-pulse.yml`, add a step after "Rebuild same-day call-up pulse" and before the commit step:
   ```yaml
   - name: Validate roster status
     run: python scripts/validate_mlb_roster_status.py
   ```

**Verify**: `python scripts/validate_mlb_roster_status.py` → exit 0 against the committed artifact. `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/roster-pulse.yml'))"` → no output (valid YAML). If pyyaml is unavailable, use `python -m pip show pyyaml` to check first; if absent, verify indentation matches the sibling steps by eye and note it.

### Step 5: Keep prior roster rows when a refetch comes back empty

In `mlb/roster_status.py`, in the per-team loop inside the refresh function (around :275-288): before calling `_load_or_fetch`, capture `prior_rows = list((cache.get("queries", {}).get(key) or {}).get("rows") or [])`. After it returns, if `fetched and not rows and prior_rows`: restore `rows = prior_rows`, write the prior rows back into `cache["queries"][key]` (preserving the old `fetched_at` if practical), and increment a `degraded_teams` counter. After the loop, if `degraded_teams > 5`, raise `RuntimeError` naming the count (a league-wide statsapi outage should fail the pulse, not publish 25 stale teams silently); if `1 <= degraded_teams <= 5`, print a warning line naming the teams.

**Verify**: `python -m pytest -q tests/test_mlb_roster_status.py` → all pass, including 2 new tests using the injectable `roster_fetcher`: (a) one team returns `[]` on refresh with a warm cache → that team's prior rows survive in both the payload and the saved cache; (b) 6+ teams return `[]` → raises.

## Test plan

- `tests/test_refresh_milb_season_stats.py`: +1 (skip-flag honored).
- `tests/test_refresh.py`: +2 (season derived; env override).
- `tests/test_mlb_roster_status.py`: +2 (empty-team keeps prior; mass-empty raises).
- Validator changes are exercised by running the validator scripts against committed artifacts (Step 3/4 verify lines) plus existing `tests/test_public_data_refresh.py`.
- Final: `python -m pytest -q` all green, then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`.

## Done criteria

- [ ] All targeted test files pass; full `python -m pytest -q` passes.
- [ ] `grep -n "2026" scraper/refresh.py scraper/mlb_actuals.py` shows no hardcoded season default left (docstrings/comments OK).
- [ ] `grep -n "VALUCAST_SKIP_MILB_TINY_GUARD" scripts/refresh_milb_season_stats.py` → 2+ hits (check + message).
- [ ] `grep -n "valucast_prospect_comps\|valucast_consensus_gap\|valucast_prospect_rank_v1" scripts/validate_public_data_freshness.py` → all three present.
- [ ] `grep -n "Validate roster status" .github/workflows/roster-pulse.yml` → 1 hit, positioned before the commit step.
- [ ] `git status` shows only in-scope files modified; the pytest byproduct file is restored.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The `min_rows` loop in `validate_public_data_freshness.py` no longer matches the excerpt (someone refactored it first).
- `metadata.json`'s writer has moved out of `scraper/refresh.py`.
- Any existing test asserts the literal `season == 2026` in a way that contradicts derivation (report it — do not silently rewrite its meaning).
- The roster refresh function's cache flow doesn't match the `_load_or_fetch` excerpt.

## Maintenance notes

- **Offseason posture is still an open product decision** (what should valucast.app serve in December?). This plan converts silent-wrong into loud-fail + documented flags; when the offseason arrives, Alex chooses: set the skip flags + freeze posture, or build a real offseason mode. The Jan-1 behavior after Step 2 is: actuals for the new year come back empty → the existing "no player rows" gate fails loud → decision forced, nothing silently stale.
- The comps floor (20) is far under today's 104 but comps coverage is gate-driven and grows; if a future model change legitimately shrinks coverage below 20, lower the floor consciously in the same commit.
- Reviewer scrutiny: Step 5's cache-restore path — confirm the saved cache file never ends up with an empty `rows` list for a team that previously had players.
