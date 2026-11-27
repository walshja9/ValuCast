# Senior Analytics Formula Review — 2026-07-21

> **Resolution status (2026-07-21): historical audit snapshot.** Tier-1 items
> #1-#6 and #8 were fixed in `ef48d773` and `3f294d0b`; item #7 was fixed and
> merged in `b2e70904`. Tier-2 entries remain registered research hypotheses,
> not demonstrated model improvements.

Six territory reviewers (model core, rank/buys, dynasty/value, inference, surfaces, cross-cutting), every P0/P1 claim independently re-derived by an adversarial verifier. 21 serious claims survived triage: 11 CONFIRMED, 8 DOWNGRADED (real mechanism, overstated harm), 2 REFUTED. Zero P0s: nothing serves a number that is *wrong* beyond the already-adjudicated known issues. The core machinery — ridge solve with intercept-excluded penalty, per-fold leak-free standardization, hurdle decomposition, horizon clipping, outcome-distribution coherence guard, cluster bootstrap structure — is correct and in places notably careful.

## Tier 1 — Confirmed defects in SERVED surfaces, NOT under the prospect-model freeze

These affect numbers users see today and live outside the frozen prospect model. Normal ship discipline (tests + review) applies, not registered gates.

**1. Dynasty layer: multiplicative curves applied to signed values** (`src/league_values/post_processors.py:96,136` via `mlb/dynasty.py:1119-1127,258-264`) — CONFIRMED. Volume/age multipliers on a mean-centered value are only monotone for positive values. A below-average player's volume *penalty* moves his value toward zero — a better rank. A mediocre 22-year-old ranks *below* a mediocre 30-year-old because the youth multiplier amplifies his negative value. No replacement-level shift exists in the MLB layer to prevent this. Fix: shift to a non-negative (above-replacement) scale before applying multiplicative curves. **The most material finding in this review.**

**2. Dynasty layer: playing-time reliability reused as talent-persistence decay** (`mlb/dynasty.py:237-241,263-264`) — CONFIRMED. A volume-sample score (small current PA/IP → ~0.55) is compounded per horizon year (0.55² ≈ 0.30 by year 2), so a part-time but genuinely good player is crushed in dynasty value for having a small sample — conflating playing-time uncertainty with asset decline. Fix: separate the two; let age carry the decay, represent sample thinness as uncertainty, not a compounding haircut.

**3. Card skill grades consume raw MiLB rates across levels** (`prospects/rank_v1.py:672-706` → `prospects/peak_projection.py:148-192`) — CONFIRMED. Low-A OPS and AAA OPS are graded on one yardstick while the repo's own `translate_peripherals()` sits unused by this path. Hot A-ball lines can trip "impact" skill bands. Fix: feed level-translated rates into `_scale()` and skill_band thresholds.

**4. Combined multi-level stat lines mis-weight OPS/OBP/AVG** (`prospects/milb_translation.py:288-303,355-374`) — CONFIRMED. PA-weighting a blended OPS is wrong (SLG is per-AB); ERA/WHIP happen to be correct (IP is their denominator). Fix: reconstruct from summed components (sum(H)/sum(AB), etc.). Small but systematic display error.

**5. Comps cohort "median" takes the upper-middle element** (`prospects/comps.py:480-481`) — CONFIRMED. Biased-high for even-sized cohorts (common — many cohorts resolve short). Five consensus sites already do even-n averaging correctly; comps.py drifted. Fix: `statistics.median` via one shared helper.

**6. 2020 short-season scaling leaks into rate weights** (`prospects/comps.py:52,206-212`) — CONFIRMED. The 162/60 PA scale is right for the playing-time tier but is reused as the weight in the era-relative OPS mean, tripling a 60-game season's influence on a rate. Fix: raw PA for rate weights, scaled PA for tier only.

**7. Forward scoreboard significance framing** (`prospects/forward_scoreboard.py:239-294`) — CONFIRMED, ⚠️ frozen file. The published permutation null is decorative — the verdict reduces entirely to the bootstrap CI of a median, which under-covers on small discrete sign-imbalanced day-pools (exactly the current provisional regime). Fix (needs explicit authorization to touch the frozen file): drive significance off the permutation null it already computes, or use the sign-test/Wilson interval for the median; at minimum make the copy honest about which test gates the verdict.

