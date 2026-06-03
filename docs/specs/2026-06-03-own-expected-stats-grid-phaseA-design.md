# Our Own Expected Stats (EV×LA Grid) — Phase A Faithfulness — Design

**Date:** 2026-06-03
**Status:** Draft / pending review
**Builds on:** Rung 3 (Statcast input de-noising), which blends toward **Savant's** `xBA`/`xSLG`. This rung computes **our own** xBA/xSLG so the hitting stack stops depending on Savant's expected-stat calculation.

## Goal

Build our own expected-stats model — an empirical exit-velocity × launch-angle grid fit from raw Statcast batted-ball data — and **prove it reproduces Savant's `xBA`/`xSLG`**. This is the honest answer to "are the values truly ours?": replace the one borrowed ingredient (Savant's expected stats) with our own calculation.

**Phase A is a cheap faithfulness gate.** It commits only to a small batted-ball pull and answers "can EV+LA, computed by us, reproduce Savant's xBA?" The expensive full 2015–25 pull and re-running the Rung 3 de-noise with our numbers is **Phase B, gated on Phase A passing.**

## Data (audited 2026-06-03)

Savant `statcast_search` CSV returns per-ball `launch_speed` (EV), `launch_angle` (LA), `events` (outcome), `batter` (MLBAM id). ~130k balls-in-play/season; ~25k-row response cap; rate-limited.

- **Phase A window: 2021–2023** (~375k balls) — enough for a dense grid *and* to score players for the faithfulness check. ~150 chunked requests.
- **Pull must be resumable + throttled + retrying.** The real risk is partial failure mid-pull, so fetch in **date chunks sized under the ~25k cap (~5-day windows)**, throttle between requests, retry a failed chunk, and make re-runs idempotent (skip chunks already fetched). Not a single 150-request blast.
- **Raw balls are not committed** (too large / fragile). We commit: the fitted grid artifact + per-player-season our-xBA/xSLG snapshots.

## The grid (`projections/models/expected_stats_grid.py`)

A 2D empirical grid binned by **EV (2 mph) × LA (5°)**. Each cell stores, from the `events` field, the empirical `P(hit)` and `E[total_bases]` (single→1 base & hit, double→2, triple→3, home_run→4, all outs→0). A player-/league-agnostic physics table.

- **Sparse-cell fallback** (thin cells are noisy): require a min sample per cell; below it, fall back in order — pool immediate EV/LA neighbors → EV-only marginal rate → global rate.
- **Missing-EV balls** (bunts / untracked contact) are **excluded** from both grid-fit and scoring (pinned, not silently bucketed).
- Fitted grid stored as an immutable JSON artifact (cell → `{n, p_hit, e_bases}`), same immutability contract as the other backbones.

## Scoring (our xBA / xSLG)

For each player-season: `our_xBA = Σ grid.p_hit(ball) / AB`, `our_xSLG = Σ grid.e_bases(ball) / AB`, summed over the player's batted balls, with **`AB` joined from the hitting backbone**. We match Savant's AB-denominator conventions as closely as the data allows; small definitional offsets (sac flies, edge cases) are tolerable because the gate is correlation-led (below).

**Self-fit inflation is negligible** — one player is ~0.1% of the ~375k league balls, so their own balls barely move their cells' rates. (If we want zero doubt, fit the grid on 2021–22 and score 2023 — still cheap. Offered as an option; default is pooled-window fit.)

## The faithfulness gate (success bar — corr-led, MAE characterized)

We already have **Savant's `xBA`/`xSLG` on disk** (Rung 3 snapshots), so the comparison needs no extra pull.

- **PRIMARY (pass/fail): `correlation(our_xBA, Savant_xBA) ≥ 0.95`** across qualified player-seasons in the window, and the same for xSLG. This is the bar for "we reproduce it."
- **SECONDARY (characterized, NOT hard-fail): mean |our − Savant|** is *reported and decomposed*, not pass/failed. We expect a systematic residual: **Savant's xBA also uses sprint speed** (fast hitters beat out weak grounders), which EV+LA alone omits. So fast/slow players will be off in a *known direction*. That residual is the **signpost to the next input** (add sprint speed → close the gap), not a failure of the rung.

If correlation clears 0.95, we have genuinely reproduced xBA from our own calculation; the MAE residual quantifies exactly what sprint-speed would add.

## Non-Goals

- The full 2015–25 batted-ball pull and re-running the Rung 3 de-noise with our numbers — **Phase B**, gated on this.
- A learned model (logistic/GBM) — stdlib-only repo; the empirical grid *is* how xBA is defined.
- Leakage-safe grid fitting — Phase A is a **descriptive** faithfulness check (reproduce a contemporaneous metric), not prediction. Leakage-safe fitting is Phase B's concern (when the grid feeds the predictive de-noise).
- Sprint-speed input — the named next lever, not this rung.
- Wiring into the app or the de-noise — behavior-neutral; this rung only produces + validates the artifact.

## Components

- `projections/data/batted_balls.py` — resumable/throttled chunked pull + CSV parse → `(ev, la, events, batter, season)` rows for a window.
- `projections/models/expected_stats_grid.py` — `fit_grid(balls)`, sparse-cell fallback, `p_hit`/`e_bases` lookup, per-player scoring → our xBA/xSLG given AB; store/load the grid artifact.
- `projections/backtest/grid_faithfulness.py` — compute our xBA/xSLG over the window, join Savant's stored values, report corr (gate) + MAE (characterized, optionally split by player speed tendency).

## Success Criteria

1. **Pull:** resumable, throttled, retrying batted-ball pull for 2021–2023; a re-run skips already-fetched chunks; partial failure doesn't corrupt state.
2. **Grid:** fitted EV×LA grid with sparse-cell fallback, stored immutably; sanity unit test — a 100 mph / 12° cell has high `p_hit`, a 65 mph / −30° (weak grounder) low.
3. **Scoring:** our xBA/xSLG per player-season; the sum/AB math unit-tested on a tiny hand-built grid.
4. **Gate (the verdict):** `corr(our_xBA, Savant_xBA) ≥ 0.95` and `corr(our_xSLG, Savant_xSLG) ≥ 0.95` across qualified player-seasons; MAE reported and characterized against the sprint-speed expectation. Honest WIN (reproduced) / SHORTFALL (diagnose) either way.
5. **No regressions:** additive; existing suite stays green.

## Risks & limitations

- **EV+LA omits sprint speed** — the known faithfulness ceiling; expected residual, quantified not hidden, and the pointer to the next input.
- **Pull fragility** — Savant rate-limits/changes params; mitigated by resumable chunks + throttle + retry, and Phase A's small window.
- **Definition drift vs Savant** (AB denominator, excluded balls) — kept tolerable by the correlation-led gate; missing-EV handling pinned.
- **Could fall short of 0.95** — then it's a finding: EV+LA alone isn't enough to call it faithful, and sprint speed (or more) is required before claiming "our xBA." Reported plainly; no fudging the bar.
