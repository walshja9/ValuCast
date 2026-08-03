# MLB Pitcher Skill Challenger Design

**Date:** 2026-08-02
**Status:** Approved in conversation; design only
**Scope:** MLB pitchers; research-only

## Goal

Determine whether public MLB pitch-level evidence adds forward predictive value
to ValuCast's existing pitcher projection without changing opportunity, role,
rank, value, publication, or any served surface during research.

The challenger answers one question:

> Does a compact set of pitch shape, location/execution, and arsenal features
> improve next-season pitcher skill forecasts beyond the incumbent ValuCast
> pitcher projection?

This is not a public Stuff+ clone and not a reproduction of Stockyard. ValuCast
owns the source queries, aggregation, code, targets, validation, and resulting
artifact. No external proprietary score, formula, output, or training label is
consumed.

## Decision

Use one incremental challenger over the incumbent. Do not create three separate
Shape, Command, and Arsenal models before the combined evidence proves useful.
Do not publish a descriptive 100-scale merely because it can be calculated.

The selected architecture is deliberately narrow:

```text
public MLB Statcast pitches
    -> compact pitcher-season feature rows
    -> fold-local correction to incumbent rate forecasts
    -> next-season K/BF and BB/BF predictions
    -> existing FIP reconstruction for evaluation context
    -> research-only evidence artifact
```

## Existing architecture reused

- `projections/models/marcel_pitcher.py` remains the incumbent and authority.
- `projections/backtest/pitching_harness.py` remains the source of qualification
  floors, role handling, and scorecard metric definitions.
- `projections/models/pitcher_role.py` remains the sole role estimate.
- The dependency-free ridge implementation pattern already used in
  `prospects/model.py` is reused; no ML dependency is added.
- Existing projection and public-data artifacts remain byte-identical unless a
  later, separately authorized promotion occurs.

## Approaches considered

### 1. Incremental correction to the incumbent — selected

Use the incumbent forecast as the baseline feature and let pitch evidence make
a small, regularized correction. This directly tests incremental information,
limits overfitting, and falls back naturally when coverage is absent.

### 2. Separate Shape, Command, and Arsenal models — rejected for v1

This creates multiple looks and an immediate combination problem. The feature
families remain available for registered ablations inside the single look, but
they do not become independent public metrics.

### 3. Display-only descriptive indices — rejected for v1

They would be easy to market but would not show that the information improves a
forecast. Public presentation follows evidence, not the reverse.

## Data contract

### Source and cutoff

- Public MLB Statcast pitch records, 2015 through the latest completed season.
- Each pitcher-season row uses only pitches thrown through that season's final
  regular-season date.
- Outcomes come strictly from the following completed MLB season.
- The cutoff is season completion; partial-season data is excluded from the
  retrospective evaluation.

### Storage

Raw pitch files are streamed or processed in bounded season chunks and are not
committed. The repository stores only:

- compact pitcher-season aggregates;
- source/query parameters;
- season coverage counts;
- a canonical feature-contract version; and
- provenance sufficient to reproduce the aggregation.

This avoids recreating a multi-gigabyte raw-pitch warehouse on the local drive.

### Identity and exclusions

- Join only by MLBAM ID.
- Exclude position-player pitching appearances.
- Preserve two-way-player pitching rows under their MLBAM ID and pitcher role.
- Require a registered minimum pitch count before a correction is eligible.
- Rows below that floor or missing required features fall back exactly to the
  incumbent forecast.

## Feature contract

All features are pitcher-season aggregates. Continuous transforms,
standardization, pitch-type reference values, and imputation are fitted inside
each training fold.

### Incumbent anchor

- Incumbent projected K/BF.
- Incumbent projected BB/BF.
- Existing continuous starter probability.

### Pitch shape

- Pitch-type usage.
- Velocity.
- Horizontal and vertical movement.
- Release position and extension.
- Spin rate only where coverage is adequate and missingness is explicit.
- Shape values expressed relative to pitch type and pitcher handedness.

### Location and execution

- Zone, heart, edge, and waste rates.
- Horizontal and vertical location dispersion by pitch type.
- Called-strike and swinging-strike evidence as observed outcomes, not as
  proprietary command grades.

### Arsenal construction

