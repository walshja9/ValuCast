# Plan 031 — Pitcher Strike% Gate (Wave B): Registered, UNSPENT

**Status: REGISTERED 2026-07-16 — LOOK HELD (DO-NOT-SPEND), seed 31013 never
executed.** This registration freezes the gate specification for the
`strike_pct_only` variant exactly as dry-run at exploratory seed 31017
(`data/validation/level_translation_dryrun.json`, `gate_look_spent: false`).
The registered look is deliberately NOT being spent on the current 3-fold
vintage — see §9 for the decision record and the re-arm condition. Executing
anything at seed 31013 before the re-arm condition is met violates this
registration.

## 1. Background: what the exploratory dry-run found

Three ablations were dry-run over the registered fold set (test cohorts
2018/2019/2021, train_through = test − 4) on both gate axes, entirely dark
(flags default False, serving byte-identical proven):

| Variant | Board Δc_pitcher (point / 98.33% LB) | Board Δc_hitter (point) | Dynasty Brier Δ% pitcher (point / 98.33% LB) | Dynasty Brier Δ% hitter |
|---|---|---|---|---|
| fitted_translation_only | −0.002687 / −0.004980 | −0.000957 | +0.0666 / −0.4728 | −0.0409 |
| strike_pct_only | **+0.005677 / +0.001653** | −0.000258 | +0.5120 / −0.2066 | 0.0 (exact) |
| both | +0.002696 / −0.001296 | −0.000848 | +0.5107 / −0.3889 | −0.0409 |

Ablation attribution is unambiguous: the fitted level-translation lever is
inert-to-negative on both axes and both roles; **the pitcher strike% feature
carries the entire positive signal**, and combining the two levers dilutes it.

Two structural power facts discovered in the same run:

- **Dynasty-Brier axis is 1-fold powered for any feature lever.** In folds 2018
  and 2019 the incumbent's own fold-local gate falls back to
  `level_age_prior` for both probability heads (insufficient inner walk-forward
  cohorts), and the prior reads only (level, age) cells — structurally immune
  to any feature change. Verified against the committed
  `valucast_prospect_dynasty_backtest.json` (same `candidate_sources`, and the
  dry-run incumbent reproduces its per-fold candidate Briers exactly). Only
  fold 2021 can move. A "≥2% per-role Brier with LB>0" requirement therefore
  has approximately zero power against any plausible feature-level effect and
  would burn the look with near-certain failure.
- **The strike% board effect is fold-concentrated**: per-fold Δc_pitcher =
  −0.000202 (2018), −0.001019 (2019), **+0.018870 (2021)**. The pooled point
  clears the registered +0.005 threshold and the 98.33% LB is positive at the
  exploratory seed, but the effect lives in the newest fold.

## 2. Hypothesis

Adding a None-safe pitcher strike% command feature
(`strike_pct_dev = known × (strikes/pitches − 0.658)`, plus a `strike_pct_known`
missingness flag; pitcher-only; appended last in both the prospect-model OUTCOME
space and the universal feature space) improves within-role pitcher tier
ordering on the historical board replay, without touching hitters and without
degrading the pitcher dynasty outcome distribution.

Mechanistic prior: strike% is a direct command signal at the season-line
level; fold-era coverage is 100% (3449/3449 pitcher rows, values verified
against live StatsAPI), so the missingness flag is inert in folds and exists
purely as current-feed safety. NOTE (math review F6): the claimed
orthogonality of strike_pct_dev to existing K/BB features was asserted, never
measured — no in-repo correlation readout exists; partial collinearity is
plausible. The mechanistic prior supports the *feature*, not the specific
2021-only pattern observed (a structural command effect should express at
least weakly in every cohort; 2018/2019 deltas are ~zero-to-negative).

## 3. Exact variant to be gated (ONE variant; one look covers the bundle)

```
{"model_flags": {"PITCHER_STRIKE_PCT_ENABLED": true}}
```

i.e. the `strike_pct_only` ablation, exactly as implemented in
`prospects/level_translation_challenger.py` (strike% lever only). The fitted
level-translation lever (`LEVEL_TRANSLATION_FITTED_ENABLED`) is **explicitly
NOT registered**: its dry-run evidence is negative on the board axis for both
roles and ~zero on the Brier axis. It stays dark; re-opening it requires new
evidence under a structurally different form (e.g. per-stat multiplicative or
quantile mappings, or AAA-Statcast-informed anchors) — additive per-(stat,level)
shifts are nearly in the linear span of the existing level code +
`*_x_level` interactions and are absorbed by the ridge (dry-run finding).

