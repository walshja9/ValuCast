# Stage 2 Quality-Starts Backfill Design

Date: 2026-07-23
Status: approved design; implementation not started

## Decision

Build a research-only quality-starts sidecar from official MLB game logs. Key
the facts by `(mlbam_id, season)`, bind the artifact to one exact prospect input
snapshot, and fail closed when coverage or reconciliation is incomplete.

The sidecar may be consumed only by the Stage 2 validation path. It must not
change the prospect model, Rank v1, public values, pitcher caps, Role Watch,
publication decisions, or any production input artifact.

## Why this is needed

The Stage 2 realized-value audit cannot evaluate the complete pitcher 7x7
category set because quality starts are missing from part of the MLB outcome
history.

The committed July 20 readiness artifact reports:

- 6,292 pitcher-season rows;
- 3,808 rows with quality starts; and
- 2,484 rows without quality starts.

The July 23 committed prospect input has already moved to:

- 6,296 pitcher-season rows;
- the same 3,808 rows with quality starts; and
- 2,488 rows without quality starts.

Those 2,488 raw missing values collapse to 2,127 unique player-seasons because
the source can include team splits and aggregate season rows. Of the unique
missing player-seasons, the completed-season MLB history identifies 801 with at
least one start and 1,018 with no starts. The remaining 308 do not have a
matching completed-season workload row, primarily because 306 are from the
current 2026 season.

Under the approved fetch policy, the July 23 snapshot produces 3,019 game-log
requests: 2,492 player-seasons with known starts and 527 positive-IP
player-seasons without a completed-season workload match. That request set
contains 1,691 stable completed-season QS values to check, 222 unversioned
current-season QS values to compare and disclose, and 1,106 missing values to
derive.

This drift is why the sidecar must record the exact source-input hash and
cutoff. Counts in this document are diagnostic measurements, not permanent
thresholds.

## Existing code to reuse

`scraper/mlb_actuals.py` already provides the required primitives:

- `fetch_game_logs(...)` calls the official MLB StatsAPI game-log endpoint;
- `derive_qs_from_games(...)` applies the quality-start definition;
- `normalize_ip(...)` converts baseball innings notation correctly; and
- `_fetch_json(...)` supplies bounded retries and a timeout.

The backfill must reuse these functions. It must not create a second StatsAPI
client or a second quality-start formula.

## Source and fixed definition

The source endpoint is:

```text
/api/v1/people/{mlbam_id}/stats
  ?stats=gameLog
  &group=pitching
  &season={season}
  &gameType=R
```

A game is a quality start when:

- `gamesStarted` is greater than zero;
- normalized `inningsPitched` is at least 6.0; and
- `earnedRuns` is no more than 3.

Only regular-season MLB games count. For the current season, game logs must be
filtered to dates on or before the input snapshot's `current.fetched_date`.
Completed seasons use the full regular-season log.

## Input universe and identity

The canonical universe is the unique `(mlbam_id, season)` set in
`historical_mlb_seasons` from an explicitly supplied
`data/prospects/prospect_model_inputs.json` snapshot.

Rules:

1. Parse `mlbam_id` from the existing `{mlbam_id}_pitcher` key.
2. Collapse team-split and aggregate rows to one player-season identity.
3. Block if duplicate rows contain conflicting existing `qs` values.
4. Use the maximum IP across duplicate rows as the season-total opportunity
   check; never sum team splits and an aggregate total together.
5. Never attach an aggregate QS value to only one team split.
6. Join the completed sidecar back by `(mlbam_id, season)` so every matching
   source row receives the same season total.

The builder records the SHA-256 of the complete input file and the input
snapshot date. A sidecar built for a different hash or date is invalid.

## Fetch policy

Use the smallest trustworthy request set:

- When the completed-season workload history says `GS == 0`, set `qs = 0`
  without a game-log request.
- When the workload history says `GS > 0`, fetch the game log.
- When no completed-season workload row exists but the input has positive IP,
  fetch the game log.
- When no completed-season workload row exists and the input has zero IP, set
  `qs = 0`.

An existing nonzero QS value paired with a proven zero-start season is a
conflict and blocks the artifact.

For fetched completed seasons, the number of game-log starts must equal the
aggregate `gs` value in
`data/mlb/mlb_history_pitching_seasons.json`. A mismatch blocks the artifact.

For fetched completed-season rows that already have an existing `qs`, the
derived count must match it exactly. This checks the derivation against every
stable existing value in the request set, not a hand-picked sample. A mismatch
blocks the artifact.

