# Stage 2 Realized-Value Readiness Design

Date: 2026-07-23
Status: approved design; implementation not started

## Decision

Build a new research-only Stage 2 readiness audit that consumes the validated
quality-starts sidecar in memory and reports three separate questions:

1. Does the historical outcome store satisfy the incumbent coverage policy for
   all hitter and pitcher 7x7 categories?
2. Does the incumbent model use a direct 7x7 impact target?
3. Can the historical study reproduce the information that would have been
   available at each original decision date?

The QS sidecar is expected to make the first answer yes. It does not change the
other two answers.

The existing readiness artifact and the spent normalized-production evidence
chain remain immutable. The new audit must not rerun, reinterpret, or overwrite
either one.

## Why a separate audit is needed

The existing readiness audit correctly blocks realized-value regret when:

- the model artifact declares a missing pitcher category;
- the incumbent impact target is not direct 7x7; or
- exact prospective replay is not reconstructable.

Before the QS backfill, those conditions were all true at once. The new
`valucast_stage2_quality_starts` sidecar resolves the data-coverage condition
for the July 23 input snapshot, but the existing audit reads the frozen model
contract's `missing_pitcher_categories` declaration. Mutating that old report
would blur two different facts:

- the historical outcome data now contain the complete category evidence; and
- the incumbent model was still built with a non-direct target that omitted
  QS.

The correct response is a new additive artifact that reports both facts
plainly.

## Existing behavior that remains frozen

The following must remain byte-for-byte or behaviorally unchanged:

- `audit_realized_value_readiness(...)`;
- `data/validation/valucast_prospect_realized_value_readiness.json`;
- the normalized-production registered look and its result;
- `data/models/valucast_prospect_model.json`;
- the prospect input contract and raw caches; and
- every live score, rank, value, card, cap, Role Watch result, and publication
  decision.

The new audit is not a second look at the registered challenger. It is a
readiness and data-contract check for future Stage 2 research.

## Minimal implementation seam

Extend `prospects/realized_value_readiness.py` with one additive public
function:

```python
audit_stage2_realized_value_readiness(
    contract,
    model_artifact,
    qs_sidecar,
    *,
    contract_sha256,
)
```

The function may reuse the existing readiness audit for identity, cohort, and
replay facts. It must independently evaluate category evidence after the QS
join instead of copying the model artifact's declared missing categories.

Add one manual builder:

```text
scripts/build_stage2_realized_value_readiness.py
```

Extend:

```text
tests/test_prospect_realized_value_readiness.py
```

Write one new committed artifact:

```text
data/validation/valucast_stage2_realized_value_readiness.json
```

No new package, dependency, workflow, or generalized artifact framework is
needed.

## Authoritative inputs

The audit consumes:

1. the exact bytes of
   `data/prospects/prospect_model_inputs.json`;
2. `data/models/valucast_prospect_model.json`; and
3. `data/validation/valucast_stage2_quality_starts.json`.

The builder computes the prospect-input SHA-256 itself and passes it into the
pure audit. A caller-supplied hash without the source bytes is insufficient for
the committed builder.

## QS sidecar validation

The audit must fail closed unless the sidecar:

- has schema `valucast_stage2_quality_starts`;
- has the supported version;
- has status `ready`;
- contains no blockers;
- names the same prospect-input path;
- contains the exact prospect-input SHA-256 computed by the builder;
- has a cutoff equal to the contract's `current.fetched_date`;
- contains one row per `(mlbam_id, season)`;
- has a valid recomputed `content_sha256`;
- contains nonnegative integer `games_started` and `quality_starts`;
- never has `quality_starts > games_started`; and
- joins to every pitcher season in `historical_mlb_seasons`.

Extra sidecar rows outside the contract universe must be disclosed and block
the audit. Missing rows must be listed by identity and block the audit.

Team-split and aggregate source rows may share one player-season QS result.
That is expected and must not be treated as a sidecar duplicate.

## In-memory enrichment

