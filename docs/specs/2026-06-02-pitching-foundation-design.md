# Pitching Foundation — Role-Routed Marcel (per-Batter-Faced) — Design

**Date:** 2026-06-02
**Status:** Draft / pending review (amendments incorporated 2026-06-02; awaiting sign-off)
**Builds on:** the hitting program scaffolding (historical backbone pattern, leakage-safe rolling-origin harness, `MarcelParams`, run archive, `ProjectionCatalog`). This is the **pitching analog of hitting Rung 1** — the foundation rung. Statcast-pitcher inputs are a later rung.

## Goal

Stand up ValuCast's own pitching projections: a historical pitcher backbone + a **role-routed Marcel** model (separate SP/RP usage, blended for mixed-role arms) projecting per-batter-faced skill rates and role-appropriate volume, reconstructed into the engine's pitching categories — validated on the harness against classic baselines. First in-house pitching leg toward a complete H+P ValuCast board.

## Why role-routed + per-BF (locked in brainstorming)

- **Per-BF rates** (not per-IP): BF is the pitcher's analog of PA — the correct, less-endogenous denominator (a pitcher who allows more baserunners faces more batters; per-IP hides that). Mirrors the per-PA call that worked for hitting. **`battersFaced` verified present and populated in the MLB Stats API** (probed 2026-06-02), so per-BF is locked; no fallback needed.
- **Role-routed, not pooled**: SP and RP differ in usage (GS/QS vs appearances/SV/HLD) and rate context. We project role and route accordingly.
- **Graceful middle state (the key refinement)**: role is NOT a hard binary. We project a continuous **SP probability `p_SP`** from recent games-started share and **blend** the SP-line and RP-line by it. Clear starters (`p_SP≈1`) and clear relievers (`p_SP≈0`) route cleanly; swingmen, openers, bulk relievers, failed starters, and conversion arms get a smooth blended projection plus a `mixed_role` flag — no cliff.

## 1. Historical pitcher backbone (`projections/data/pitching_historical.py`)

Mirror the hitting backbone: immutable per-season snapshots `projections/data/pitching/pitching_<season>.json`, 2010–2025, keyed by `mlbam_id`, manifest with content hash, re-pull no-op, content-change raises. Reuses `scraper.mlb_actuals` (`fetch_actuals` already returns pitchers; `normalize_pitcher` already computes most of this — extend it to carry `battersFaced`, `gamesFinished`, `hitByPitch`, `intentionalWalks`).

**Stored counting row (per pitcher-season):**
```
mlbam_id, season, BF, IP (true decimal), ER, H_ALLOWED, BB, HBP, K, HR,
W, L, SV, HLD, GS, G, GF, QS
```
- **IP** stored as true decimal (via existing `normalize_ip`, e.g. 4.2→4.667), not baseball notation.
- **QS** is the one expensive field — the season endpoint has no `qualityStarts`, so it's derived from game logs (existing `derive_qs_from_games`). To bound the pull, derive QS **only for pitchers with GS>0**; relievers get QS=0. Flag this as the costly step of the one-time pull.

## 2. Role classification + SP-probability (`projections/models/pitcher_role.py`)

- **Per-season role share** = `GS / G` (0 = pure relief, 1 = pure starter).
- **Projected `p_SP`** = weighted (5/4/3) recent role-share, leakage-safe (prior seasons only). Continuous in [0,1].
- **`mixed_role` flag** when `0.2 < p_SP < 0.8` (transparency for swingmen/openers/converts).

## 3. Role-routed Marcel projector (`projections/models/marcel_pitcher.py`)

