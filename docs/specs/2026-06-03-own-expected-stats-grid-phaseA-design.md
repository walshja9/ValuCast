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
- **Missing-EV balls** (bunts / untracked contact) are **excluded from grid-FIT** (no EV/LA to bin). At SCORING time they are **not** dropped — see the denominator rule below — they're imputed at the grid's global fallback rate so a full-AB denominator isn't silently understated.
- Fitted grid stored as an immutable JSON artifact (cell → `{n, p_hit, e_bases}`), same immutability contract as the other backbones.

## Scoring (our xBA / xSLG)

For each player-season: `our_xBA = Σ grid.p_hit(ball) / AB`, `our_xSLG = Σ grid.e_bases(ball) / AB`, summed over the player's batted balls, with **`AB` joined from the hitting backbone**.

**Denominator rule (explicit — full AB, to match Savant):** the denominator is the **full official AB** from the backbone. This matches Savant's xBA (which divides by AB). Consequences, pinned:
- **Strikeouts and BIP outs stay in AB and correctly contribute 0** hit-prob — a strikeout *should* lower xBA. Not excluded.
- **Missing-EV BIP are imputed** at the grid's **global fallback rate** (league-average `p_hit`/`e_bases`), *not* scored 0 and *not* dropped from the denominator — otherwise the full-AB denominator would silently understate our xBA for players with more untracked contact.
- **`missing_ev_coverage`** (share of a player's BIP lacking EV/LA) is computed and reported as a diagnostic, so any residual denominator drift is visible, not hidden.

(Rationale: full AB is the closest match to Savant; an adjusted "AB minus missing-EV" denominator would diverge from Savant's definition and inject denominator drift into the comparison.)

**Self-fit inflation is negligible** — one player is ~0.1% of the ~375k league balls, so their own balls barely move their cells' rates. (If we want zero doubt, fit the grid on 2021–22 and score 2023 — still cheap. Offered as an option; default is pooled-window fit.)

## The faithfulness gate (success bar — corr-led, MAE characterized)

We already have **Savant's `xBA`/`xSLG` on disk** (Rung 3 snapshots), so the comparison needs no extra pull.

**Qualified comparison population (no tiny-sample correlations):** player-seasons with **AB ≥ 200 AND tracked BIP ≥ 50**, joined to the Savant snapshots. Tiny-sample players are excluded from the gate (they'd inflate or distort correlation).

- **PRIMARY (pass/fail): `correlation(our_xBA, Savant_xBA) ≥ 0.95`** across the qualified population, same for xSLG. The bar for "we track it."
- **CALIBRATION (required diagnostics — correlation alone is insufficient):** a biased affine transform can have corr≈1 yet be unusable as a *replacement* input. So we also compute and report, for our_xBA vs Savant_xBA and our_xSLG vs Savant_xSLG:
  - **mean signed error** (bias) and **MAE**,
  - the **linear calibration slope + intercept** (our value regressed on Savant's).
  **Phase B rule:** before our values replace Savant's in the de-noise, Phase B must either show **acceptable calibration** (slope ≈ 1, intercept ≈ 0, small bias) **or store and apply a simple affine calibration layer** (`a·our + b`) fit leakage-safe. Phase A's job is to *measure and report* these; Phase B enforces them.
- **SECONDARY (characterized, NOT hard-fail): the residual is expected** — **Savant's xBA also uses sprint speed** ([MLB xBA glossary](https://www.mlb.com/glossary/statcast/expected-batting-average)) on certain weakly-hit balls, which EV+LA alone omits. Fast/slow players will be off in a *known direction*; that residual is the **signpost to the next input**, not a failure. Report MAE split by player speed tendency where possible.

If correlation clears 0.95 **and** calibration is clean (or a calibration layer is defined), we've genuinely reproduced xBA from our own calculation.

## Non-Goals

- The full 2015–25 batted-ball pull and re-running the Rung 3 de-noise with our numbers — **Phase B**, gated on this.
- A learned model (logistic/GBM) — stdlib-only repo; the empirical grid *is* how xBA is defined.
- Leakage-safe grid fitting — Phase A is a **descriptive** faithfulness check (reproduce a contemporaneous metric), not prediction. Leakage-safe fitting is Phase B's concern (when the grid feeds the predictive de-noise).
- Sprint-speed input — the named next lever, not this rung.
- Wiring into the app or the de-noise — behavior-neutral; this rung only produces + validates the artifact.

## Components

- `projections/data/batted_balls.py` — resumable/throttled chunked pull + CSV parse → `(ev, la, events, batter, season)` rows for a window.
- `projections/models/expected_stats_grid.py` — `fit_grid(balls)`, sparse-cell fallback, `p_hit`/`e_bases` lookup, per-player scoring → our xBA/xSLG given AB; store/load the grid artifact.
- `projections/backtest/grid_faithfulness.py` — over the qualified population (AB ≥ 200, tracked BIP ≥ 50), compute our xBA/xSLG, join Savant's stored values, report **corr (gate) + calibration (mean signed error, MAE, slope/intercept) + missing-EV coverage**, MAE optionally split by player speed tendency.

## Success Criteria

1. **Pull:** resumable, throttled, retrying batted-ball pull for 2021–2023; a re-run skips already-fetched chunks; partial failure doesn't corrupt state.
2. **Grid:** fitted EV×LA grid with sparse-cell fallback, stored immutably; sanity unit test — a 100 mph / 12° cell has high `p_hit`, a 65 mph / −30° (weak grounder) low.
3. **Scoring:** our xBA/xSLG per player-season; the sum/AB math unit-tested on a tiny hand-built grid.
4. **Gate (the verdict):** over the qualified population (AB ≥ 200, tracked BIP ≥ 50), `corr ≥ 0.95` for both xBA and xSLG (primary pass/fail); **calibration reported** — mean signed error, MAE, slope/intercept — with a clean-calibration-or-calibration-layer requirement carried to Phase B; MAE characterized against the sprint-speed expectation. Honest WIN (reproduced + calibrated) / SHORTFALL (diagnose) either way.
5. **No regressions:** additive; existing suite stays green.

## Risks & limitations

- **EV+LA omits sprint speed** — the known faithfulness ceiling; expected residual, quantified not hidden, and the pointer to the next input.
- **Pull fragility** — Savant rate-limits/changes params; mitigated by resumable chunks + throttle + retry, and Phase A's small window.
- **Definition drift vs Savant** (AB denominator, excluded balls) — kept tolerable by the correlation-led gate; missing-EV handling pinned.
- **Could fall short of 0.95** — then it's a finding: EV+LA alone isn't enough to call it faithful, and sprint speed (or more) is required before claiming "our xBA." Reported plainly; no fudging the bar.
