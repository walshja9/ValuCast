# Adversarial Review: The Mike Sirota Disagreement

**Date:** 2026-07-29
**Scope (owner-set):** determine whether ValuCast's ~#177–203 ranking of Mike
Sirota (mlbam 701527) reflects a general Stage 1 coverage weakness — defensive
role floor, athleticism, injury-adjusted development, contact quality, or
organizational investment — or public-ranking overreaction. Cohort evidence,
not a one-player correction. No scoring, ranking, artifact, or publication
change; model freeze preserved throughout. Three independent read-only lanes:
case anatomy, historical cohort, feature evaluation. All computation from
committed artifacts in scratchpad worktrees.

## Verdict

**Neither hypothesis survives as stated.** The ranking is not primarily a
missing-feature problem, and public overreaction is unmeasurable from
committed data. The model sees Sirota's production and discounts it for
defensible, historically vindicated reasons — then pushes him further down
through serving and normalization choices that add no information about the
player. The architecture-neutral ceiling of the frozen model is ~#38–49;
the residual gap to public #12–13 lies entirely in scouting-tool signals the
score is deliberately policy-barred from consuming.

## 1. Case anatomy (reproduced exactly from committed inputs)

The frozen model rates Sirota a **92nd-percentile hitter** on raw evidence
(outcome head 0.3147, impact head 0.2892), then four mechanisms produce
28.04/#177:

| Mechanism | Cost | Character |
|---|---|---|
| Age-23-at-AA youth discount (youth = −0.5 flips elite interactions) | ~−6.7 pts | Deliberate; **historically vindicated** (below) |
| 45% shrinkage of the 242-PA line (PA/(PA+200)) | ~−7.6 pts | Deliberate sample policy |
| Serving the AA-only slice, dropping his 1.080-OPS A+ line (401-PA pooled season scored by the observe-only pooled shadow at +0.054 raw) | ~−4.7 pts | Serving choice, already measured in-repo |
| Within-role→pooled normalization (hitter distribution dominates pitchers' through ~p95, so every top hitter maps down) | ~−2.5 pts ≈ 56 places | Adds no player information; the mirror image of the pitcher-crowding defect already ruled against in `docs/governor-review-2026-07-13-pitcher-lean-memo.md` and flagged by the calibration report |

Counterfactual walk (frozen weights, scratch-only): undoing all four caps him
at ~#38–49 — HKB (#31)/STS (#43) territory, structurally unable to reach
Pipeline/PL #12–13 (score thresholds 51.1/50.2 vs his ceiling ~39–42).

**What the public sees that the score cannot:** FG tool grades ARE committed
(`data/fangraphs/fg_fv_snapshot.json`: FV 45+, Raw Pwr 60, Spd 60, Pitch Sel
60 — and, contested: Hit 30/40, Fld 30/40) but are context-only by policy
(`rank_v1.py` PROHIBITED_SCORE_INPUTS). Not in the repo at all: trade
provenance (CIN→LAD), any 2024–25 season row (so injury-caused age cannot be
verified), AA exit velocity, sprint speed, defensive metrics.

**Not coverage gaps:** organizational investment saw him and priced him
correctly (66.69 = third-round slot bonus, weight 0.06 → exactly 4.00 of his
28.04 points).

**Repo self-awareness:** `valucast_consensus_gap.json` already ranks him the
single worst lower-side divergence (−155); the claims ledger records
ValuCast's own bearish Sirota claim being `retracted_by_model_move` on 07-14.
But the calibration report's disagreement watchlist inspects only the VC top
50, so consensus-elite/VC-deep players are structurally invisible to it
(owner disposition item 3 addresses this).

## 2. Historical cohort (matured 2014–2019 cohorts, committed outcomes)

- **The age discount is real and steep:** among A+/AA raw mashers (OPS ≥
  .900), role-or-better falls monotonically **89% (age ≤21) → 56% (22) → 50%
  (23) → 25% (24)**; n=30.
- **The elite-walk qualifier adds nothing:** old high-walk mashers 31.2%/0%
  (n=16) vs old low-walk 29.7%/5.4% (n=37).
- **No anti-archetype bias in the model:** walk-forward OOF predictions for
  the loose archetype (n=14 covered) predicted mean tier 0.241 vs realized
  0.250; old-loose predicted 0.129 vs realized 0.000 (generous, if anything).
- **The exact archetype is nearly empty:** n=2 matured (1 role, 1 bust).
- **The one soft spot:** his specific slice — AA mashers age ≥23 — realized
  **55.6% role-or-better / 11.1% star** (n=18; 65.2%/21.7% adding the
  pedigree-confounded ≤2021 class), matching what the model's own outcome
  head implies at his score (players OOF-scored 0.25–0.35 realized 54.7%
  role-or-better, n=75) — but **double his displayed `dynasty_signal`**
  (26.8% role-or-better / 73.2% bust). The tension is between ValuCast's two
  heads on the display surface, not between the score and history (owner
  disposition item 2; separate audit doc).
- **Public side unmeasurable:** no pre-2026 consensus ranks exist in the
  repo. 2026-only context: 75% of ValuCast's decided bearish divergence
  claims ended in self-retraction (67/89), including Sirota's.

## 3. Feature axes (the model's own walk-forward gate as yardstick)

Harness reproduced to the fourth decimal (pooled kNN baseline 0.140745,
n=2,901; current candidate +6.36%; gate bar ≥2%) before testing:

| Axis | In frozen model? | Historically reconstructable? | Measured effect |
|---|---|---|---|
| Injury-adjusted development time | No (availability layer is downward-only) | Density proxies committed; real MiLB IL logs via StatsAPI transactions **verified to 2014**, bounded collection needed | **Best axis: hitter gate +2.16%→+3.02%** (density proxies); `years_since_draft` harmful (gate →+1.09%) |
| Defensive position value | No (position unused by score) | Positions fully committed 2014–19 | +2.16%→+2.53% (position×youth×level) |
| Athleticism | Weak SB proxy only | Sprint speed does not exist for 2014–19 MiLB (verified) | Proxies inert; SB already absorbed |
| Contact quality (AA EV) | No | Not reconstructable (MiLB Statcast: FSL-A 2021+, AAA 2023+ only; 2017 verified empty) | Proxies exactly inert |
| Organizational investment | Yes — priced correctly | Already shipped at data-supported level | Richer blocks **lose to kNN outright** (−3.18% pooled); intl-bonus file survivorship-selected + policy-barred |

Both positive deltas carry a best-of-ten multiple-comparison caveat.

## Owner disposition (2026-07-29)

1. This evidence report committed (this document).
2. **Immediate honesty item:** audit the displayed 26.8% role probability vs
   the outcome head's ~54.7% OOF implication →
   `docs/audit-2026-07-30-dynasty-signal-probability-honesty.md`.
3. Expand the disagreement watchlist to consensus-elite/ValuCast-deep
   players. Display-only; no scoring change.
4. **Freeze preserved; no Sirota adjustment.** (Standing non-action.)
5. Register injury-adjusted development and position×youth as cohort-wide
   challengers with multiplicity controls →
   `docs/registration-2026-07-29-outcome-feature-challengers.md`.
6. Cross-role normalization stays on its existing research track (the 7/13
   memo); the earlier study was underpowered — not reopened without
   sufficient new evidence. (Standing non-action.)
7. Contact-quality and organizational-investment work skipped — no
   historical coverage / no measured lift. (Standing non-action.)

Lane raw materials: scratchpad `sirota/`, `sirota_cohort/`,
`sirota_features/` (analysis scripts; regenerable per each lane's method
notes from committed artifacts).
