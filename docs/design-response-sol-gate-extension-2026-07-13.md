# Sol (GPT-5.6) design response — rank-gate extension (2026-07-13)

Response to docs/design-brief-sol-gate-extension-2026-07-13.md. Verified by a
4-agent adversarial battery 2026-07-13: 17 CONFIRMED / 3 PARTIAL / 0 refuted.
The BINDING text is the "Rank-gate v1 registration" section of
plans/028-pitcher-lean-model-fix.md, which corrects the 3 PARTIALs (buy_score
6.0 is a value-history discontinuity filter not a score boundary; 3-board is
the FEATURED tier standard, general floor is 2; no cross-role tier existed —
one was defined and registered) and adds the 2026-07-14 power-check amendment
(C_cross report-only; C2/C3 cut on power). This file is the design record;
where it disagrees with the registration, the registration governs.

---

Exact historical board replay is not possible from the committed data. A rank-scoring core can be replayed honestly if every current-only input is explicitly neutralized. That supports a meaningful gate for the three 028 scoring levers, but not for their interaction with live availability or roster state.

## 1. Target 1 — replay-feasibility table

Classes: **(a)** reconstructible, **(b)** current-only/anachronistic, **(c)** partially reconstructible.

| Rank input | Class | Replay finding and evidence |
|---|---:|---|
| Historical MiLB performance, age, level, role, and draft/signing facts | **(a)** | The input builder combines historical cohort facts with draft facts into `historical.rows`; the committed contract retains both feature families. [raw_input_builder.py:983](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/raw_input_builder.py:983), [prospect_model_inputs.json](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/data/prospects/prospect_model_inputs.json) |
| Out-of-fold `prospect_model` outcome/impact scores for a canonical cohort record | **(a)** | Historical records produce feature vectors and targets, and the existing walk-forward machinery fits each test cohort only from earlier cohorts. Production scoring turns the same feature families into `expected_outcome_score`, `expected_category_impact_score`, and reliability. [model.py:526](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/model.py:526), [model.py:778](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/model.py:778), [model.py:1240](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/model.py:1240) |
| Exact served-model line selection and current-line corrections | **(c)** | Production scoring selects from current rows, consults current service facts, and may compare a prior-year line with a worse current-season line. Historical cohort rows lack an exact as-of copy of that current-row pool and comparator state. [model.py:1204](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/model.py:1204), [model.py:1225](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/model.py:1225), [model.py:1294](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/model.py:1294) |
| Universal/dynasty outcome signal consumed by rank | **(a)** | The existing dynasty backtest reconstructs fold-specific predicted distributions and factual four-year outcomes from historical rows and MLB seasons. Rank converts that distribution into its universal outcome component. [dynasty_backtest.py:35](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/dynasty_backtest.py:35), [dynasty_backtest.py:56](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/dynasty_backtest.py:56), [rank_v1.py:847](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:847) |
| `rank_v1` score weights, caps, and deterministic ordering | **(a)** | These are committed code. Final ordering is by adjusted score followed by deterministic non-score tie-breakers. [rank_v1.py:127](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:127), [rank_v1.py:1065](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:1065), [rank_v1.py:2066](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:2066) |
| Exact historical candidate universe | **(c)** | Today’s universe is built from current dynasty profiles with current age and profile-presence filters. Historical cohort rows can define a fixed pseudo-universe, but not the exact board membership that existed on that date. [universe.py:197](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/universe.py:197), [universe.py:218](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/universe.py:218) |
| Role-quantile normalization pool | **(c)** | The transform itself is reproducible, but its values depend on the complete eligible hitter/pitcher pool. Active-roster and stale-profile filtering alter that pool, so only pseudo-cohort normalization is possible. [rank_v1.py:741](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:741), [rank_v1.py:1144](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:1144), [rank_v1.py:1918](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:1918) |
| Current input-row selection, `source_kind`, and factual current context | **(c)** | Rank chooses among `input_contract.current` rows and separately locates the newest current-season stat row. Historical rows preserve core stats, but not an exact historical current-row pool, fetched-date state, or source-kind fallback decision. [rank_v1.py:335](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:335), [rank_v1.py:356](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:356), [raw_input_builder.py:999](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/raw_input_builder.py:999) |
| Prior-career MiLB history used by the confidence softener | **(c)** | The loader combines the current season with accumulated card history and does not accept an as-of cutoff. The committed card history directly inspected in this run covers 2022–2026, so it cannot reconstruct prior-career state for the 2018/2019 folds. [rank_v1.py:232](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:232), [rank_v1.py:256](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:256), [milb_card_history.json](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/data/prospects/raw/milb_card_history.json) |
| Availability: sample-size/level/starter signal | **(c)** | The thresholds are reproducible and the historical rows carry sample facts, but the live calculation aggregates the latest-season row pool and chooses a display row. A historical pseudo-profile is possible; an exact profile is not. [availability.py:195](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/availability.py:195), [availability.py:210](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/availability.py:210), [availability.py:273](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/availability.py:273) |
| Availability: sample staleness | **(c)** | Season-level staleness can be approximated from cohort year and sample season. Day-level staleness requires the as-of `generated_at` and historical `sample_fetched_date`, which are not preserved for old cohorts. [availability.py:219](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/availability.py:219), [availability.py:265](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/availability.py:265), [availability.py:305](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/availability.py:305) |
| Availability: upstream Fantrax roster/availability status | **(b)** | This signal comes from current input rows. The builder reads present Fantrax availability when constructing `current`; it is not part of historical cohort rows or a dated status archive. [availability.py:384](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/availability.py:384), [availability.py:394](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/availability.py:394), [raw_input_builder.py:968](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/raw_input_builder.py:968) |
| Availability: official MLB IL/transaction state | **(b)** | The live artifact is built from official transactions through the current generated date. Crucially, its dated archive retains query and validation metadata, not player profiles, so the archive cannot reconstruct historical IL membership. [mlb/availability.py:314](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/mlb/availability.py:314), [mlb/availability.py:400](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/mlb/availability.py:400), [mlb/availability.py:406](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/mlb/availability.py:406) |
| Availability: manual injury/status overrides | **(b)** | The current override file contains present-day player-specific facts. `run_prospect_availability` loads it by default. There is no dated override history. [availability.py:22](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/availability.py:22), [availability.py:743](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/availability.py:743), [prospect_availability_overrides.json](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/data/manual/prospect_availability_overrides.json) |
| MLB service totals and rookie-limit graduation | **(c)** | Rookie thresholds are fixed, and historical MLB seasons allow service totals to be approximated through a cohort cutoff. The live `mlb_service` array is nevertheless rebuilt as current aggregate state; it is not a dated historical service ledger. [rank_v1.py:47](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:47), [raw_input_builder.py:1025](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/raw_input_builder.py:1025), [raw_input_builder.py:1034](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/raw_input_builder.py:1034) |
| Active MLB roster membership | **(b)** | Active roster IDs affect normalization and the final board route. The official roster artifact is current, and its archive stores validation counts but omits the player profiles needed for replay. [rank_v1.py:1905](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:1905), [rank_v1.py:1944](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:1944), [mlb/roster_status.py:161](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/mlb/roster_status.py:161), [mlb/roster_status.py:235](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/mlb/roster_status.py:235) |
| Manual graduation/aged-out exclusions | **(b)** | Rank reads the current manual file internally and hard-excludes those IDs. There is no date-effective history. [rank_v1.py:385](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:385), [rank_v1.py:1954](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:1954), [prospect_graduation_overrides.json](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/data/manual/prospect_graduation_overrides.json) |
| External consensus boards and FanGraphs FV snapshot | **(b), but rank-neutral** | These are current snapshots, but rank merges them only after scoring into `context_only.source_ranks`; the code explicitly says they never enter the score. They do not block core score replay, though they cannot provide historical validation. [rank_v1.py:404](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:404), [rank_v1.py:419](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:419), [rank_v1.py:2061](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:2061) |
| Four-year factual outcome labels used by the proposed gate | **(a)** | The existing backtests clip outcomes to four years and expose a cross-role comparable bust/role/star tier. Pairwise concordance already ignores tied outcomes. [dynasty_backtest.py:27](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/dynasty_backtest.py:27), [dynasty_backtest.py:78](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/dynasty_backtest.py:78), [model.py:762](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/model.py:762) |

