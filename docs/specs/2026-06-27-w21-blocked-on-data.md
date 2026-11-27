# W2.1 (dynasty-signal up-weight) — DECISION: blocked-on-data

Date: 2026-06-27
Status: **BLOCKED-ON-DATA** (do not ship). Supersedes the up-weight/blend portion of
`2026-06-26-valucast-wave2-value-rebalance.md`.

## Decision

Do **not** up-weight the dynasty signal in the served prospect value. The reweight
cannot be validated with the data that exists today; shipping it would be a board-shaping
choice that *feels* right (it matches external consensus) but cannot be shown to improve
realized-outcome prediction.

## Reason

The dynasty signal beats the level-age prior on **realized** outcomes (post-cohort MLB
established/star results, not the predicted tier) in only **1 of 3 mature folds**. From the
served backtest `data/models/valucast_prospect_dynasty_backtest.json`:

```
                fold 2018         fold 2019         fold 2021
HITTER   cand==base (prior)  cand==base (prior)  0.806 vs 0.655  <- only discriminating fold
PITCHER  cand==base (prior)  cand==base (prior)  0.783 vs 0.695  <- only discriminating fold
```

On 2018 and 2019 the per-fold gate falls back to the level-age prior (it does not clear the
2% improvement bar), so candidate == baseline — zero out-of-sample evidence. The per-target
sources confirm the *simplified* `established_probability` / `role_or_better` head falls back
on those folds too, so simplifying the composite does not rescue it. The role research gate
reports `active`, but that verdict is **non-discriminating**: the two tied folds pass the
temporal-stability guard's non-strict `≥`/`≤` for free, and the entire `active` rests on the
single 2021 fold. One fold carrying the whole verdict is a warning label, not validation.

This is a **data constraint, not a method bug**: only three mature trainable folds exist, the
2020 MiLB season was cancelled (cohorts jump 2019 → 2021), and the 4-year maturity horizon
leaves 2022+ not yet closed. No methodology change manufactures a second discriminating fold
from data that isn't there.

## Revisit trigger

Reopen W2.1 when **≥1 additional mature cohort fold** shows the dynasty signal beating the
level-age prior out-of-sample (candidate ≠ baseline AND candidate concordance > baseline) —
i.e. ≥2 discriminating folds total. Earliest realistic data: 2022/2023 cohort maturity
(~2026–2027), one fold at a time. Re-run the existing dynasty backtest and check the per-fold
`candidate_sources` / concordances before reconsidering.

## Consequence for the board (intended, not a defect)

The served board keeps its current-production lean. The known position disagreements —
**Jesús Made (#12 vs consensus #1), Leo De Vries, Sam Shaw > Devin Taylor, Ronny Hernandez (#33)** —
are **model-position disagreements, not correctness defects**. Two external boards (ProspectsLive,
PROSPX) reward ceiling more than we do; we cannot *prove* they're right, so we do not reshape
toward them on faith.

## Related

- **W2.4 (stale-current comparator) SHIPPED** and is unaffected by this — it fixed selector/stale-line
  *bugs*, which are correctness defects, distinct from the ceiling-vs-production *lean*.
- **W2.2 (thin-penalty recalibration)** stays **gated behind W2.1**: it is symmetric (lifts both
  buried legit prospects *and* gaudy thin-current over-rankings like Hernandez), so it should not
  ship without the W2.1 counterweight that this decision blocks. Closed alongside W2.1 for now.
- Methodology / harness map: the spike used `prospects/dynasty_backtest.py` (`_role_backtest`,
  `_temporal_stability_guard`), realized labels via `prospects/universal.py:_raw_target` (NOT
  `dynasty.expected_factual_outcome_tier`, which is the circular path the red-team flagged).
