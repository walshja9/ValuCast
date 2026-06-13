# ValuCast Universal Prospect Model

## Purpose

The universal prospect model is ValuCast's independent baseball opinion. It
predicts factual future MLB outcomes without embedding the preferences of a
specific fantasy league.

It does **not** produce a universal prospect rank. A rank necessarily answers
"best for what?" and therefore belongs in a downstream league-scoring adapter.
The same ValuCast outcome profile can eventually support 5x5, 7x7, OBP, points,
and custom-league values without retraining the baseball model.

The existing `prospects/model.py` remains the DD-oriented research model. Its
direct 7x7 target and ranks are not reused as universal truth.

## Version 0.3

Version 0.3 is a shadow-only A/A+/AA/AAA foundation. It predicts:

- Establishment probability for hitters and pitchers
- Regular-hitter and rotation-volume probability
- Representative MLB volume and production, conditional on establishment
- Every outcome required by the Diamond Dynasties 7x7 adapter

The representative season is always the player's highest-volume future MLB
season (`PA` for hitters, `IP` for pitchers). It is never selected because it
was the player's best fantasy-category season.

The expanded factual feature space adds MiLB volume, rate and counting facts,
plus sanitized Rule 4 draft-pick and signing-bonus facts. Draft facts dated
after a historical cohort are hidden. Scouting reports, draft rankings, blurbs,
and fantasy-market data never cross the contract boundary.

Every target has its own player-grouped expanding-window validation gate. Ridge
must beat the strongest of a factual level-age prior, expanded-feature
neighbors, and unchanged canonical core-stat neighbors by at least 2% out of
sample with at least 250 held-out observations. Probability targets use Brier
score; continuous targets use MAE. When ridge does not earn its gate, the
profile publishes the stronger factual baseline instead.

There is no model-wide promotion gate and no live consumer. Per-target evidence
is allowed to be mixed.

The expanded June 13, 2026 build enrolled 6,040 historical prospects without
survivor filtering and produced 2,486 current prospect profiles. The exact
per-target gate counts are emitted in the model artifact on every build. No
target is promoted merely to complete a league adapter.

Pitcher rotation probability is the first active universal target:

- Brier score: `0.050235`
- Strongest baseline: `0.052254`
- Out-of-sample improvement: `+3.86%`
- Rank concordance/AUC: `0.835`

Richer MiLB skills without draft facts also beat their rotation baseline in the
research ablation. Draft/signing and richer skills together produced the best
calibration. Pitcher establishment initially appeared active under MAE, but
correct probability scoring demoted it to fallback; this is why target-specific
scoring rules are part of the contract.

## Independence Boundary

Allowed inputs:

- MLBAM identity
- Factual MiLB statistics, age, level, position, and role
- Factual Rule 4 draft pick, slot, and signing-bonus facts known by the cohort
- Factual post-cohort MLB seasons
- Factual MLB service used to remove graduated players

Prohibited inputs:

- External prospect rankings
- External or fantasy projections
- Dynasty rankings, values, or market prices
- DD's direct 7x7 score or ValuCast's current live prospect order

## Rebuild

After refreshing the factual contract from Diamond Dynasties:

```powershell
python scripts/build_universal_prospect_model.py
```

Outputs:

- `data/models/valucast_universal_prospect_model.json`
- `data/prediction_archive/valucast_universal_prospect_model/YYYY-MM-DD.json`

## League Adapters

League adapters live separately in `prospects/adapters.py`. They translate
universal factual profiles into category or points-league opinions without
changing the baseball model.

```powershell
python scripts/build_prospect_league_adapters.py
```

The DD 7x7 adapter can now produce a research-only rank because the universal
profile predicts every required DD category. Standard 5x5 still correctly
refuses to rank pitchers because universal `W` and standalone `SV` outcomes are
not yet available. An adapter rank is never emitted when any configured
category is missing from the actual model artifact.

The DD adapter uses rotation probability to split pitcher `QS` from
`SV+HLD`, and scales ratio-category impact by projected playing time. Those are
league-scoring decisions and never feed back into the universal baseball model.

## Next Research Blockers

1. Add complex-league and rookie-ball coverage without weakening enrollment or
   outcome-completeness rules.
2. Add role-neutral underlying MLB skills where the source contract supports
   them, rather than fantasy-category outcomes.
3. Improve probability calibration and conditional target sample size without
   lowering the promotion gates.
4. Forward-test dated profiles.
5. Add the missing universal outcomes required to unlock complete 5x5, points,
   and broader custom-league adapters.