Measurement ceiling: **no exact historical `rank_v1` replay**. The honest maximum is an out-of-sample replay of the score-producing core over a fixed historical pseudo-universe, with class-(b) inputs disabled and class-(c) approximations declared.

## 2. Recommended gate design

Use one proposed `prospects/rank_backtest.py` and one small pure scoring entry point shared with live `rank_v1`. Do not call `run_prospect_rank_v1`: its defaults load current availability and roster artifacts, while `build_prospect_rank_v1` internally reads current manual exclusions and consensus snapshots. [rank_v1.py:1889](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:1889), [rank_v1.py:1908](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:1908), [rank_v1.py:2272](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:2272)

### Historical rank-core replay

Reuse the existing test cohorts—2018, 2019, and 2021—and the fixed four-year training rule. Those folds and their training cutoffs are already emitted by the current harness. [adapter backtest artifact:139](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/data/models/valucast_prospect_adapter_backtest.json:139), [adapter backtest artifact:161](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/data/models/valucast_prospect_adapter_backtest.json:161), [adapter backtest artifact:183](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/data/models/valucast_prospect_adapter_backtest.json:183), [adapter_backtest.py:369](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/adapter_backtest.py:369)

For each fold:

1. Fit the prospect-model and dynasty signals using only eligible training cohorts.
2. Make the test cohort’s eligible historical rows the fixed pseudo-universe.
3. Apply production role-quantile normalization to that fixed pool.
4. Score four nested variants:

   - `C0`: frozen pre-028 baseline.
   - `C1`: `C0` + stale-pedigree cap.
   - `C2`: `C1` + pitcher concordance-gap down-weight.
   - `C3`: `C2` + structural pitcher attrition discount.

