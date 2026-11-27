# ValuCast Wave 2 — Prospect Value Rebalance (spec)

Date: 2026-06-26
Status: PROPOSED — small safe cut awaiting approval; blend rebalance is shadow-only (does not ship in this wave).
Predecessor: Waves 0–1 shipped in `fe31578` (clean bugs + card single-line parity); sentinels in `f497c8e`.
Reviewed: Codex (plan review 2026-06-26) — "small cut yes, blend no." This spec is the small cut.

## Problem

The served prospect value is a current-skill sort wearing an outcome label:

`value = 0.76·model_score + 0.15·universal_outcome_index + 0.06·investment + 0.03·reliability`
(`prospects/rank_v1.py:99-129`), where `model_score = 100·(0.58·expected_outcome_score + 0.42·impact)`.

The full root-cause chain (76% fallback term, throttled validated signal, −28 thin penalty,
stale-pitcher floats) is documented and real, but **fixing the blend is not safe yet** — the
acceptance gate for a reweight is circular (the proposed outcome composite correlates 0.99 with
the tier it would be scored against) and the backtest is effectively n=1 (only the 2021 fold
carries signal). So this wave ships **only the parts that are correct regardless of the blend**:
record-selection consistency and a recalibrated thin penalty. The blend change is specified here
as deferred shadow work with a non-circular gate.

## Scope of THIS wave (the small safe cut)

- **W2.4 — unify record selection on one best-single-level record.** Foundation; ships.
- **W2.2 — recalibrate the thin-sample penalty (cap 28 → 12, keyed to the displayed record).** Ships.
- **W2.3 — CUT.** Once selection is unified, stale-prior-vs-bad-current should largely disappear
  (Perez gets scored on his current line). Do not build a separate staleness regression on spec.
  Revisit only if a residual list proves the class still exists after W2.4.
- **W2.1 — DEFERRED, shadow only.** The gate-aware blend + outcome composite does NOT ship in this
  wave. It runs as a shadow column behind a non-circular gate (below) and flips live only when
  realized-outcome validation shows lift.

## Goal / non-goals

**Goal of the small cut:** every surface (score, availability penalty, card line, read line)
describes **one** record; the thin penalty stops crushing legitimate half-season lines; the
inversion exemplars move the right direction. No blend weights change, so the board re-baselines
only where record-selection and the penalty were wrong — not site-wide.

**Non-goals (explicit — do NOT do these):**
- Do **not** change blend weights in this wave (that is W2.1, shadow only).
- Do **not** pool / MLE-combine multiple levels into one line. The repo already decided against
  this in `docs/specs/2026-06-17-best-single-level-sample-design.md:14-26` — single level only,
  never a combine. Unify on the **best single level**, not a blend.
- Do **not** retune the age-for-level curve (verified not a defect; leave `_age_level_context_score`).
- Do **not** lower the universal model's 2.0% Brier promotion bar.
- Do **not** calibrate the `star` tier (sampling noise: ~76 hitter / 58 pitcher positives).
- Do **not** build the points-pitcher scoring model (separate work; chip already suppressed).

## W2.4 — Unify record selection (the whole contract)

Today **four** selectors pick a player's "the record" independently and disagree:

- `prospects/model.py:912` — largest **sample** (can pick a prior-year line: this is why Fernando
  Perez is *scored* on his 2025 94-IP line while the card shows the current 12.7-IP / 7.11-ERA line).
- `prospects/universal.py:278` — highest **level**.
- `prospects/rank_v1.py:415` — highest **level** (display / factual line).
- `prospects/availability.py:161-171` — its own selection for the availability penalty.

Current mismatch counts vs the displayed card line: model/display **476**, universal/display
**361**, availability/display **658** (top-300 examples: Theo Gillen, Noble Meyer, Chase Harlan,
Caleb Bonemer).

**The fix:** one selection rule, applied by all four call sites.

Selection rule (the existing best-single-level rule, `2026-06-17-...:36-37,62-69`):
1. Prefer **current-season** (2026) records over prior-year.
2. Among current-season **single-level** samples that clear the percentile threshold
   (hitters ≥ 100 PA, pitchers ≥ 20 IP), pick the **largest** (most PA / IP). Single level only —
   **never a combine / pool.**
3. If no current-season level clears threshold, fall back to the largest current-season single-level
   line present (thin — W2.2's penalty then applies to it), and only then to the prior fallback.

Contract: the selected record's **identity** (mlbam_id + season + level + sample) must be identical
across `model_score`, the dynasty tier, the availability penalty, the card line, and the read line.
The *consistency* is mandatory; where the current code legitimately needs a different view it must
derive it from the one selected record, not re-select.

Effect: `model_score`, the dynasty tier, the availability penalty, and the displayed line all
describe one record; the W2.2 penalty (keyed to that record) fires on the right sample; Perez is
scored on his current line.

## W2.2 — Season-progress thin-sample penalty (`rank_v1.py:1245-1282`)

- Lower cap: `THIN_SAMPLE_CONFIDENCE_PENALTY_MAX 28.0 → 12.0`.
- Key thinness to the **unified selected / displayed record's sample** (W2.4's record), NOT the
  model's absolute-200-PA reliability.