**8. "Next Build Order" panel is a hardcoded stale literal** (`prospects/front_office_report.py:395-401`) — from the grade-lever review. "B+ evidence" matches nothing live; validator only checks it's a list. Compute it or correct it.

## Tier 2 — Confirmed/downgraded items for the REGISTERED-EXPERIMENT queue (frozen model)

- **Ridge λ hardcoded, never tuned** (`model.py:724-745`, CONFIRMED): one constant across heads of wildly different dimensionality/noise. Inner leave-one-cohort-out or GCV per head, stored in the artifact.
- **kNN gate-baseline is artificially weak** (`model.py:848-858`, DOWNGRADED): unweighted k=25 Euclidean in 27–36-dim z-space — distance concentration makes it near-global-mean, flattering the ridge at the promotion gate. Distance-weighted kernel + k∝√n. This governs the *gate*, so it's quietly load-bearing.
- **model_score + universal_outcome_index double-count** (`rank_v1.py:833-880`, CONFIRMED): correlated measurements of the same latent, fixed-weight-summed. Measure the correlation; residualize or fit stacked weights OOS.
- **Investment = max(draft, bonus)** (`rank_v1.py:907-931`, CONFIRMED): max of two noisy positives is upward-biased and discards corroboration. Blend instead.
- **TARGET_SPECS hand-picked scales censor tails** (`universal.py:359-529`, DOWNGRADED): OLS on clamped [0,1] targets = Tobit-ignored censoring at the extremes where the best prospects live. Training-fold quantile scaling or logit link.
- **Train/serve shrinkage mismatch** (`model.py:1273`/`universal.py:336`, DOWNGRADED but facts confirmed): coefficients learned on raw rates, applied to reliability-compressed inputs. Shrink training features identically, or move reliability into a prediction blend.
- **Rank-blend mixes a quantile-transformed component with raw-scale components** (`rank_v1.py:832-855`, DOWNGRADED); **additive confidence penalties on a 0-100 score are regressive** (thin-sample −28 hits a 40-score player 70%, a 70-score player 40%; `rank_v1.py:1401-1466`, DOWNGRADED) — make haircuts multiplicative.
- **Guardrail multiple-comparisons problem** (`competition_benchmark.py:180-195` + `dynasty_backtest.py:151-170`, CONFIRMED): all-cohort/all-fold strict non-regression on point estimates with no noise accounting — false-negative rate *rises* as folds are added. ⚠️ **Directly interacts with the 2009–2013 extension: at 8 folds the all-fold guard as written becomes much harder to pass by chance alone. The extension's registration must specify a noise-aware regression criterion (exceed cap by > its own SE band) or it will be biased toward null by construction.**
- **Buy momentum asymmetric clamp** (`web/buy_score.py:32,109-117`, DOWNGRADED): +15%/−10% window makes upside momentum reach 0.6 from neutral vs 0.4 down — an undocumented directional prior. Document or symmetrize.

## Refuted (claims that did NOT survive)

- "5% regression cap statistically unjustified / silently overrides registration" — the plan documents the rationale, and the clamp only ever *tightens*; the verifier found the registration contract intact.
- "Top-k regret dominated by tie-slice artifacts" — the oracle math tie-averages correctly on re-derivation.

## Clean (verified sound)

Gaussian-elimination ridge solve + singularity guard; per-fold standardization (no leakage); hurdle E[Y]=P(Y>0)·E[Y|Y>0]; horizon clipping at both training and eval; per-player dedup across folds; coherence guard forcing valid outcome partitions; AUC-style concordance with tie handling; empirical-Bayes reliability formula itself; downward-only stale/pedigree corrections; hierarchical cohort→player bootstrap structure; comps z-space similarity as a display lens (Euclidean defensible; Mahalanobis worth one registered look).

## Recommended order

1. Ship Tier-1 items 1–6 + 8 as a normal fix batch (dynasty layer first — items 1–2 change served dynasty ranks and are genuine math bugs).
2. Decide the two governance items: scoreboard significance fix (frozen-file authorization) and the power-gate decoupling (separate proposal, from the grade-lever review).
3. Fold the guardrail noise-aware criterion into the 2009–2013 extension registration *before* it's written — cheapest at design time.
4. Queue Tier-2 as registered experiments for the post-2026-season epoch batch alongside plan-028 re-tests.
