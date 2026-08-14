# Program: Pitcher-Pass (owner-approved A+B, 2026-08-14)

**Directive (owner, 2026-08-14): "Pitchers have to pass."** Goal: a
materially changed pitcher model that beats the 25-historical-neighbors
baseline on all three ordering metrics under a brand-new registration —
the only path back from the REJECTED verdict, as the registry entry
requires. **Scope approved: Phase A + Phase B.**

**Standing constraints:** scoring freeze intact; all work is shadow /
research-only; the five closed cohorts (2016–2019, 2021) are DEVELOPMENT
data (unlimited looks, no claims); the confirmatory claim comes only from
the Phase C registration whose pooled evidence includes the pristine 2022
cohort (~Oct 2026 maturation, never touched by any look). Plan 031's held
look (seed 31013) is never spent; its re-arm condition names the same
2022-maturation window — Phase C and the 031 successor registration are
the same batch.

## Diagnostic record (committed evidence, pre-development)

1. Ordering-specific failure: model beats neighbors on MAE (0.1333 vs
   0.1487) and wins the 200 largest disagreements 134–66, yet ties on
   rank metrics.
2. The 390-row zero-tie block (21% of the pool; arrival-ridge clamp at
   0.0) contains 23 contributors and a 3.5x within-block gradient that
   neighbors capture.
3. Feature ceiling: 35 features vs the baseline's 8 and still an ordering
   tie — the box-score line alone is exhausted.

## Dev log (development cohorts; point estimates; NOT claims)

**2026-08-14 — de-clamp refuted.** Killing the tie block directly makes
ordering WORSE (unclamped product Δ-Spearman −0.016 vs neighbors; sigmoid
−0.013; arrival-only −0.019, against the served model's −0.008): the
ridge's linear ordering inside the low tail is noisier than a tie. The
tie was protective. Conclusion: the deficit is local structure the linear
form cannot express, not the clamp per se.

**2026-08-14 — ensemble carries the signal.** A 50/50 score blend of the
served hurdle with the neighbors score beats neighbors on ALL THREE
ordering metrics on the dev pool (Δ +0.0221 Spearman / +0.0093 Kendall /
+0.0178 AUC) while also beating the neighbors MAE (0.1403 vs 0.1487).
Complementary errors; alpha=0.5 was best of {0.3, 0.5, 0.7}; rank-blends
are worse; epsilon tie-breaking by neighbors fails.

**2026-08-14 — strike% (Phase B signal #1).** `pitches`/`strikes` cover
100% of pitcher rows in every cohort INCLUDING the 2022 holdout (raw
dataset join; the input contract does not carry them). Adding Plan 031's
reviewed `strike_pct_extra` features to the hurdle improves the model
itself (MAE 0.1333→0.1317; ordering deficit roughly halves) and lifts the
blend to Δ +0.0225 / +0.0097 / +0.0180. Consistent with 031's dry-run
finding that strike% carries real signal.

**Current dev standing vs the eventual gate:** with registered-run CI
half-widths (~±0.027 Kendall), Spearman and AUC margins would likely
clear; Kendall (+0.010) would not. More headroom required — candidates:
learned stacking (fold-safe out-of-fold neighbor feature), tuned blend
weights per arrival band, additional historically-covered signals
(BF/IP already in; HR-suppression shape; multi-line within-cohort usage),
k-NN metric learning. AAA Statcast is UNAVAILABLE historically (archive
starts 2026-07-14) — excluded from Phase B; Fangraphs boards/FV are
third-party opinion — forbidden in the factual model.

## Phases

- **A — architecture (no new data):** ensemble/local-structure challenger
  (blend or stack of hurdle + neighbors). Fold hygiene note for stacking:
  training-row neighbor features must be leave-one-out or nested-fold to
  avoid self-match leakage.
- **B — new signal, historically covered:** strike% first (done, small
  positive); further candidates above. Every feature must exist for
  2014–2022 cohorts or it cannot support the Phase C claim.
- **C — new registration (~Oct 2026):** challenger frozen before the 2022
  cohort matures; one look on the pooled evidence including pristine
  2022, with a 2022-fold-positive side condition (joining the Plan 031 /
  C1 / E1 new-vintage batch); fresh seed (37083 remains reserved from the
  maturation registration's now-moot rule 4 — Phase C draws its own).

## Boundaries

No served score, rank, value, buy, publication, or workflow change. The
challenger ships nothing without a registered PASS and explicit owner
authorization. Dev numbers in this document are development-only and must
never be quoted as claims, publicly or in the registry.