- Number of meaningfully used pitch types.
- Usage concentration.
- Pairwise velocity and movement separation.
- Fastball/secondary usage balance.

Pitch labels must be normalized through one explicit mapping. Unknown or newly
introduced labels remain `other`; they are never silently coerced into an
existing pitch family.

## Targets and model

Fit two dependency-free ridge corrections:

1. next-season strikeouts per batter faced; and
2. next-season walks per batter faced.

Each target model includes the incumbent forecast and the registered feature
set. The correction output is bounded to a registered, training-derived range
so a sparse or extreme pitch profile cannot create an implausible forecast.

The existing FIP-derived ERA path remains unchanged. Challenger K/BF and BB/BF
may be substituted only inside the research evaluator to measure downstream
K/9, BB/9, ERA, and WHIP effects. Opportunity and IP are never predicted by
this challenger.

## Validation design

### Folds

- Rolling-origin folds by target season.
- Training seasons strictly precede the target season.
- All transformations and ridge fits are fold-local.
- One registered retrospective look; feature-family ablations are reported
  within that look and do not create additional promotion opportunities.

### Comparators

- **Control:** current ValuCast pitcher projection.
- **Challenger:** control plus the pitch-evidence correction.
- **Context:** same-season persistence and archived Steamer forecasts where the
  exact same player, outcome, and window are available.

External forecasts are contextual benchmarks only and never training inputs.

### Primary gate

The challenger must satisfy all conditions:

1. at least 2% lower aggregate out-of-sample MAE than Control across K/9,
   BB/9, ERA, and WHIP;
2. no individual primary endpoint worsens by more than 1%;
3. a majority of target-season folds beat Control;
4. starter and reliever cohorts each avoid a regression greater than 1%; and
5. at least 250 qualified pitcher-seasons across scored folds.

### Prospective confirmation

A retrospective pass is not promotion. It authorizes only a dated shadow
forecast for the next untouched completed season. Any live-source, rank, value,
or public superiority change requires that prospective result plus a separate
owner decision and disclosure.

## Research artifact

Write one fail-closed artifact containing:

- registration and feature-contract versions;
- source seasons and provenance;
- fold definitions and sample counts;
- Control and Challenger metrics by target and fold;
- SP/RP cohort results;
- feature-family ablations;
- coverage and fallback counts;
- gate result;
- `research_only: true`;
- `feeds_live_projection: false`;
- `feeds_rank_or_value: false`;
- `feeds_pitcher_publication: false`; and
- `claim_eligible: false` until prospective confirmation is complete.

No player-level challenger forecast is served publicly during the retrospective
phase.

## Failure behavior and edge cases

- Missing source season: fail the build; never substitute partial data.
- Duplicate pitcher-season identity: fail.
- Missing coverage for a player: exact incumbent fallback.
- Pitch-type classification drift: report it and route unknown types to `other`.
- Role change: evaluate under the existing continuous starter probability; do
  not invent a challenger role model.
- Injured or inactive pitchers: the skill forecast may exist internally, but
  availability and opportunity remain authoritative elsewhere.
- Zero projected IP: no challenger publication and no downstream value effect.

## Explicit non-goals

- No AAA or MiLB transfer model in v1.
- No public Shape, Command, Arsenal, Stuff+, or Pitching+ score.
- No Stockyard data, code, labels, or reverse engineering.
- No XGBoost or new dependency.
- No injury, workload, role, or playing-time model.
- No change to the model freeze, failed-decay flag, pitcher cap, publication
  veto, Role Watch, ranks, or values.

## Tests

The implementation must prove:

1. deterministic aggregation from a small pitch fixture;
2. MLBAM-only identity and position-player-pitching exclusion;
3. pitch-label normalization and explicit `other` handling;
4. exact fallback to Control below the coverage floor;
5. fold-local transformations with no target-season leakage;
6. walk-forward target alignment to the following season;
7. deterministic ridge predictions and bounded corrections;
8. exact gate math and cohort reporting;
9. artifact boundary flags remain fail-closed; and
10. existing projection, rank, value, and publication artifacts do not change.

## Success condition

The work succeeds when ValuCast can state privately, from a committed and
reproducible artifact, whether public pitch evidence improves its MLB pitcher
skill forecast. A negative result is a complete result: the incumbent remains
untouched and no public metric is created.