5. In every variant, neutralize official IL, upstream status, manual availability, manual graduation, active-roster filtering, day-level staleness, and career-history softening. Structural attrition is the only availability difference permitted.
6. Compare score order with the factual four-year expected outcome tier.

Report concordance in three partitions:

- `C_pitcher`: pitcher–pitcher pairs; the main efficacy metric for `C1`.
- `C_cross`: hitter–pitcher pairs whose realized tiers differ; the only honest historical ordering metric for uniform role discounts in `C2` and `C3`.
- `C_all`: all comparable pairs.

A per-role adapter concordance cannot measure a uniform pitcher discount because that discount does not change pitcher-versus-pitcher ordering. The current adapter harness is explicitly role-separated. [adapter_backtest.py:369](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/adapter_backtest.py:369), [adapter_backtest.py:555](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/adapter_backtest.py:555)

### Proposed pre-registered historical criteria

Freeze these before any 028 scoring result is viewed:

| Candidate | Primary criterion |
|---|---|
| `C1` vs `C0` | `ΔC_pitcher ≥ +0.005`, with the adjusted one-sided confidence lower bound above `0`. |
| `C2` vs `C1` | `ΔC_cross ≥ +0.005`, with the adjusted one-sided confidence lower bound above `0`. |
| `C3` vs `C2` | `ΔC_cross ≥ +0.005`, with the adjusted one-sided confidence lower bound above `0`. If not, cut the redundant attrition lever. |

Common invariants for every accepted step:

- At least `250` eligible players per role and at least `2` folds, reusing the current gate floors. [adapter_backtest.py:40](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/adapter_backtest.py:40)
- `ΔC_all ≥ 0`.
- `ΔC_hitter ≥ -0.005`.
- No fold’s primary concordance delta below `-0.010`.
- Tie-aware top-quartile precision delta at least `-0.005`; the existing implementation can be reused. [adapter_backtest.py:171](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/adapter_backtest.py:171)
- Baseline and candidate have exactly the same identity set.
- Every role/base-rate coefficient is derived from that fold’s training cohorts only.

### Current-board paired ablation guard

This is a safety gate, not out-of-sample evidence. Score the same frozen current snapshot twice, with only the registered lever changing.

Proposed invariants:

- Input artifact hashes and ranked identity set: exactly equal.
- A cap or discount may never increase a score.
- `C1`: fresh pedigree at `≤2` years since draft remains exactly unchanged; non-qualifying pedigree remains unchanged.
- `C2` and `C3`: hitter score components remain byte-identical.
- Maximum per-player score decrease: `6.0`, matching the existing step boundary used downstream. [buy_score.py:25](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/web/buy_score.py:25)
- Membership overlap: at least `20/25`, `42/50`, and `90/100`.
- Among baseline top-200 rows, 95th-percentile absolute rank movement no greater than `50`.
- On the frozen baseline top-200 identities with at least three qualifying public boards, external-consensus median absolute gap may worsen by at most `5` ranks and p90 by at most `15`. Three-board coverage and the 600-rank source cap already exist. [ahead_of_consensus.py:42](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/ahead_of_consensus.py:42), [ahead_of_consensus.py:51](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/ahead_of_consensus.py:51)
- The existing publication veto remains: top-25 pitchers `≤7` and top-50 pitcher rate `≤0.30`. It is not efficacy evidence. [calibration_report.py:31](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/calibration_report.py:31), [valucast_governor.py:436](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/quality/valucast_governor.py:436)

Named-player positions are diagnostics only. They must be removed from acceptance; the current plan’s assertion set is exactly the trap this gate replaces. [028 plan:836](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/plans/028-pitcher-lean-model-fix.md:836)

### Pre-registration and multiple comparisons

Put a frozen “Rank-gate v1 registration” section in the existing 028 plan and commit it separately before implementing or running the gate. No new configuration framework is needed. Record:

- baseline commit;
- `C0`–`C3` formulas;
- thresholds above;
- cohort and eligibility rules;
- class-(b) neutralization list;
- bootstrap seed `28013`;
- input artifact hashes.

Evidence budget:

- Exactly **one historical look**, evaluating all three nested comparisons in one batch.
- Use `10,000` paired bootstraps stratified by fold and role.
- Bonferroni familywise `α=0.05/3=0.0167`; therefore require a one-sided `98.33%` lower confidence bound above zero.
- Comparisons are sequential: `C2` is eligible only if `C1` passes; `C3` only if `C2` passes. Do not pick the best-looking member of the family.
- After results are unblinded, no parameter retuning and rerun on these cohorts counts as confirmatory. A failed lever is cut. A subsequent result is exploratory until a genuinely new outcome vintage exists.

This is intentionally strict because the current fold outcomes are already visible in the committed artifact; there is no untouched historical holdout left.

## 3. What the gate still cannot catch

- Whether an IL, rehab, manual override, or upstream status discount was historically correct.
- Interactions between the structural attrition discount and live injury/staleness discounts.
- Exact historical membership, active-roster routing, manual graduation, or their effect on the normalization pool.
- Exact historical current-line selection, fetched-date staleness, or prior-career softeners.
- Whether present consensus boards are correct; the consensus check only detects extreme drift.
- Calibration of score magnitude. Concordance sees order, not whether `55` versus `45` is an honest distance.
- Rare-star harm hidden by a bust-heavy outcome distribution.
- Future concept drift. The only eventual confirmation is prospectively archived, profile-complete inputs followed until outcomes mature.

Full future replay would require archives to retain player-level roster profiles, IL profiles, override snapshots, the exact candidate universe, input contract, model profiles, and normalization pool. Current MLB availability and roster archives do not retain those profiles. [mlb/availability.py:406](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/mlb/availability.py:406), [mlb/roster_status.py:241](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/mlb/roster_status.py:241)

## 4. Self-attack

### Anachronism leaks

- Calling `run_prospect_rank_v1` with historical core artifacts still loads today’s availability and roster defaults. [rank_v1.py:2272](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:2272)
- Calling `build_prospect_rank_v1` still reads today’s manual graduation and consensus files internally. [rank_v1.py:1908](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:1908)
- Calling `load_milb_history_index` without a cutoff injects post-cohort seasons. [rank_v1.py:232](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/rank_v1.py:232)
- Calling the availability runner injects today’s override and MLB availability artifacts. [availability.py:743](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/availability.py:743)
- Allowing `generated_at` to fall back to current time silently turns historical missing fetch dates into present-day staleness. [availability.py:649](/C:/Users/Alex/Documents/Codex/2026-05-18/league-values/prospects/availability.py:649)

Each should be a hard harness error, not a warning.

### Goodhart risks

| Criterion | How it can be gamed or mislead |
|---|---|
| `C_pitcher` | A cap can improve common bust/role ordering while burying rare legitimate stars. Top-quartile precision helps but cannot eliminate this. |
| `C_cross` | Pushing every pitcher down can exploit historical role base rates without improving pitcher identification. That is why within-role non-regression and blast-radius limits remain mandatory. |
| Top-quartile precision | A large tie block near the boundary can preserve overlap while worsening ordering elsewhere. |
| Current top-25/top-50 role shape | An executor can tune directly to seven pitchers. It remains a publication veto only, never evidence that the model improved. |
| Consensus-gap guard | Copying consensus would pass it. External ranks must remain prohibited score inputs; only worsening is bounded. |
| Top-N overlap and score bounds | Many small changes around cut lines can still alter important names while respecting every aggregate limit. |
| Bootstrap confidence | The cohorts are already known and previously inspected. Multiplicity adjustment limits opportunism; it does not manufacture a fresh holdout. |

### Assertion trap

Any acceptance rule mentioning Hughes, Murphy, Anderson, Hernandez, Sloan, or another named player is the old assertion trap. Named rows may illustrate mechanics after the gate has rendered its decision; they cannot influence pass/fail.

The existing governor threshold is also susceptible to becoming “tune until exactly seven.” The freeze-before-run rule is what keeps it a veto rather than the objective.

## 5. Cleared/checked

Checked in this design review:

- Adapter import boundary and fold construction.
- `rank_v1` score branches, normalization pool, availability application, calibration, exclusions, sorting, and hidden file reads.
- Prospect-model and universal/dynasty historical seams.
- Input-contract raw sources and historical/current split.
- Sample, staleness, upstream-status, official-IL, and manual availability paths.
- Active-roster, MLB-service, and manual-graduation paths.
- Player-level contents omitted from MLB availability/roster archives.
- External consensus/FV use; confirmed context-only.
- Current 028 assertion acceptance language.
- No pytest, build script, artifact builder, file edit, staging, commit, or stash was run.

Final verification found concurrent tracked modifications, including `mlb/availability.py` and `mlb/roster_status.py`, plus the expected untracked `data/dd/dd_dynasty_feed.json`. I did not create those changes; the two relevant MLB files were reread after the drift so their citations above reflect the final observed worktree.