The audit creates an in-memory view of
`historical_mlb_seasons` and attaches `qs` by `(mlbam_id, season)` to every
pitcher row.

It must not:

- write an enriched prospect input;
- change an existing QS value in the source contract;
- write to the MLB history caches; or
- treat a failed join as zero.

For completed seasons, an existing source QS that differs from the validated
sidecar is a conflict and blocks. For the current season, a difference must
appear in the sidecar's validated `current_season_values_superseded`
disclosure; the cutoff-bound sidecar value is authoritative for the in-memory
view and the difference does not block. Any undisclosed current-season
difference blocks. The builder does not repair source data.

## Separate readiness findings

### 1. Outcome evidence

`outcome_evidence` evaluates the fields available in the in-memory historical
outcomes, independent of how the incumbent model target was constructed.

The canonical categories remain:

Hitters:

- R
- HR
- RBI
- SB
- AVG
- OPS
- SO

Pitchers:

- SO
- QS
- SV+HLD
- ERA
- WHIP
- K/BB
- L

For `sv_hld`, both `sv` and `hld` must be present.

Coverage must reuse the incumbent target's existing evidence policy:

- hitter reference seasons require at least 150 PA;
- pitcher reference seasons require at least 20 IP; and
- a category is active when its populated reference-season count is at least
  80% of the best-covered category for that role.

These thresholds come from `IMPACT_REFERENCE_MIN` and
`IMPACT_CATEGORY_COVERAGE`; implementation must reuse those constants rather
than copy new numbers. This is a readiness audit of whether all seven
canonical categories are usable under the standing target contract. It does
not claim that every raw season row contains every field.

The report includes all role-season counts, eligible reference-season counts,
per-category populated counts, the coverage threshold, and the resulting
active and missing categories. `outcome_evidence.status` is `ready` only when
identity, sidecar, join, and all-seven-category activation pass.

The audit may count coverage over the full historical store because it is not
fitting a model or calculating performance. A future evaluator must still
build percentile references inside each training fold; this audit does not
authorize the incumbent's global reference construction.

### 2. Incumbent impact target

`incumbent_impact_target` reports the frozen model artifact as it exists. In
the July 23 artifact this remains:

- `direct_7x7: false`; and
- QS absent from the target used to build the incumbent.

The new outcome evidence must not rewrite that historical fact. The blocker
`impact_target_not_direct_7x7` remains until a separately registered,
validated challenger establishes an eligible direct target.

### 3. Prospective replay

`prospective_replay` preserves the existing finding:

- the retrospective store is reconstructed from completed seasons;
- the precise information set available at each original decision date is not
  reconstructable; and
- exact prospective replay is not ready.

The blocker `exact_prospective_replay_not_reconstructable` remains.

## Readiness labels

The report uses explicit, non-interchangeable labels:

- `retrospective_direct_7x7_evidence_ready` is true when the historical
  outcomes have complete, validated 7x7 evidence after the sidecar join.
- `incumbent_direct_7x7_target_ready` is true only when the frozen model
  artifact itself declares and supports a direct 7x7 target.
- `exact_prospective_replay_ready` preserves the replay finding.
- `realized_value_regret_ready` is true only when all three are true and no
  other blocker remains.

For the validated July 23 inputs, the expected result is:

```text
retrospective_direct_7x7_evidence_ready = true
incumbent_direct_7x7_target_ready = false
exact_prospective_replay_ready = false
realized_value_regret_ready = false
overall status = blocked
```

This is not a failed audit. It is an honest record that the QS data problem is
cleared and two different research-design problems remain.

## Output artifact

The artifact has this logical shape:

