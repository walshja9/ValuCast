# Registered Study: Stage 1 Outcome Proof Maturation Re-Run (v2)

**Study id:** `stage1_outcome_proof_maturation_v2`
**Registered:** 2026-08-14 (this document is committed and pushed BEFORE any
study result is computed or viewed; the push timestamp and commit hash are the
registration record).
**Study type:** Research-only, one look. No score, rank, value, cap, Role
Watch, buy, publication, or workflow change ships from this study. The only
public surface change it can produce is the model-registry verdict edit its
pre-registered resolution mapping dictates, applied as its own reviewed PR.
**Fulfils:** the `resolution_condition` registered on
`universal_prospect_model_pitchers` in
`data/models/valucast_model_registry.json` (PR #53): re-run the Stage 1
outcome proof when the 2020/2021 cohorts mature and resolve the
pitcher-vs-neighbors claim terminally.
**Owner approvals (recorded before registration):** 2026-08-14, in session —
(a) the four-rule resolution mapping below, including rule 4's bounded final
increment; (b) a negative outcome resolves the neighbors claim as
**REJECTED**, with the prior-beating result stated alongside.

## Prior knowledge (disclosed)

The following was already observed before this registration and is NOT a
study result:

- Proof v1 (`data/validation/valucast_stage1_outcome_proof.json`, PR #46,
  seed 34041, cohorts 2016–2019): hitters beat both baselines on all three
  ordering metrics with delta CIs excluding zero (n=1,379). Pitchers beat
  the level/age prior (supported_retrospective) but are indistinguishable
  from the 25-historical-neighbors baseline: deltas straddle zero with
  slightly negative point estimates (e.g. Spearman −0.020 [−0.059, +0.019];
  n=1,522).
- Input-contract counts checked on 2026-08-14 (marginal distributions only —
  no model prediction for any 2021 row has ever been computed or viewed):
  the 2020 cohort has **0 rows** (the 2020 MiLB season was canceled), so the
  registered condition's "2020 and 2021" reduces to **2021 only** as a
  matter of fact, not choice. The 2021 cohort has 751 input rows; after the
  model's standard eligibility filters (role, outcome present, mlbam_id,
  age ≤ 25) it contributes **386 hitters** (310 bust / 64 role / 12 star)
  and **365 pitchers** (309 bust / 49 role / 7 star). The 2021 cohort's
  four-year outcome horizon closed with the completed 2025 season.
- The 2022 cohort (772 input rows) closes its horizon when the 2026 season
  completes (~Oct 2026). It is NOT admitted to this look; it defines the
  terminal backstop in rule 4.

All gates below are set on quantities not yet computed: every out-of-fold
prediction for the 2021 fold, and every pooled metric, delta, and interval
on the expanded pool.

## Frozen design

### Evaluation — identical machinery, one parameter

- Rebuild the out-of-fold evidence with `mature_through=2021` passed as a
  research parameter through `prospects.model.outcome_oof_rows` (a thin
  pass-through to the existing `_historical_rows(..., mature_through=...)`
  parameter). The live constant `prospects/model.py MATURE_THROUGH = 2019`
  gates served training labels and is **not** edited — changing it is a
  model change under the freeze. A regression test asserts the constant and
  the served default behavior are untouched.
- Fold rule unchanged (`_walk_forward`): test cohort T trains only on
  cohorts < T. The 2021 fold trains on ≤2019 outcomes (2020 is empty,
  harmlessly). Cross-cohort per-player de-dup keeps the earliest cohort,
  so adding 2021 leaves every ≤2019 fold population byte-identical.
- **Registered population pins (halt to owner adjudication on any
  mismatch, because the daily refresh rewrites the input contract and
  historical rows can legitimately drift between registration and run):**
  (a) a pre-prediction eligibility check — before any model output is
  computed — requires the 2021 eligible counts to equal the registered
  **386 hitters / 365 pitchers**; (b) after OOF construction, pooled totals
  must equal **1,765 hitters / 1,887 pitchers** over exactly the five
  closed cohorts 2016–2019 and 2021; (c) the maturation OOF artifact's
  per-role fold `identity_sha256` values for 2016–2019 must equal those in
  the committed live artifact
  `data/models/valucast_outcome_oof_scores.json`, so the v1 comparison
  basis cannot silently shift. A halt reports the deviation with no metric
  viewed; adjudication precedes any look.
- Same metrics (Spearman rho, Kendall tau-b, ROC AUC), same baselines
  (level/age prior; 25 historical neighbors), same claim policy (≥3 closed
  cohorts, n≥250 per role, delta 95% CI must exclude zero), same
  player-clustered bootstrap with **10,000** resamples, via the unchanged
  `prospects.stage1_outcome_proof` module.
