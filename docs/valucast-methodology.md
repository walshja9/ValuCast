# ValuCast Projection Methodology (Internal)

> As of June 2026 · ValuCast H+P v1. Canonical engineering reference. The public
> `/methodology` page is distilled from this; keep this the source of truth.

## The rung program

We built ValuCast's projections as a ladder of rungs, each gated by held-out validation.

### Hitting
1. **Marcel foundation** — recent seasons weighted 5/4/3, regressed toward league mean
   (`n_reg`), age-adjusted, per-PA rate components reconstructed. WIN vs. persistence /
   league-avg baselines (rate-stat MAE ratio ~0.979).
2. **Reliability weighting (Rung 2)** — stabilization-anchored year-to-year reliability.
   TIE — did not clear the carryover guard, not shipped as a win.
3. **Statcast input de-noising (Rung 3)** — blend actual contact/power toward Savant
   xBA/xSLG with mix-preserving redistribution into 1B/2B/3B/HR (knobs
   `alpha_contact`/`alpha_power`; `gamma=0` nests classic). WIN — shipped.
4. **Barrel→HR (Rung 4)** — gated non-build (did not beat baseline).

### Pitching
- **Role-routed Marcel**, per-batter-faced, with a **continuous SP-probability** blend
  (`p_sp`) instead of a starter/reliever cliff; leakage-safe role-shift
  `f[c]^(h_sp − p_sp)` (no double-apply); separate SP/RP usage models. WIN — skill MAE
  ratio ~0.821. Fully in-house (no borrowed projection inputs).

## Validation discipline
- **Immutable historical backbone** (content-compared, Windows-newline-safe).
- **Leakage-safe rolling-origin backtest** — project forward, never peek.
- **Beat-the-baseline gates** — persistence → league-average → classic Marcel.
- **Carryover guard** — a tuning-block win must replicate on a disjoint scoring block.
- Go/no-go gating killed Rung 4 and the own-xBA Phase A.

## Honesty rules (ours vs. external)
- **Pitching:** the projection **model** is built and validated by ValuCast using public
  MLB historical data — it does **not** consume Steamer or any third-party pitcher
  projection. ("ValuCast-built model," not "proprietary data.")
- **Hitting:** our projection model, consuming **Savant xBA/xSLG** as inputs.
- **Own-xBA grid (Phase A): SHORTFALL.** Our EV×LA empirical grid reached corr 0.87 but
  did not beat Savant (sprint-speed component needed). Savant remains the better input;
  we kept the finding and did not ship our own xBA.
- **Steamer:** external comparison board and the default source; a fair historical
  benchmark against archived preseason Steamer remains pending.

## Prospect Rank v1

Prospect Rank v1 is ValuCast's own prospect ordering. It combines ValuCast-owned
factual signals into one baseball-first rank:

- current MiLB performance and sample reliability
- age/level context
- factual draft/signing investment
- factual availability and sample-risk context
- the shadow Prospect Model v0.6 and universal outcome context

DD ranks, DD values, DD value history, public prospect rankings, market signals,
and DD adapter ranks or scores are display/comparison context only. They can be
shown beside a player to explain disagreement, but they cannot affect the
ValuCast prospect score.

Bucket calibration is applied by rule, not by name. Current rules cover
lower-minors pedigree compression, thin upper-level pitcher samples, and
upper-level hitters with full current samples but limited game impact.

## Verdict ledger
| Rung | Result |
|---|---|
| Hitting foundation | WIN — rate-stat MAE ratio ~0.979 |
| Reliability (Rung 2) | TIE — failed carryover guard |
| Statcast de-noise (Rung 3) | WIN — shipped |
| Barrel→HR (Rung 4) | NO — gated out |
| Pitching foundation | WIN — skill MAE ratio ~0.821 |
| Own-xBA grid (Phase A) | SHORTFALL — corr 0.87, did not beat Savant |

## The workflow
Brainstorm → spec → plan → execute → held-out verdict, recorded honestly either way.
