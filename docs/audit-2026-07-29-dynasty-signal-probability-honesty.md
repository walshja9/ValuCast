# Audit: `dynasty_signal` Probability Honesty

**Date:** 2026-07-29
**Commissioned by:** owner disposition item 2 on
`docs/review-2026-07-29-sirota-disagreement-adversarial-review.md` ("the
immediate honesty problem"). Read-only measurement against committed
artifacts at `931c916`; no fix is implemented in this document's commit.

## Finding (reframed per the 2026-07-29 senior review on PR #32)

**The two probability heads are mutually inconsistent, and only one of them
has committed value-level reliability evidence — the one NOT being
published.** The displayed `dynasty_signal` values are compressed toward
the base rate with a hard board-wide ceiling of 0.56; when the board is
binned by the v0.6 outcome score, the v0.6 head's committed OOF evidence
implies realized role-or-better rates roughly 2× the displayed figures
across scores 0.15–0.40 and up to ~2.7× above 0.40. Strictly, this
measures **cross-head inconsistency**: the displayed universal-head values
and the v0.6 head cannot both be right, and the repo's only
value-vs-frequency reliability evidence (v0.6 OOF, n=2,901, ECE
0.017/0.021) sides against the displayed numbers. **Direct miscalibration
of the universal head is not established** — no universal-head OOF
reliability data exists in the repo to test it, which is itself disposition
option 3. Sirota (displayed 27.7% vs 54.7% [43.4, 65.4] OOF-implied for his
v0.6 bin) is a representative instance.

## Provenance (the chain that produces the number)

`dynasty_signal` comes entirely from the **shadow-only universal model**
(v0.4.0), not the v0.6 head that produces the score:
`prospects/universal.py` `TARGET_SPECS`/`train_target`/`score_current` →
`_coherent_outcome_distribution` → `prospects/dynasty.py:45-73`
`decision_signal` (pure rename, no recalibration) →
`rank_v1.py:2324` verbatim copy onto every board row →
`build_public_dynasty_snapshot.py:689` verbatim into the public snapshot.

**The served values are a hybrid of gate-failed fallbacks and active ridge
heads.** The universal model's `established_probability` gate is `fallback`
in BOTH roles (a 25-neighbor empirical vote at ~0.04 resolution), and
`star_probability` likewise failed both roles — the same reason
`rank_v1.py:997-1008` already excludes star from the live score. However,
`_coherent_outcome_distribution` (`prospects/universal.py`) clamps the
served established value up to the ACTIVE `regular_probability` /
`rotation_probability` ridge heads and writes it back: against the cited
`931c916` layer, **1,305 of 2,924 profiles (967 hitters, 338 pitchers)
serve a value off the 0.04 neighbor grid** — i.e. the ridge side of the
max — including Sirota's own 0.2768 (his ridge `regular_probability`). So
the published number is max(gate-failed vote, active-but-different-target
ridge head); neither branch has value-level reliability evidence. The
repo's own comment on the derived peak fields still applies:
"UNCALIBRATED universal-model outcome frequencies… observe-only"
(`peak_projection.py:531`).

## Board-wide cross-head divergence (displayed vs v0.6-OOF-realized, by v0.6 score bin)

Read this table as a two-head consistency check, not a direct reliability
curve for the universal head: rows are binned by the v0.6 score, so the
universal head could in principle differ per-bin if it carried independent
information — though no independent signal can explain a 0.56 ceiling
against 87–93% realized top-bin rates.

Hitters (board n=1,363; OOF n=1,379, cohorts 2016–2019):

| Score bin | Displayed role+% | Realized role+% | OOF n | Wilson 95% |
|---|---|---|---|---|
| 0.00–0.10 | 8.0 | 4.5 | 796 | [3.3, 6.2] |
| 0.10–0.15 | 13.2 | 15.9 | 208 | [11.5, 21.4] |
| 0.15–0.20 | 18.5 | **35.7** | 140 | [28.3, 43.9] |
| 0.20–0.25 | 22.9 | **36.0** | 100 | [27.3, 45.8] |
| 0.25–0.30 | 26.0 | **56.8** | 44 | [42.2, 70.3] |
| 0.30–0.35 | 31.1 | **51.6** | 31 | [34.8, 68.0] |
| 0.35–0.40 | 36.5 | **59.1** | 22 | [38.7, 76.7] |
| 0.40–0.50 | 34.7 | **93.3** | 15 | [70.2, 98.8] |
| 0.50–1.00 | 41.5 | **87.0** | 23 | [67.9, 95.5] |

Pitchers show the same shape at lower magnitude (board-weighted mean
understatement +2.9 pts vs hitters' +8.0; >2× above score 0.40). Full
tables and the join method are in the audit lane's output; caveats: OOF
population is 2016–2019 cohorts vs the 2026 board (mix shift possible), and
conditioning on the v0.6 score would permit per-bin differences only if the
universal head carried independent information — which cannot explain a
0.56 ceiling against 87–93% realized top rates.

## Where the values reach users

- **Rendered HTML: nowhere** — the 2026-07-19 prospect-evidence-honesty
  change removed the percentages from templates, and scouting prose is
  scrubbed of probability language. The glossary has no term for them.
- **Committed/public JSON: everywhere** — every board row in
  `valucast_prospect_rank_v1.json`, every prospect row in
  `public_dynasty_snapshot.json`, the prediction archives, and fallback
  driver strings ("role+ probability 0.2768").
- **One user-visible prose path**: `web/prospect_percentiles.py:757-771`
  turns `bust_risk >= 0.70` into card copy ("the projection caps at a
  bench/depth role") — qualitative wording driven by the miscalibrated
  value without displaying it.
- **The live score itself**: `universal_outcome_index = (role_or_better −
  star) × 50` feeds the rank blend (`rank_v1.py:996-1018`) and inherits the
  same compression. This is inside the model freeze and is NOT addressed
  here; it belongs to the research track with the cross-role normalization
  item (owner disposition item 6 discipline applies).

## Calibration coverage asymmetry

The v0.6 head has per-player OOF (n=2,901) plus a committed reliability
curve with ECE (hitter 0.017 / pitcher 0.021). The universal head — the one
whose numbers are published — has **no** value-vs-realized-frequency check
anywhere in the repo: its backtests cover relative Brier vs baselines,
ordering, and top-quartile precision only.

## Disposition options (owner decision required; nothing implemented)

1. **Stop publishing the raw probabilities** in public JSON (strip
   `dynasty_signal` from board/snapshot rows as never-rendered,
   gate-failed values — the `peak_summary` precedent), keeping them in
   observe-only internal artifacts.
2. **Keep publishing with an honest label** (rename fields to
   `uncalibrated_neighbor_vote_*` or attach an explicit uncalibrated
   disclaimer at the artifact level), and re-point the `bust_risk` card-copy
   threshold at evidence that has a reliability curve.
3. **Build the missing reliability artifact** for the universal head and
   let the numbers stand or fall on it.

Any of these is display/artifact-layer work; none touches the frozen score.
The `universal_outcome_index` compression inside the score is recorded here
as a research-track fact and deliberately not acted on.