- **Fresh seed: 36061.** Forbidden (held, spent, exploratory, or reserved
  elsewhere): 34041 (proof v1), 35021 (Plan 035), and Plan 035's pinned
  forbidden list — 28013, 28014, 28015, 28017, 29001, 29016, 31013, 31017,
  32019, 33021, 34021, 34027, 34031, 72127.

### Artifact plumbing (fixed before the run)

- The live artifacts `data/models/valucast_outcome_oof_scores.json` and
  `data/models/valucast_probability_reliability.json` reproduce the served
  gate and are validated (not rebuilt) by the daily refresh. They are
  **not touched**. The maturation run writes its own committed research
  inputs instead:
  `data/validation/valucast_outcome_oof_scores_maturation2021.json` and
  `data/validation/valucast_probability_reliability_maturation2021.json`,
  built by the same builders with the same schemas. The reliability
  builder currently hardcodes the live OOF path in `source.path`; the
  machinery PR parameterizes that source path (validator-compatible — the
  schema checks only `source.sha256`) so the maturation artifact records
  its true provenance instead of falsely citing the live file.
- The `backtest` and `scorecard` inputs are claim-time archives whose
  content is independent of outcome maturity, but their committed live
  copies are rewritten by the daily and shadow workflows. The run
  therefore snapshots them as frozen copies —
  `data/validation/valucast_prospect_dynasty_backtest_maturation2021.json`
  and
  `data/validation/valucast_ahead_of_consensus_scorecard_maturation2021.json`
  — and the proof's recorded sources cite the snapshots.