```json
{
  "schema": "valucast_stage2_realized_value_readiness",
  "version": "1.0.0",
  "status": "blocked",
  "inputs": {
    "prospect_contract": {
      "path": "data/prospects/prospect_model_inputs.json",
      "sha256": "...",
      "cutoff_date": "2026-07-23"
    },
    "model_artifact": {
      "path": "data/models/valucast_prospect_model.json"
    },
    "quality_starts_sidecar": {
      "path": "data/validation/valucast_stage2_quality_starts.json",
      "content_sha256": "..."
    }
  },
  "outcome_evidence": {
    "status": "ready",
    "retrospective_direct_7x7_evidence_ready": true,
    "hitter": {
      "complete": true,
      "season_rows": 5864,
      "eligible_reference_seasons": 2862,
      "populated_reference_seasons": {
        "r": 2862,
        "hr": 2862,
        "rbi": 2862,
        "sb": 2862,
        "avg": 2862,
        "ops": 2862,
        "so": 2862
      }
    },
    "pitcher": {
      "complete": true,
      "season_rows": 6296,
      "eligible_reference_seasons": 3806,
      "populated_reference_seasons": {
        "so": 3806,
        "qs": 3806,
        "sv_hld": 3806,
        "era": 3806,
        "whip": 3806,
        "k_bb": 3806,
        "l": 3806
      }
    }
  },
  "incumbent_impact_target": {
    "direct_7x7": false,
    "incumbent_direct_7x7_target_ready": false
  },
  "prospective_replay": {
    "exact_prospective_replay_ready": false
  },
  "realized_value_regret_ready": false,
  "blockers": [
    "impact_target_not_direct_7x7",
    "exact_prospective_replay_not_reconstructable"
  ],
  "content_sha256": "..."
}
```

The counts illustrate the expected July 23 result and are not schema constants
or permanent thresholds.

All lists and mappings must use deterministic ordering. The artifact content
hash excludes only the `content_sha256` field and uses the repository's
existing canonical JSON encoding convention.

## Blocker policy

When the QS sidecar validates and 7x7 fields are complete,
`missing_pitcher_category:qs` must not appear in the new artifact.

The new artifact must retain:

- `impact_target_not_direct_7x7`; and
- `exact_prospective_replay_not_reconstructable`.

Additional blockers are added for:

- malformed or stale sidecar metadata;
- sidecar content-hash mismatch;
- missing, extra, or duplicate player-season identities;
- invalid QS or GS values;
- QS conflicts with source rows;
- incomplete hitter or pitcher category fields;
- invalid historical identities; and
- cohort identity or role conflicts.

No blocker is converted to a warning merely to reach a ready status.

## Non-goals

This work does not:

- define a direct 7x7 scoring formula;
- define a realized-value regret formula;
- train, rebuild, or promote a model;
- rerun the normalized-production registered look;
- spend another registered look or multiplicity budget;
- modify the old readiness artifact;
- change any live score, rank, value, card, or publication behavior;
- change the model freeze, failed-decay flag, or pitcher publication veto;
- authorize a public performance or superiority claim;
- wire a builder into CI or daily workflows; or
- publish or deploy anything.

## Verification

Tests must prove:

- the existing audit's output is unchanged;
- the existing committed readiness artifact remains byte-identical;
- a valid sidecar supplies QS to every pitcher row in memory;
- all hitter and pitcher 7x7 categories can satisfy the standing coverage
  policy while the overall audit remains blocked;
- QS no longer appears as a missing category after a valid join;
- the incumbent direct-target blocker remains;
- the exact-replay blocker remains;
- invalid schema, version, status, input hash, cutoff, or content hash blocks;
- missing, extra, duplicate, or invalid sidecar rows block;
- completed-season or undisclosed current-season QS conflicts block;
- incomplete non-QS categories block;
- the new report and content hash are deterministic; and
- only the new readiness artifact is written.

Before and after implementation, hash:

```text
data/validation/valucast_prospect_realized_value_readiness.json
data/prospects/prospect_model_inputs.json
data/models/valucast_prospect_model.json
```

The hashes must remain unchanged.

## Success condition

The work succeeds when ValuCast can prove, with one deterministic and
input-bound research artifact, that all retrospective 7x7 categories satisfy
the standing coverage policy for the July 23 snapshot while still refusing to
claim that the incumbent impact target or exact prospective validation is
ready.
