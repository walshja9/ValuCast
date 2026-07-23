# ValuCast Prospect Model

## Ownership

ValuCast owns the model code, validation, prediction artifacts, and eventual
product ranking. Diamond Dynasties owns upstream factual collection and exports
the sanitized contract at `data/dd/prospect_model_inputs.json`.

The model does not read `dd_dynasty_feed.json`. That feed contains externally
informed rankings and dynasty values, so it is not an acceptable training
boundary for an independent ValuCast opinion.

## Version 0.6

Version 0.6 is the incumbent AA/AAA model with two independent axes. The first
trains separate hitter and pitcher ridge models on an ordinal MLB outcome
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

The current artifact reports a partial-category fantasy-impact target. It
covers every canonical hitter category and all pitcher categories except `QS`,
so direct 7x7 is not active. The impact axis exists to capture fantasy-relevant
outcomes and to value reliever seasons that the starter-heavy ordinal label
misses.

The hitter impact model uses a two-stage hurdle architecture because the
partial-category impact target is zero-inflated:

1. Estimate whether the prospect produces a meaningful future MLB season.
2. Estimate partial-category fantasy impact conditional on producing one.

Six restrained interactions model how power and discipline translate by level.
The original interaction-space 25-neighbor model remains an explicit canonical
baseline, preventing the new feature space from earning an easier gate by
weakening its comparison set.

Current held-out partial-category result:

- Combined impact board: active, `+3.03%` versus the canonical
  factual-neighbor baseline
- Hitter impact model: fallback, `-1.59%`
- Pitcher impact model: active, `+5.55%`

The incumbent artifact keeps the two opinions separate as
`valucast_prospect_rank` (ordinal outcome bridge) and `valucast_impact_rank`
(partial-category impact). Prospect Rank v1 consumes the incumbent v0.6 model
score at weight `0.76` and feeds the live ValuCast rank.

The v0.7 artifact is a non-live feature-readiness preview. It does not replace
v0.6 or feed the live ValuCast rank.

## Stage 1 / Stage 2 boundary

Stage 1 is ValuCast's real-baseball outcome layer. It produces role-specific
arrival, sustained-role, and representative MLB production forecasts. The
served incumbent currently binds Prospect Model v0.6 with the universal/dynasty
outcome profile through contract version 1.0.0.

Stage 2 is the deterministic Rank v1 and downstream league-value translation.
It consumes only an incumbent or promoted Stage 1 contract plus timestamped
availability/opportunity and league-format rules. Research and shadow challenger
states are rejected before scoring. The Stage 1 contract migration changed no
board score, rank, value, cap, Role Watch, or publication decision.

<!-- prospect-model-contract:start -->
```json
{
  "live_model_artifact": "data/models/valucast_prospect_model.json",
  "live_rank_artifact": "data/models/valucast_prospect_rank_v1.json",
  "model_score_consumed_by_live_rank": true,
  "live_model_score_weight": 0.76,
  "impact_target_kind": "partial_category_fantasy_impact",
  "impact_target_direct_7x7": false,
  "missing_pitcher_categories": ["qs"],
  "v0_7_artifact": "data/models/valucast_prospect_model_v0_7.json",
  "v0_7_status": "shadow_preview",
  "v0_7_purpose": "Feature-readiness preview for Prospect Model v0.7."
}
```
<!-- prospect-model-contract:end -->

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

## Future Model Promotion Gates

A future replacement for the incumbent model remains non-live until:

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

The v0.7 shadow preview is the non-live feature-readiness step. Richer factual
MiLB features remain a candidate only if they improve absolute held-out error
against the unchanged canonical baseline. External rankings and projections
remain prohibited inputs.
