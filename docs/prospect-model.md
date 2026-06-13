# ValuCast Prospect Model

## Ownership

ValuCast owns the model code, validation, prediction artifacts, and eventual
product ranking. Diamond Dynasties owns upstream factual collection and exports
the sanitized contract at `data/dd/prospect_model_inputs.json`.

The model does not read `dd_dynasty_feed.json`. That feed contains externally
informed rankings and dynasty values, so it is not an acceptable training
boundary for an independent ValuCast opinion.

## Version 0.6

Version 0.6 is an observe-only AA/AAA model with two independent axes. The
first trains separate hitter and pitcher ridge models on an ordinal MLB outcome
bridge:

- Bust: `0.0`
- MLB role player: `0.5`
- MLB star: `1.0`

Validation is player-grouped and expanding-window by cohort year. Each role and
the combined board must beat the stronger of a smoothed level-age prior and a
25-neighbor factual baseline by at least 2% out of sample. Partial-season rates
are regressed toward historical means before scoring.

The second axis predicts the best forward MLB season across canonical DD 7x7
categories that have adequate coverage in the historical cache. It derives
`SV+HLD` from factual saves and holds rather than substituting saves alone.
Categories automatically activate when their coverage reaches at least 80% of
the best-covered category for that role.

- Canonical hitters: `R`, `HR`, `RBI`, `SB`, `AVG`, `OPS`, `SO`
- Canonical pitchers: `K`, `QS`, `SV+HLD`, `ERA`, `WHIP`, `K:BB`, `L`

Pitcher seasons are scored against the better applicable DD role group:
starters use `K/QS/ERA/WHIP/K:BB/L`, while relievers use
`K/SV+HLD/ERA/WHIP/K:BB/L`. This avoids treating a closer's zero QS or a
starter's zero saves-plus-holds as a failure.

The June 12, 2026 historical backfill reached adequate coverage for every
canonical category, so the artifact now reports a direct 7x7 target. The impact
axis exists to capture fantasy-relevant outcomes and to value reliever seasons
that the starter-heavy ordinal label misses.

The hitter impact model uses a two-stage hurdle architecture because the direct
7x7 target is zero-inflated:

1. Estimate whether the prospect produces a meaningful future MLB season.
2. Estimate direct 7x7 impact conditional on producing one.

Six restrained interactions model how power and discipline translate by level.
The original interaction-space 25-neighbor model remains an explicit canonical
baseline, preventing the new feature space from earning an easier gate by
weakening its comparison set.

Current held-out result:

- Combined direct 7x7 impact board: active, `+2.43%` versus the canonical
  factual-neighbor baseline
- Hitter direct 7x7 impact model: active, `+2.08%`
- Pitcher direct 7x7 impact model: active, `+2.72%`

All three direct-impact gates now pass. The model remains shadow-only because
the v0.6 hitter architecture was selected during retrospective research and
must confirm itself in dated forward archives before live promotion.

The artifact keeps the two opinions separate as `valucast_prospect_rank`
(ordinal outcome bridge) and `valucast_impact_rank` (partial-category impact).
Neither rank is consumed by the live board.

## Input Contract

Allowed:

- MLBAM identity
- Factual MiLB statistics, age, level, position, and role
- Forward MLB outcome labels derived from factual MLB performance
- Factual post-cohort MLB seasons for the available partial-category impact axis
- Factual MLB service used to remove graduated players

Prohibited:

- External prospect rankings
- External projections
- Dynasty rankings, values, or market prices
- ValuCast's current live prospect order

The model validates the source-policy flags before training. Current candidates
without an MLBAM-keyed service fact fail closed and are not ranked.

## Rebuild

Run the factual export from Diamond Dynasties, then build the model from
ValuCast:

```powershell
python generate_valucast_prospect_inputs.py --copy-to-valucast
python scripts/build_prospect_model.py
```

## Promotion Gates

The model remains observe-only until:

1. It covers the intended prospect universe, including lower minors and new
   draftees through separate factual priors.
2. Direct fantasy outcome labels replace the ordinal bridge target.
3. Hitter and pitcher models independently beat their strongest factual
   baselines walk-forward.
4. Top-N hit rate, calibration, and rank stability pass defined thresholds.
5. Dated full-universe archives provide enough forward evidence.
6. A clean-room test proves external rankings and projections cannot change the
   ValuCast prospect rank.

An active statistical gate is evidence worth continuing. It is not automatic
permission to replace the live prospect board.

The next research step is forward confirmation of v0.6 plus broader lower-minors
coverage and a factual draft prior. Richer factual MiLB features remain a
candidate only if they improve absolute held-out error against the unchanged
canonical baseline. External rankings and projections remain prohibited inputs.