**Shared per-BF skill core** (rates more portable across roles than usage is):
- Project per-BF rates for `K, BB, H_ALLOWED, HR, ER, HBP` via the Marcel mechanics (weighted 5/4/3, regressed toward league means by `n_reg`). Uses a **pitcher-specific params object** `PitcherMarcelParams` (§ below) — **not** hitter `MarcelParams`.
- **Role-context rate adjustment (explicit, leakage-safe, no double-apply):** relievers post better short-burst rates than the same arm starting. From **pre-target seasons only**, compute per-role league rates for each skill component `c` and the role factor `f[c] = league_RP_rate[c] / league_SP_rate[c]` (`>1` for K, `<1` for ER, etc.). Model a rate at role-mix `x` (fraction of BF as a starter) as `base_SP · f^(1−x)`. A pitcher's pooled observed rate `r_obs` already reflects their **historical** role mix `h_SP` (their GS-share-weighted role context). Re-express at the **projected** role `p_SP`:
  ```
  projected_rate[c] = pooled_rate[c] · f[c] ^ (h_SP − p_SP)
  ```
  When `h_SP == p_SP` (role unchanged) the exponent is 0 → **no adjustment**, so a career reliever projected as a reliever gets **no** double-applied boost; only a *change* in role (e.g. RP→SP, `h_SP=0, p_SP=1` → divide by `f`, removing the reliever boost) shifts the rate. This makes the SP/RP split matter at the rate level without per-pitcher per-role histories.

**Pitcher params (`PitcherMarcelParams`, do NOT reuse hitter `MarcelParams`):**
- Reuses `season_weights = (5,4,3)` and an `n_reg` default, but carries **no** hitter age multipliers and **no** `alpha_*`/`gamma` fields (those are hitter-modeling concerns and must not leak in).
- **Age: neutral in v1** — pitcher skill age adjustment = 1.0 (no curve), explicitly flagged for later pitcher-specific tuning. Pitchers age differently than hitters; rather than reuse an untested hitter curve, v1 applies no age effect and a later rung fits/validates a signed pitcher age curve. (If a v1 age effect is ever added, it must be pitcher-specific and unit-tested for sign.)

**Separate usage/volume models (the split):**
- **SP usage:** project `GS`, `IP/start` (→ IP), `BF/start` (→ BF); `QS-rate-per-GS` → QS.
- **RP usage:** project `G` (appearances), `IP/appearance` (→ IP), `BF/appearance` (→ BF); `SV-rate` and `HLD-rate` (per appearance, with `GF`-share as the closer signal) → SV, HLD.

**Blend by `p_SP`:** project a full SP-line and a full RP-line for the pitcher, then `stat = p_SP·SP_stat + (1−p_SP)·RP_stat` for every output. Pure roles collapse to one line; mixed arms get the smooth blend.

## 4. Reconstruction to engine categories

From projected BF + per-BF rates + usage, reconstruct what `category_registry` consumes:
- **Skill/rate:** `IP, K, BB, H_ALLOWED, ER, HR` → `ERA = 9·ER/IP`, `WHIP = (BB+H_ALLOWED)/IP`, `K_9`, `BB_9`, `K_BB`.
- **Counting/role (flagged noisy):** `W` (from prior W-rate per IP — team-context-bound), `SV`/`HLD` (RP usage rates), `QS` (SP `GS × QS-rate`), `SV_HLD`.
- Guards: clamp all counts ≥0; IP>0 before any ratio; **`BF ≥ 3·IP`** within rounding tolerance (every batter faced is an out or a baserunner; IP is outs/3, so BF must be ≥ outs_recorded = 3·IP — `BF ≥ IP` is far too weak).

**Mixed-role export — primary-pool approximation (Option A, explicit):**
- For **backtesting/modeling**, the single blended full-season line is used directly.
- For **engine export**, emit **one row** with `pool = starter if p_SP ≥ 0.5 else reliever`, positions reflecting eligibility, and metadata carrying `p_SP` and `mixed_role`. This is a **primary-pool approximation**: a mixed arm is valued entirely within its dominant pool, not split fractionally. We do **not** claim the blended line is fully coherent across SP and RP valuation — it isn't, because the engine has no fractional pool membership.
- **Dual-row export** (Option B: separate SP and RP valuation rows sharing `base_id` with `p_SP`/`(1−p_SP)`-weighted contributions) is the more faithful treatment for mixed arms and is noted as a **future option**, explicitly out of scope for v1.