The current-season log is evaluated only through the bound cutoff date. It is
not compared with the completed-season workload artifact. Existing
current-season QS values have no row-level source timestamp and may be older
than the input cutoff, so they are not a valid equality reference. The
cutoff-bound official game-log value supersedes them in this research sidecar;
any difference is recorded under `current_season_values_superseded` and does
not alter the production cache.

Requests run serially with a fixed short inter-request delay. Existing bounded
retry behavior remains authoritative; exhausting it records a blocker instead
of silently skipping the player-season.

## Output artifact

Write:

```text
data/validation/valucast_stage2_quality_starts.json
```

The artifact has this logical shape:

```json
{
  "schema": "valucast_stage2_quality_starts",
  "version": "1.0.0",
  "status": "ready",
  "source": {
    "provider": "MLB StatsAPI",
    "stat": "gameLog",
    "group": "pitching",
    "game_type": "R",
    "definition": "GS > 0 and IP >= 6.0 and ER <= 3"
  },
  "input": {
    "path": "data/prospects/prospect_model_inputs.json",
    "sha256": "...",
    "cutoff_date": "2026-07-23"
  },
  "coverage": {
    "source_rows": 6296,
    "unique_player_seasons": 5283,
    "resolved_player_seasons": 5283,
    "post_join_rows_with_qs": 6296
  },
  "validation": {
    "existing_values_checked": 1691,
    "existing_value_mismatches": [],
    "current_season_values_superseded": [
      {
        "mlbam_id": 123456,
        "season": 2026,
        "existing": 1,
        "derived": 3
      }
    ],
    "games_started_mismatches": [],
    "duplicate_value_conflicts": []
  },
  "rows": [
    {
      "mlbam_id": 123456,
      "season": 2024,
      "games_started": 24,
      "quality_starts": 13,
      "provenance": "derived_game_log"
    }
  ],
  "blockers": [],
  "content_sha256": "..."
}
```

The example counts show the July 23 input shape and are not schema constants.
Rows are sorted by `mlbam_id`, then season. Allowed provenance values are:

- `existing_qs`;
- `derived_game_log`; and
- `no_starts`.

The final artifact is written atomically only after all validations finish.
Network progress may be checkpointed in the operating-system temporary
directory. The checkpoint must include the bound input hash and may not be
reused when that hash changes.

## Readiness behavior

`status` is `ready` only when:

- every unique pitcher player-season is resolved;
- the join gives every raw pitcher-season row a QS value;
- every fetched completed-season start count reconciles;
- every checked completed-season existing QS value matches;
- every superseded current-season value is disclosed;
- no duplicate identity has conflicting existing QS values; and
- no request or parse failure remains.

Otherwise `status` is `blocked`, the artifact lists explicit blockers, and the
Stage 2 evaluator must refuse it. Missing values are never silently converted
to zero unless the no-start rule is proven.

Completing this sidecar clears only the QS coverage defect. It does not by
itself make the overall realized-value study ready: the existing
`impact_target_not_direct_7x7` and
`exact_prospective_replay_not_reconstructable` blockers remain separate.

## Stage 2 boundary

The first implementation ends after building and validating the sidecar.
Consumption by a Stage 2 research evaluator is a later, separately reviewed
step.

The first implementation must not:

- rewrite `prospect_model_inputs.json`;
- rewrite `mlb_prospect_seasons_cache.json`;
- modify Stage 1 profiles;
- change any live rank, score, value, or card;
- change pitcher caps or the pitcher publication veto;
- change the model freeze or failed-decay flag;
- wire the builder into daily workflows; or
- publish a performance or superiority claim.

## Verification

Tests must prove:

- existing QS derivation and innings normalization are reused;
- duplicate player-season rows collapse deterministically;
- conflicting existing QS values block;
- zero-start seasons become zero without a fetch;
- started seasons use regular-season game logs;
- current-season games after the bound cutoff are excluded;
- derived starts reconcile with completed-season aggregate GS;
- completed-season existing QS mismatches block;
- unversioned current-season QS drift is disclosed and superseded by the
  cutoff-bound official game log;
- a failed or missing game log blocks;
- checkpoint data cannot cross an input hash;
- the final rows and content hash are deterministic;
- every source pitcher row resolves after the sidecar join; and
- production input files remain byte-identical.

The focused baseline before implementation is:

```text
python -m pytest \
  tests/test_prospect_realized_value_readiness.py \
  tests/test_valucast_raw_input_builder.py -q
```

It currently passes 24 tests.

## Success condition

The work is successful when one immutable, input-bound, research-only sidecar
provides a reconciled QS value for every pitcher-season in the selected
prospect input snapshot, while all live model and publication behavior remains
unchanged.