Pitch/strike counts are joined from the committed raw dataset
(`data/prospects/raw/valucast_universal_prospect_dataset.json`) into the
in-memory contract exactly as the dry-run does (join key mlbam_id ×
cohort_year × level, verified unique, 3449/3449 joined, 0 corrupt rows). No
on-disk contract change is part of the registered look.

## 4. Dual gate specification

**Primary (board ordering axis) — decisive:**
- Metric: Δc_pitcher (within-role tier concordance, candidate − incumbent),
  weighted across the registered folds, via
  `prospects.rank_backtest.paired_bootstrap_lower_bound` (10,000 paired
  within-fold resamples, one-sided 98.33% normal-approx LB, z = 2.128045).
- **PASS requires: point ≥ +0.005 AND 98.33% LB > 0** at the registered seed.
  This is the identical form and threshold as the registered C1 rank-gate
  (calibrated by `scripts/power_check_rank_gate.py`); no new threshold is
  invented for this look.

**Secondary (dynasty Brier axis) — non-inferiority guard, NOT a detector:**
- Pitcher: dynasty multiclass-Brier improvement % (variant vs incumbent,
  paired player-cluster bootstrap, 10,000 draws, registered seed) must have
  **98.33% LB > −1.0%** (i.e. we must be able to rule out a ≥1% distribution
  degradation). The −1.0% floor is anchored, not free-floating: it is exactly
  **half of `MIN_GATE_IMPROVEMENT_PCT` (2.0, `prospects/model.py:95`)** — the
  registered Brier improvement threshold — reflecting that ruling out half a
  gate-unit of damage is the strongest statement a ~1-effective-fold axis can
  support. Justification for non-inferiority instead of "≥2% with LB>0":
  the E1 power finding (3 folds cannot certify ~+0.007 ordering effects)
  compounds here — two of the three Brier folds are structurally frozen at the
  level-age prior (Section 1), so the axis has ~one fold of effective sample.
  Demanding +2% with LB>0 on a one-fold axis is not a gate, it is a guaranteed
  fail; demanding non-inferiority preserves the axis's real function
  (protecting the calibrated distribution from ordering-motivated damage).
  **Disclosure (math review F5): this gate-form change is data-informed** — it
  was drafted after observing that the variant fails the old form (point
  +0.512% < 2%, LB −0.207% < 0) and passes the new one. The structural
  justification is verified fact (the prior-fallback freeze is in the
  committed backtest artifact), and the change is made at registration, before
  any look is spent, with the dry-run values disclosed here — but any reader
  should weigh it knowing the timing. Dry-run reading: point +0.512%,
  LB −0.207% — passes the guard with margin.
- Hitter (both axes): the lever is pitcher-only by construction. Hitter gates
  are exact-zero checks, not statistical ones: **hitter model-level scores must
  be bit-identical** (dry-run: 0 of 345 changed) and the hitter dynasty Brier
  delta must be exactly 0. Hitter BOARD Δc must satisfy the E1 pooled-quantile
  ripple tolerance |point| < 5×10⁻³ (dry-run: −0.000258).

## 5. Registered evidence procedure

- **Seed: 31013.** Never yet executed anywhere (enforced in
  `scripts/run_level_translation_dryrun.py::FORBIDDEN_SEEDS` and the unit
  locks). Burned seeds 28013 / 28017 / 29001 and the wave's exploratory 31017
  are all excluded from the registered run. **Adjudication (2026-07-16): the
  31013 literal inside the FORBIDDEN_SEEDS guard and its unit lock is ACCEPTED
  as a deviation from the draft-text-only rule** — the guard makes executing
  31013 from the dry-run script impossible and removing it would weaken seed
  discipline, not strengthen it.
- Folds: test cohorts 2018, 2019, 2021 (the registered walk-forward:
  `OUTCOME_COMPLETE_THROUGH − OUTCOME_HORIZON_YEARS`, train_through = test − 4,
  player-disjoint by the earliest-cohort dedupe). Identity-set equality between
  incumbent and candidate is a hard invariant (raise, never warn).
- Machinery: `_fold_board_scores` + `paired_bootstrap_lower_bound` for the
  primary; the dynasty `_role_backtest` fold loop + `_delta_pct` player-cluster
  bootstrap for the guard. No metric redefinition; only within-role fields may
  be reported (quarantine).