## 5. Harness (extend, don't fork)

The scorecard metrics (MAE/RMSE/correlation, normalized ratio) are pool-agnostic and reused as-is. The backtest needs a **pitcher variant**: pitcher eval population gated on a **min-IP floor** (e.g. SP ≥ 60 IP, RP ≥ 20 IP) instead of PA, and pitcher headline categories.

**Baselines, in order:**
1. **Persistence** (season T-1 = T) — the first bar.
2. **League-average.**
3. **Classic pooled pitcher Marcel** (no role split) — the "does the split help?" baseline.
4. **Role-routed split Marcel** (this model).

**Headline categories scored:** `IP, K, ERA, WHIP, K_9, BB_9` (skill) + `W, SV, QS, HLD` (usage/context, reported but **expected noisy**).

## 6. Honesty: skill vs context

`ERA, WHIP, K, K_9, BB_9` are the **skill bar** — where player history can beat persistence. `W, SV, QS, HLD` are **usage/team-context categories**: even with usage modeling, a player-history model can project a closer's *opportunity* from save history but cannot know the team's 9th-inning decision. These are projected so the engine has a full line, **reported but not tuned toward**, and never claimed as a strength. (The pitcher analog of R/RBI for hitters — but more context-bound.)

## Success criteria

1. **Backbone:** immutable pitcher snapshots 2010–2025 (incl. BF), manifested; re-pull no-op; QS derived for GS>0.
2. **Role:** `p_SP` is continuous, leakage-safe, and blends (verified on a swingman hand-case: a 50/50 GS-share arm gets a ~midway SP/RP blend, not a coin-flip cliff).
3. **Reconstruction correctness:** unit-tested rate→category math (ERA/WHIP/K_9 from components); clamps and `BF≥IP` guard hold.
4. **The verdict (honest either way):** rolling-origin, tuning block disjoint from scoring block. Role-routed Marcel **beats persistence** on the skill categories (mean MAE ratio < 1.0 + correlation majority, carryover-confirmed). Secondary: does the role split **beat classic pooled pitcher Marcel**? Report W/SV/QS separately as context cats. A tie on the split (routing doesn't beat pooled) is a valid recorded result.
5. **No regressions:** hitting projections and the full existing suite stay green; pitching is additive.

## Non-Goals

- Statcast / pitch-level inputs (xERA, xwOBA-against, barrel%-against, Stuff+) — the next pitching rung.
- Hard SP/RP cliffs — explicitly avoided via `p_SP` blending.
- Injury / IL modeling for volume (IP projection uses usage history only; injuries are noise we don't predict).
- App integration / shipping (that's the deferred complete-H+P ship spec, revisited after this).
- Prospect pitchers (no MLB history → not projectable here).
- Per-pitcher Statcast or pitch-mix; tuning pitcher-specific age/`n_reg` constants beyond a first pass.

## Risks & limitations

- **Usage volatility is the ceiling.** IP, role, and especially SV/QS swing on team decisions and health. The skill rates (K/BB/HR per BF) are where we expect to win; volume/role cats will be the weak spots, by nature.
- **Role-context rate adjustment** (SP↔RP) is a league-average shift, not per-pitcher; conversion arms are inherently uncertain — the `mixed_role` flag surfaces them.
- **QS pull cost** (per-starter game logs) is the expensive one-time step; bounded to GS>0 pitchers.
- **Pitcher aging** differs from hitting; v1 reuses the mechanic with first-pass constants and flags it for later tuning — not a foundation blocker.
- **It may tie on the split.** Beating persistence is the real foundation bar; "split beats pooled Marcel" is a bonus the harness will rule on honestly.