- The committed proof `data/validation/valucast_stage1_outcome_proof.json`
  and its report `docs/stage1-outcome-proof.md` regenerate **in place**
  (the schema's `evaluation.mature_through_cohort` becomes 2021); v1
  remains in git history; the registry evidence path stays stable.
- In the same run PR, the canonical builder
  `scripts/build_stage1_outcome_proof.py` repoints **all four** inputs at
  the frozen maturation/snapshot artifacts above and its default seed at
  36061, so the committed proof remains exactly reproducible and the
  drift-safe reproduction tests stay live permanently instead of skipping
  whenever a daily-mutable input advances.

### Resolution mapping (mechanical; pitcher model-minus-neighbors pooled deltas)

"Clears" = the artifact's own `evidence_status` at
`historical.roles.pitcher.metrics.<metric>.model_minus_baseline.historical_neighbors_25`
is `supported_retrospective` (pooled model-minus-neighbors delta 95% CI
excludes zero in the model's favor under the claim policy) — evaluated on
**all three** ordering metrics (`spearman_rho`, `kendall_tau_b`,
`roc_auc`), the same bar the hitter verdict was earned on. The mapping
below **partitions the outcome space**: rule 4 is the residual, so every
possible result lands in exactly one rule.

1. **Clears all three** → `universal_prospect_model_pitchers` resolves
   **VALIDATED**; the registry edit cites the regenerated proof.
2. **Any metric's delta CI entirely below zero** → the beyond-neighbors
   claim resolves **REJECTED now** (owner-approved framing: REJECTED for
   the neighbors claim, with the prior-beating result stated alongside in
   the verdict reason).
3. **Any straddling metric with point estimate ≤ 0** → **REJECTED now**
   (as rule 2).
4. **Otherwise** (not all three clear, no CI entirely below zero, no
   straddler with point ≤ 0 — e.g. all three straddle with positive
   points, or a mix of cleared and positively-straddling metrics) → one
   final, already-scheduled increment: the identical evaluation re-runs
   once when the 2022 cohort matures (~Oct 2026, adding roughly 380
   pitcher outcomes), under seed **37083** — pinned now, verified fresh
   against the repo on 2026-08-14, and reserved exclusively for that run
   so no seed can be shopped at resolution time. After that run: clears
   all three → VALIDATED; anything else → REJECTED. **No further
   extensions under this registration.** A future claim requires a
   materially changed pitcher model and a new registration.

Ties/edge cases: a metric that cannot be computed for a reason not covered
above voids the verdict for owner adjudication rather than defaulting to
pass. The study executor reports raw measured quantities; verdict
application is mechanical from this table.

### Relationship to the registered condition (refinements stated, not smuggled)

This mapping refines the `resolution_condition` pinned on the registry
entry in three ways, each disclosed here before any result exists:

- The pinned condition says "delta interval excluding zero" in the
  singular without naming a metric; this registration requires the bar on
  **all three** ordering metrics — strictly harder to pass, matching
  exactly how the hitter verdict was earned. Under this registration a
  partial result (some metrics clear, none negative) is rule 4, not
  VALIDATED.
- The pinned condition declares "no third outcome" but defines nothing for
  a straddling interval; rules 3 and 4 close that gap mechanically (a
  non-positive straddle resolves REJECTED now; the bounded 2022 increment
  is a scheduled completion of the same look, not a new claim).
- The pinned condition reserves "owner then decides REJECTED vs.
  remains-PROVISIONAL" for resolution time; the owner has now made that
  decision in advance (REJECTED framing, recorded above), which supersedes
  the deferral.

The resolution PR updates the pinned condition text and its lock test
(`tests/test_app.py`, which currently asserts the condition mentions
"2020") to the terminal state this mapping dictates.

### Hitter monitoring clause (evidence cannot be unseen)

The re-run necessarily recomputes hitter results on the expanded pool.
Hitter deltas are reported as **monitoring, not a new claim**. If **any of
the six hitter delta CIs** (3 metrics × 2 baselines:
`level_age_prior` and `historical_neighbors_25` under `spearman_rho`,
`kendall_tau_b`, `roc_auc`) has a **lower bound ≤ 0** on the five-cohort
pool, the hitters VALIDATED verdict returns to owner review with public
disclosure — pre-committing now that a weakened result is surfaced, not
rationalized. Six simultaneous 95% intervals make this trigger deliberately
hair-triggered in the false-alarm direction; since the consequence is
review and disclosure, never an automatic verdict change, that asymmetry
is intended.

If hitter support holds, the hitters `verdict_reason` evidence citation
updates to the regenerated artifact's figures in the resolution PR — a
citation refresh mandated by this registered re-run (the old figures no
longer exist in the cited file), not a discretionary rewording.

### Descriptive-only outputs (cannot rescue or veto the gate)

Per-cohort tables including 2021 alone; evidence-band deciles on the
expanded pool; hitter monitoring detail. No subset selection, no
additional looks, no new baselines, no metric substitutions.

## Boundaries

Research-only. `public_superiority_authorized` stays `false` in the
artifact. No serving importer may reference the maturation artifacts; the
existing production-importer test extends to them. The registry test
pinning the pitcher entry (byte-identical reason + resolution condition)
updates in the resolution PR to pin whichever terminal state the mapping
dictates.

## Execution protocol

1. This registration is committed and pushed (with independent adversarial
   review recorded in the PR) BEFORE any study code runs.
2. Machinery lands with the registration: the `mature_through`
   pass-through in `outcome_oof_rows`; the reliability builder's
   `source.path` parameterization; normalization of the tie-sort key
   shared by the proof's evidence bands and the reliability deciles (a
   latent str-vs-int sort divergence that could cause a spurious
   reconciliation halt on the expanded pool); and the runner
   `scripts/run_stage1_maturation_rerun.py`, which asserts seed freshness
   against the forbidden list, asserts `MATURE_THROUGH == 2019` untouched,
   enforces the registered population pins (the eligibility pin
   pre-prediction), snapshots the backtest/scorecard inputs, and applies
   the mapping mechanically. Machinery-PR regression tests use synthetic
   fixtures only — CI must not compute real 2021 predictions before the
   registered look. CI green, merged.
3. One look: the runner executes once; artifacts regenerate; results are
   reported to the owner with the mapping applied mechanically.
4. The registry verdict edit lands as its own reviewed PR per the mapping.

## Sign-off record

- [x] Owner: resolution mapping incl. rule 4's bounded final increment
      (approved 2026-08-14, in session)
- [x] Owner: REJECTED framing on a negative outcome (approved 2026-08-14,
      in session)
- [x] Independent adversarial review completed 2026-08-14 (fresh-context
      reviewer; verdict REGISTER AFTER FIXES). All findings addressed in
      this text: exhaustive residual rule 4; rule-4 seed 37083 pinned now;
      population pins bound to registered numbers + fold identity hashes;
      reliability source-path parameterization named; hitter trigger
      restated as lower-bound ≤ 0 on any of six deltas; all four proof
      inputs frozen/snapshotted so reproduction tests stay live;
      condition refinements disclosed; pre-prediction eligibility check;
      synthetic-fixture-only machinery tests; tie-sort normalization.
      Full findings recorded in the registration PR.
- [ ] Registration commit pushed BEFORE the run; then one look; then the
      resolution PR
