# Projections Rung 2 — Reliability-Weighted (Stat-Specific) Regression — Design

**Date:** 2026-06-02
**Status:** Approved (design)
**Builds on:** `2026-06-02-projections-foundation-hitting-design.md` (Rung 1: Marcel hitting + harness)

## Goal

Beat **classic Marcel** (not just a persistence baseline) on held-out seasons by regressing each hitting component toward the league mean by a component-specific amount derived from that component's empirical reliability — instead of the single global `n_reg` Rung 1 applies to everything (`marcel_hitter.py:39`).

This is the cheapest plausible way to beat classic Marcel without building the Statcast pipeline. Power and strikeout rates are far more predictive year-to-year than batting average; regressing them all identically over-shrinks the stable stats and under-shrinks the noisy ones. Rung 2 fixes exactly that.

## Why this rung, why now

The Rung 1 tuning pass tied: a 2-knob grid (`n_reg`, `pa_base`) selected the classic Tango constants, so tuned == untuned. That told us the *global* knobs are already well-calibrated. The remaining structural weakness is the **uniform** regression. This rung tests the one lever with theory behind it, using only data we already have.

## The model

For target season `T`, using only seasons `< T`:

1. **Per-component reliability `r_c`** (the new piece, defined precisely below).
2. **Per-component regression constant:**
   ```
   n_reg_c = n_reg_base × (r̄ / r_c) ^ gamma
   ```
   - `r̄` = PA-weighted mean of `r_c` across projected components.
   - `(n_reg_base, gamma)` are the **only two tunable knobs**.
   - More-reliable-than-average components (`r_c > r̄`) get a *smaller* `n_reg` (shrink less); noisier components get a *larger* one.
3. **Regression** uses `n_reg_c` in place of the scalar `n_reg`:
   ```
   regressed_rate_c = (weighted_total_c + n_reg_c · league_rate_c) / (weighted_PA + n_reg_c)
   ```
4. Everything downstream (age curve, PA projection, component invariants, composition) is **unchanged** from Rung 1.

**Classic Marcel is nested:** `gamma = 0` ⟹ `n_reg_c = n_reg_base` for all `c` ⟹ identical to Rung 1. The model cannot do worse than classic Marcel except by overfitting `gamma`, which the carryover guard (below) catches. The entire experiment reduces to: **does `gamma > 0` beat `gamma = 0` on unseen seasons?**

## Defining reliability `r_c` (the data-limitation-honest part)

**We have season-level totals only.** "Stabilization" here does **not** mean a within-season split-half PA study (Carleton-style) — that requires game-log/split data we have not pulled. It means **empirical year-to-year, PA-weighted predictive reliability** of the component's per-PA rate, computed from our historical season snapshots:

- Form consecutive-season pairs `(rate_c[y], rate_c[y+1])` for players with PA ≥ `MIN_EVAL_PA` in **both** years, across all season pairs **strictly before `T`** (leakage-safe).
- `r_c` = the **PA-weighted Pearson correlation** between the earlier-year and later-year rates (weight = min/harmonic of the two seasons' PA, so a player anchors the estimate in proportion to sample).
- **Clamp** `r_c` to `[R_FLOOR, 1.0]` (e.g. `R_FLOOR = 0.05`) so a near-zero-reliability stat can't produce an explosive `n_reg`; **cap** `n_reg_c` at `N_REG_MAX` as a second guard.

This is a *relative reliability ordering* good enough to differentiate regression. It is explicitly an approximation of true talent reliability; literature-informed priors (HR/K/BB stabilize fast; AVG/BABIP slow) are used only as a **sanity check** on the ordering, never hard-coded into the model. If true within-season stabilization is wanted later, that is a **separate data add** (game logs / split halves) and its own rung — out of scope here.

## Components in scope

The reliability map covers the projected rate components from Rung 1 (`1B, 2B, 3B, HR, BB, HBP, SF, SO, SB, CS, R, RBI`).

**R and RBI get explicit treatment as noisy context stats.** Their year-to-year reliability will be low not only from sampling noise but because they are genuinely lineup/team-context-driven — a player's RBI depend on teammates on base. Reliability-weighting will (correctly) regress them heavily, but it **cannot** recover signal that isn't in the player's own line. The spec's stance: report R/RBI honestly as the weakest categories, do **not** tune the global knobs toward improving them, and never claim reliability-weighting "fixed" them. A real fix needs lineup/context modeling, a future concern.

## Harness changes

1. **Classic-Marcel baseline as a first-class metric.** Rung 1's harness scores Marcel vs *persistence*. Add a comparison of a candidate config vs **classic Marcel** (`gamma = 0`): per-stat `mae_ratio_vs_classic` and a `beats_classic` verdict. Persistence stays only as a sanity floor.
2. **Tuning→scoring carryover guard.** A bigger parameter space makes "won the tuning block" cheap. The harness must report both the tuning-block improvement and the scoring-block improvement and flag `carryover_confirmed` only when the scoring-block edge is real (mean MAE ratio vs classic `< 1.0 − epsilon` on the held-out block, not just the tuning block). A tuning win that evaporates on the scoring block is reported as a **tie**, not a win.

## Code shape (no implementation here — for the plan)

- `projections/models/reliability.py` — `compute_reliability(prior_snapshots, pa_floor) -> dict[str, float]`, leakage-safe, PA-weighted year-to-year correlation, clamped.
- `MarcelParams` extension — add `gamma: float = 0.0`; rename/alias the scalar to `n_reg_base` (keep `n_reg` working so Rung 1 callers/tests are untouched). `gamma = 0.0` default = classic.
- `marcel_hitter.project_hitter(...)` — accept an optional `reliability` map; when present and `gamma > 0`, compute `n_reg_c` per component; when absent or `gamma == 0`, behave exactly as Rung 1 (the `:39` line generalizes, the default path is byte-for-byte equivalent).
- `build_marcel_projections` — compute the reliability map once per target season (like league means) and thread it through.
- `backtest/tune.py` — search `(n_reg_base, gamma)` by **coordinate descent**, not a dense grid; **no free per-component grid in v1** (too much overfit surface, per the direction decision).

## Non-Goals (explicitly out)

- Statcast / Baseball Savant inputs (Rung 3).
- Game-log / split-half data for true within-season stabilization (future data add).
- Free per-component `n_reg` grid (overfit surface; deliberately excluded).
- Any UI / source-toggle exposure of Marcel (still seam-only).
- Pitching, prospects (separate specs).
- Tuning `k_young / k_old / pa_w*` — Rung 1 evidence says they're calibrated; touching them here just adds overfit risk.

## Success Criteria

1. **Reliability is leakage-safe + sane:** `compute_reliability` uses only seasons `< T`; the resulting ordering passes the literature sanity check (HR/SO/BB rank reliable; AVG-driving/contact stats and R/RBI rank low). Unit-tested on a hand-built two-season example.
2. **Backward compatibility:** with `gamma = 0` (and/or no reliability map), `project_hitter` reproduces Rung 1 output exactly — verified by a test asserting identical stats to the classic path, and the existing 462-test suite stays green.
3. **The verdict (honest either way):** on the held-out 2020–2025 block, a coordinate-descent-tuned `(n_reg_base, gamma)` either
   - **beats classic Marcel** — mean MAE ratio vs classic `< 1.0` across headline stats, correlation improvement on a majority, **and `carryover_confirmed`** (the tuning-block edge replicates on the scoring block); or
   - **ties** (`gamma* ≈ 0` or the edge fails to carry) — reported plainly as "reliability-weighting does not beat classic Marcel; Statcast is the next lever." A tie is a valid, useful result, not a failure to hide.

## Risks & limitations

- **Overfitting `gamma`** — central risk; mitigated by 2-knob-only design, coordinate descent, and the carryover guard.
- **Reliability is an approximation** — season-to-season correlation conflates true-talent reliability with playing-time and aging effects. Acceptable for a *relative* ordering; flagged, not hidden.
- **R/RBI floor** — see above; will stay weak, won't be tuned toward.
- **Sample** — ~330 qualified hitters × consecutive-season pairs; adequate for aggregate `r_c`, thin for tails. `R_FLOOR`/`N_REG_MAX` guard the tail.
- **2020 COVID / 2022 universal-DH discontinuities** — perturb both league means and reliability pairs involving those years; floors + PA-weighting absorb most of it. Worth a note in results if a year-pair looks anomalous.