- **Data pin (BOTH inputs, per leakage review):** the look must run against
  BOTH input files content-identical to commit d10cfd85 — the contract
  (`data/prospects/prospect_model_inputs.json`, historical rows n=6756) AND
  the raw dataset (`data/prospects/raw/valucast_universal_prospect_dataset.json`,
  the runtime source of the pitch/strike counts, pitcher join 3449/3449).
  Operational check: `git diff --quiet d10cfd85 -- data/prospects/prospect_model_inputs.json
  data/prospects/raw/valucast_universal_prospect_dataset.json` must pass.
  (Reference sha256 as measured in the 2026-07-16 Windows/CRLF checkout:
  contract `a4b5b99b10bb46707aa21f041aa706d9bed664b1a956d5cc113f2d4072ae6e90`,
  raw `00cc8ede3f438338b8babff642e95c251bdd00fdb043d934f23e38e142b69b1e`; the
  git-based check is canonical because raw-byte hashes vary with line-ending
  normalization.) The point estimate is deterministic given the data; the seed
  only moves the bootstrap LB.

## 6. Power statement (honest)

- The point estimate is fully deterministic; at the pinned data revision the
  registered point WILL be +0.005677 — only 13.5% above the +0.005 threshold.
  Any contract- or raw-data drift before the look could push it under the
  threshold; hence the dual pin.
- The 98.33% LB at 31013 will differ from the 31017 LB only by bootstrap Monte
  Carlo error (10,000 draws; observed bootstrap_sd 0.001891, MC error of the
  sd estimate ≈ 1.3×10⁻⁵ → LB jitter ≈ 2.9×10⁻⁵). The observed LB (+0.001653)
  sits ~58σ above zero; **P(the registered LB flips negative on seed noise) is
  negligible (< 10⁻⁶). The registered run's outcome is therefore already
  known — spending the look is certification, not experiment** (math review
  F1). This is the central reason the look is HELD (§9).
- **Null-pass risk (math review F2): under a cohort-noise null** — per-fold
  deltas i.i.d. N(0, observed between-fold sd 0.01125), within-fold bootstrap
  blind to fold noise — **this gate form passes ~22% of the time** (~6% if the
  true fold dispersion were half the observed, and 3 folds estimate that
  dispersion terribly). Between-fold t-test on the observed deltas: t = 0.91,
  one-sided p ≈ 0.23 (df 2) — the data cannot reject "one good cohort."
- E1 context (math review F3): E1's challenger (+0.006988 point, LARGER than
  this one) FAILED LB>0 with bootstrap_sd 0.00406. This variant passes at the
  exploratory seed because its within-fold dispersion is smaller (sd 0.00189),
  not because the effect is bigger — and within-fold player-resampling noise
  is the one uncertainty source not in question; the dominant uncertainty
  (cohort-to-cohort) is invisible to this gate form. Both effects are
  2021-fold-dominated. **Cross-wave pattern: every positive-point pitcher
  lever in both waves (E1 role_split, E1 shrink, WB strike_pct, WB both) is
  2021-dominated — the fold where the incumbent is weakest (c 0.662 vs
  0.777/0.827) and headroom is largest.** Three mechanistically unrelated
  levers all "working" only in 2021 fits "2021 is a generous fold" at least
  as well as "all three are real."
- The dynasty-Brier axis contributes ~one effective fold and is registered as a
  guard only (Section 4).

## 7. Decision rule for spending vs not spending the look

SPEND the one registered look (seed 31013, variant strike_pct_only) only if ALL hold:
1. The re-arm condition of §9 is met (new-vintage fold available — at which
   point §9 requires a superseding registration instead; see below).
2. Both pinned inputs are content-identical to the dry-run pin (git-based
   check, §5).
3. The flags-off freeze proofs still hold on the day of the run (dynasty
   backtest byte-identical rebuild; prospect + universal model artifacts
   byte-identical at pinned `now`).
4. The orchestrator accepts IN WRITING that the pass certifies a
   fold-concentrated effect with ~22% null-pass probability under cohort noise
   (§6) — an informed signature, not a discovery.

DO NOT SPEND (and return to the bench) if ANY hold:
- Either pinned input has moved (re-run the exploratory at 31017 first; if the
  deterministic point falls below +0.005, the look is dead — do not shop for a
  friendlier revision).
- Any hitter exact-zero check fails in a pre-spend flags-on smoke run.
- A serving-path prerequisite is discovered that would change fold inputs
  (e.g. the pitches/strikes whitelist landing in the contract builder and
  altering historical row content).

