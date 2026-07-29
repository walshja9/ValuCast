# Registered Challengers: Development Density and Position×Youth

**Registered:** 2026-07-29 (committed before any confirmatory result exists).
**Commissioned by:** owner disposition item 5 on
`docs/review-2026-07-29-sirota-disagreement-adversarial-review.md`.
**Status:** registration only. No model change, no artifact change, no
publication effect. The frozen model and `MIN_GATE_IMPROVEMENT_PCT = 2.0`
gate are untouched; a challenger that eventually passes still requires its
own design doc, review, and a disclosed re-baseline per standing protocol.

## Prior knowledge (disclosed)

The 2026-07-29 feature-evaluation lane ran an EXPLORATORY sweep of 10
variants over the existing walk-forward folds (test cohorts 2016–2019) and
observed: development-density proxies (`pa_per_game`, `games_played/132`
hitters; `ip_per_game` pitchers) lifted the hitter gate margin +2.1589% →
+3.0214% (pooled +6.36% → +6.66%); `pos_value × youth × level` lifted the
hitter gate to +2.5300%. These are best-of-10 selections on the same four
folds — the selection effect is real and is exactly what this registration
controls. The same sweep's negative results (athleticism proxies inert,
contact-quality proxies inert, richer pedigree harmful, `years_since_draft`
harmful) are recorded in the review doc and those axes are NOT registered.

## Frozen challenger definitions (no further variant search permitted)

Exact computations, reproduced verbatim from the exploratory runner and
frozen here so no implementation choice remains open after results are
seen. Inputs are the committed historical-row fields of
`data/prospects/prospect_model_inputs.json`; `_num(x)` means float(x) if
finite else None; every missing-value rule below is part of the frozen
definition. Features are appended to the model's rich vector (baselines
untouched), in exactly the listed order.

- **C1 — development_density** (append after the current last feature):
  - hitters, two features:
    `pa_per_game = plate_appearances / games_played` if
    `games_played > 0` else `0.0`, with `plate_appearances`/`games_played`
    read as `_num(...) or 0.0`; and
    `season_share = min(1.0, games_played / 132.0)`.
  - pitchers, one feature:
    `ip_per_game = innings_pitched / games_played` if `games_played > 0`
    else `0.0`, same missing rule.
- **C2 — position_value_x** (hitters only; three features):
  - Position-value table (single committed `position` string, uppercased;
    the committed field carries exactly one primary position — there is no
    multi-position input; any value not in the table, and missing/empty,
    maps to `0.5`):
    `C 1.0, SS 0.95, CF 0.80, 2B 0.65, 3B 0.55, RF 0.40, LF 0.30, 1B 0.15,
    DH 0.0`.
  - `p = table[position]`;
    `level = LEVEL_CODE.get(level_string_upper, 0.0)` (the model's own
    committed level coding);
    `age = _num(age) or 0.0`;
    `youth = EXPECTED_AGE.get(level_string_upper, age) - age` (the model's
    own committed expected-age table; unknown level therefore gives
    `youth = 0.0`).
  - Emit `[p, p * youth, p * level]` in that order.

Any deviation from these definitions — table values, missing rules,
ordering, or interaction forms — voids this registration and requires
re-registration.

## Confirmation protocol and multiplicity controls

Because the exploratory sweep consumed the existing folds, confirmation on
the same folds cannot be independent. Both controls below apply:

1. **Selection-controlled re-test (same data, m=2):** the two frozen
   challengers re-run on the existing harness (`prospects/model.py`
   `train_role`/`_walk_forward`, kNN baselines untouched). Pass requires,
   per challenger, ALL of: (a) pooled improvement over the binding baseline
   ≥ current candidate's margin + **0.25 percentage points** (i.e. ≥
   +6.61%); (b) hitter role gate ≥ **2.50%** (the 2.0% bar plus a 0.5-pt
   selection margin); (c) pitcher role gate not degraded below its current
   +9.70% by more than 0.25 pts; (d) no OOS fold-year where the challenger
   is worse than the current candidate by more than 1% relative. These
   thresholds are fixed now, before the confirmatory run.
2. **Fresh-cohort confirmation (the real test):** when the 2020–2021 cohorts
   mature into the outcome window (per `MATURE_THROUGH` policy), the frozen
   challengers must ALSO clear the plain 2% gate on folds that include the
   new cohort years — data no variant search ever touched. A challenger may
   ship only after BOTH controls pass, or after control 2 alone passes with
   control 1 waived in writing by the owner.

Leakage guards carried from the exploratory lane: same-season density only
(no career aggregates computed at collection time); if the IL-transaction
historical collection (StatsAPI, verified to 2014) is ever built to replace
the density proxies, IL features must be date-filtered to each cohort
season's end, and that substitution is a NEW challenger requiring
re-registration.

## Explicitly not registered

Athleticism, contact quality, organizational investment (owner item 7 —
no historical coverage or no measured lift), cross-role normalization
(owner item 6 — existing research track, underpowered study not reopened),
and any Sirota-specific adjustment (owner item 4).
