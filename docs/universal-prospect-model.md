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

## Version 0.4

Version 0.4 is a shadow-only A/A+/AA/AAA foundation. It predicts:

- Establishment probability for hitters and pitchers
- Factual star probability from MLB volume and production thresholds
- Regular-hitter and rotation-volume probability
- Representative MLB volume and production, conditional on establishment
- Every outcome required by the Diamond Dynasties 7x7 adapter

The profile now publishes a coherent factual outcome distribution:

- `bust_probability = 1 - established_probability`
- `star_probability` is capped at establishment probability
- `role_probability` is the remaining established probability

The star definition is independent of fantasy scoring: hitters require a
post-cohort `450 PA / .800 OPS` season; pitchers require a post-cohort
`120 IP / 3.75 ERA` season. The published hitter star-probability source reached
`0.842135` held-out rank concordance and the published pitcher source reached
`0.813632`. Both currently publish the strongest factual-neighbor baseline
because ridge did not earn its target-level promotion gate.

Star probability does not feed the league adapter or DD value. Expected
category impact and ceiling probability remain separate until a later
dynasty-valuation gate proves how they should interact.

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

The scoring implementation now lives in the source-neutral
`projections/league_adapter.py` contract. Prospect and MLB projection models
remain separate, but both can emit the same rows:

- stable player identifier and role
- projected playing-time volume
- factual category projections
- optional source metadata

League settings are applied only after that boundary. The shared contract does
not make a prospect model and an MLB projection model the same model.

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

## Adapter Backtest And Promotion Gate

```powershell
python scripts/build_prospect_adapter_backtest.py
```

Output:

- `data/models/valucast_prospect_adapter_backtest.json`

The adapter replay uses a fixed three-year post-cohort outcome horizon. Each
test cohort may use only training cohorts whose complete three-year horizon
closed before the test cohort. This prevents later MLB results from leaking
into an earlier historical decision. Candidate target methods are selected
inside each eligible training window; the comparison baseline uses factual
level-age priors for every target.

The first complete DD 7x7 replay remains on hold:

- Hitter rank concordance: `0.779231` versus `0.723494` baseline (`+7.70%`);
  however, top-quartile precision was `0.293608` versus `0.301695`, so the
  no-regression guard did not pass.
- Pitcher rank concordance: `0.538083` versus `0.533152` baseline (`+0.92%`),
  below the required `+2%`; top-quartile precision also trailed the baseline.

The artifact therefore blocks a DD shadow consumer and all live DD value
influence. Even after both historical role gates pass, dated forward archives
must demonstrate stability before any capped live influence is considered.

Version 0.4 also emits category and target-source ablations. They identify the
current blockers without changing league weights:

- Hitter ratio-rate categories are the largest drag on top-quartile precision;
  removing `AVG` or `OPS` in research improves the diagnostic, but production
  adapters must not omit real league categories.
- Pitcher rate/context outcomes, especially `WHIP`, `ERA`, and `L`, add
  substantial ordering noise.
- Replacing only pitcher establishment probability with the level-age prior
  improves both held-out ordering and top-quartile precision, but that
  post-hoc result is diagnostic evidence, not an eligible production override.

## Next Research Blockers

1. Add complex-league and rookie-ball coverage without weakening enrollment or
   outcome-completeness rules.
2. Add role-neutral underlying MLB skills where the source contract supports
   them, rather than fantasy-category outcomes.
3. Improve pitcher separation and both roles' ratio/outcome-rate projections
   without lowering or tuning against the adapter promotion gates.
4. Expand completed historical coverage enough to test a longer outcome
   horizon without introducing label leakage.
5. Design and validate a separate dynasty ceiling/risk layer that may consume
   the factual outcome distribution without feeding preferences back into the
   universal model.
6. Forward-test dated profiles and adapter disagreements.
7. Plug ValuCast's separate MLB projection models into the shared league
   projection contract.
8. Add the missing universal outcomes required to unlock complete 5x5, points,
   and broader custom-league adapters.