On PASS: the flag flip still does NOT go live from this gate alone — serving
requires the pitches/strikes fields to flow through `raw_input_builder`
(`_HISTORICAL_FIELDS` + the current-feed builder) with a contract rebuild and a
fresh freeze proof, then the standard epoch batch. On FAIL: the look is spent;
the lever stays dark; no re-run at any seed.

## 8. Serving-path prerequisites (findings, not part of this wave)

1. `prospects/raw_input_builder.py::_HISTORICAL_FIELDS` (and the current-feed
   producer for `milb_season_stats.json`) do not carry `pitches`/`strikes`;
   the served contract therefore cannot feed strike% today. Additive whitelist
   change + contract rebuild + governor re-baseline required before any live
   flip. **Dead-indicator caveat (leakage review): `strike_pct_known` is 1.0
   for every fold row (100% coverage), so it standardizes to a zero-variance
   dead column — the trained model has never seen the flag vary. A count-less
   serving row would therefore be scored at effectively training-mean command
   (mild imputation), NOT cleanly "feature absent." Before any live flip, the
   serving prerequisites must include a current-feed coverage check, and if
   current-feed coverage is materially below 100%, a mixed-coverage retrain
   consideration.** The draft's original "safe by construction" claim was
   overstated and is corrected here.
2. Committed `valucast_outcome_oof_scores.json` carries an `input.sha256` that
   no longer matches the committed contract bytes (pre-existing staleness,
   observed during freeze proofs; rows themselves rebuild identical). Worth a
   nightly-ordering look independent of this plan.
3. A display-only strike% stat line on pitcher cards ships independently of
   this gate (context-not-a-score-input label; reads the same verified counts;
   touches no gated artifact). It neither depends on nor advances this
   registration.

## 9. Review record and spend decision (2026-07-16)

Three adversarial reviews of the wave (all with hands-on reproduction; full
suite 2287 passed + 17 subtests in two independent runs; dry-run artifact
reproduced byte-identically twice; serving byte-identical with flags off;
frozen files untouched; no burned seed executed):

- **Leakage / fold-hygiene: SHIP-AFTER-FIXES.** Per-fold translation tables
  refit independently (fingerprints match, provably distinct from a global
  fit); anchor sets player-disjoint from test folds in all folds × roles;
  strike% provenance verified to StatsAPI. Fixes (all applied in this
  document): dual data pin (§5), dead-indicator caveat (§8.1), 31013-literal
  adjudication (§5).
- **Serving-freeze / CI: SHIP-AFTER-FIXES.** All four served artifacts
  byte-identical under reproduction with flags off; new import graph CI-safe
  (challenger module stdlib-only; numpy already pinned). Fix (applied at
  commit time): the new modules are import-load-bearing from
  `prospects/model.py`/`universal.py` — they MUST be committed atomically with
  those edits, via an explicit add list (never `git add -A`, which would sweep
  the frozen untracked `data/dd/dd_dynasty_feed.json`).
- **Math / gate-power: DO-NOT-SPEND.** Findings F1–F8 folded into §2/§4/§5/§6
  above. Core chain: the look buys no information (outcome deterministic,
  LB ~58σ from flipping); the evidence is one 2021 fold with ~22% null-pass
  probability; waiting is nearly free because a PASS cannot ship until the
  serving-path work lands anyway.

**DECISION (orchestrator, accepted by Alex 2026-07-16): the look is HELD.**
Seed 31013 remains never-executed. Both flags stay dark.
`gate_look_spent` stays false.

**Re-arm condition:** when `OUTCOME_COMPLETE_THROUGH` advances to 2026
(post-2026 season, ~Oct–Nov), the 2022 cohort clears the 4-year horizon and
becomes a genuine fourth fold that no exploratory run has ever touched. At
that epoch, this 3-fold registration is SUPERSEDED: register a NEW gate over
the 4-fold vintage (fresh seed, never 31013/31017/28013/28017/29001), with a
2022-fold-positive side condition as the candidate confirmatory requirement —
that registration carries the out-of-sample confirmatory content this look
lacks. **Do not spend the 3-fold look even then.** This is the same
new-vintage window as the plan-028 C1 pedigree-decay and E1 role-split
re-tests; strike% joins that batch.

**Unverified items carried on the record (math review §4):** the exact
fold-stratified resampling structure of `paired_bootstrap_lower_bound` was
taken on two sessions' code-reading authority (consistent with all observed
sds); strike_pct_dev↔K/BB collinearity is unmeasured; the cause of 2021's
generosity (incumbent weakness vs cohort composition vs era effects) is not
established by any artifact.