- Re-key thinness to **season progress**, not an absolute curve:
  - `season_progress = clamp01((today − MILB_OPEN)/(MILB_CLOSE − MILB_OPEN))` (≈0.51 on 6/26; 2026
    open ~3/27, close ~9/21; module constants, fail-soft to 0.5).
  - `EXPECTED_FULL_SEASON = {hitter: 600 PA, pitcher: 130 IP}`;
    `expected_to_date = EXPECTED_FULL_SEASON[role]·season_progress` (≈307 PA / 66 IP today).
  - `frac = clamp01(sample / expected_to_date)`; `thinness = (1 − frac)**1.5`;
    `penalty = −12.0·thinness` (×0.75 if `_high_pedigree`).
- Before/after (final board score): Tre Morgan 0.96→~14, Sio 0.71→~16.6, Franco 3.28→~15.9; a true
  2-IP fluke still ≈ −11.5 (near cap). Half-season lines stop being crushed; genuine 1-PA/2-IP
  noise still maxes out.

W2.2 is calibration-judgment, not outcome-gateable (the validated set excludes thin samples by
construction — same basis as the existing penalty). It self-heals as samples fill in. The shadow
diff + exemplar checks below are the gate.

## W2.1 — Gate-aware blend + outcome composite (DEFERRED — shadow only, does NOT ship here)

Specified so the shadow column is built correctly, not to ship in this wave.

- Make blend weights gate-aware at `rank_v1.py:~1036`: when the per-row hitter gate is `fallback`
  (~48% of rows), down-weight `model_score` and up-weight an `outcome_composite`. Pitchers (gate
  `active`) keep current weights.
- `outcome_composite`: **simplify to `role_or_better_probability`** (drop the degenerate `star`
  and `bust` terms — too few positives / unstable), rescaled to a true 0–100, replacing the lossy
  `universal_outcome_index = tier·50` (realized range only 0–46).

**Non-circular acceptance gate (required before any live flip — NOT met today):**
- Score the shadow value against **realized outcomes** (the labeled cohort's actual role/star
  results), NOT against `expected_factual_outcome_tier` (the same target the composite is built
  from — that is the circularity Codex flagged).
- Require lift on **≥ 1 more temporal fold** than the single 2021 fold that currently carries the
  `active` verdict (2018/2019 must not regress).
- **Calibrate `established_probability` first** (isotonic on established only, 283 hitter / 415
  pitcher positives; its own shadow reliability-diagram gate) before it feeds the composite.
- Only when all three hold does W2.1 flip from shadow to live. Until then it is observe-only.

## Acceptance gate for the small cut (W2.4 + W2.2) — shadow-diff + exemplars

The small cut changes record selection and a penalty, not the blend, so a full backtest is not the
gate. Minimum bar to ship:

1. **Selector consistency.** model/universal/availability vs the card line mismatch counts drop to
   **0** wherever all have a selected record (from 476 / 361 / 658 today).
2. **One cheap invariant test.** For the exemplar set, the selected record identity
   (mlbam_id + season + level + sample) used for score, availability penalty, card line, and read
   line is **identical**. This test fails loud if any selector drifts again.
3. **Exemplars move the right direction:** Perez (down — scored on current line), Noble Meyer,
   Sam Shaw < Devin Taylor, Jean Carlos Sio, Jose Franco, Ixan Henderson, Tre Morgan.
4. **No top-100 chaos.** Manually inspect the largest board movers, **especially pitchers**, for
   nonsense before publishing.
5. **Existing sentinels stay green:** peak Run-Prevention direction (`peak_projection.py`), scouting
   no-sample-with-statline (`scouting/repository.py`), public-snapshot freshness.

## Rollout

1. W2.4 (record unification) first — all four selectors on one rule.
2. W2.2 (thin penalty) next — keyed to the unified record.
3. Run the acceptance gate above; diff the board; spot-check exemplars + top pitcher movers.
4. Commit + push **only when no daily build is in flight** (the build fails loud on a push race —
   coordinate the commit so it doesn't race a refresh; do not push during a build window).
5. Daily build regenerates artifacts; verify exemplars on prod.
6. W2.1 stays shadow until its non-circular gate is met (separate, later).

## Test / contract impact

- New/updated tests: unified record selection (the invariant test above), the season-progress thin
  penalty (cap 12, keyed to displayed record), and the four-selector parity assertion.
- Many existing value-*magnitude* assertions shift where record selection / penalty were wrong —
  migrate them to ordering / relative-identity assertions where possible.
- No blend-weight tests in this wave (W2.1 is shadow); add them when W2.1 flips.
