# Review of REGISTRATION-DRAFT-mlb-trajectory.md, draft 1

Verdict: CHANGES REQUIRED. Reviewed from source and column names only. No outcome value was read or used.

Corrected 11/2/2026 after the drafter checked this review against source and stopped on three mismatches, all confirmed as the
reviewer's errors: the multiplier's baseline, the age convention's rationale, and reliability rounding. Findings 2 and 8, the
revised design and the integration outline below carry the corrections.

The drafter followed the brief well. Findings 1-3 and 6 are errors in the brief, and the reviewer wrote the brief. The drafter
was right to flag the y-4 lag and the Steamer interface as problems.

## Material findings

### 1. The study answers the wrong question, so a pass would not transfer to production
The candidate predicts H3 from three years of history. The comparators use one year. Any gap could come purely from using more
history, which is what Steamer already does in production. A pass would say "three years beats one year", and nothing about
age curves. The draft correctly found it had no way to combine with Steamer, and this is the cause.

Fix: all three orderings share one year-1 forecast, so the only thing that differs is the multi-year multiplier. That is the
exact component production would swap. See the revised design below. This also moves the study onto the charter's forecast
branch of R-MLB naive, which section 4 already provides for.

### 2. The hand-set comparator is narrower than what is live
`_horizon_profile` (mlb/dynasty.py:248) multiplies by an age ratio AND a reliability haircut: `age_factor * reliability_factor`,
where reliability is `round(100 * volume / (volume + regression), 2)` (mlb/dynasty.py:435, regression 150 hitter, 20 RP, 45 SP),
divided by 100, floored at FUTURE_RELIABILITY_FLOOR 0.55 (mlb/dynasty.py:102) and applied once to future years only
(mlb/dynasty.py:237). The multiplier applies to value above the pool's minimum, not above zero: `baseline + m * (value -
baseline)` (src/league_values/post_processors.py:18), with baseline the minimum total_value in the pool (mlb/dynasty.py:935). The
draft compares against age only. Reconstruct the live formula, including that baseline. Then the comparison is against the real
trajectory component, and the only missing incumbent parts are scaling, role anchor, track-record floors and the 0.05
reliability blend.

### 3. Year weights cannot be learned
The brief said integration replaces "the year weights and age curves". Wrong. 1.0/0.72/0.48 says how much a dynasty manager
cares about 2029 versus 2027. That is a preference, not a fact in the data, and it also defines the target. Weights stay fixed.
Only the age and reliability multiplier is learned. Say so in the claim limits and in open question 3.

### 4. Full-universe Spearman is dominated by fringe players
The population is everyone with any PA or IP. A large share of rows are fringe players whose ordering no dynasty manager cares
about, so a pass could come entirely from there. Keep the charter's full-universe gate and add a second required gate on the
same rule: the top 300 assets by F1 at each origin, pooled across roles, ties broken by lower mlbam_id. Selection uses only
origin-available data and is the same for all three orderings. Both gates must pass.

### 5. As drafted, the study can never run
Several blockers are permanent or already answered:
- **Pitching files exist.** projections/data/pitching/pitching_2010.json to pitching_2025.json carry W, SV, K, ER, IP, H_ALLOWED,
  BB, BF, G and GS, with a manifest. The brief named only historical/. This blocker is the brief's error.
- **Innings are true innings.** projections/data/pitching_historical.py:24 stores `normalize_ip(inningsPitched)`.
- **DOB source exists.** projections/data/identity.json via `age_for` (projections/data/identity.py:13). A missing birth date
  counts against coverage.
- **Absence means no MLB production.** scraper/mlb_actuals.py:261 uses `sportId=1&limit=5000&playerPool=ALL`. Pre-run check,
  counts only: every season file has unique mlbam_ids and fewer than 5,000 rows; otherwise stop.
- **Legal vintage can never be proven** for these modern pulls, so "report ineligible" means the study can never run. Replace
  with a declared departure: official season totals are treated as final as of November 1 of that season, accepting that later
  stat corrections leak in small amounts. The owner accepts this at signature. All historical evidence is already
  development-class, so this does not weaken a claim the study was able to make.
- **Graduate slice:** define it from the files as no PA or IP in any stored season before y-1. Left-censoring at 2010 is
  disclosed. It stays descriptive.
- **Lawful use:** one sign-off line. Research use of public stats already committed to the repo. It is separate from the parked
  /buys image question.

### 6. Training lag
z <= y-4 was the brief's arithmetic error, as the drafter noted. With a November 1 origin, seasons z+1 to z+3 are final when
z <= y-3. Use y-3, drop the departure row, and correct the fold table:
D1 T_2018: 2012-2015. D2 T_2019: 2012-2016. D3 T_2020: 2012-2017. H T_2023: 2012-2020. P T_2026: 2012-2023.

## Accuracy of the record

### 7. Wrong attributions
A registration has to be exact about who decided what.
- "The owner substituted this location" and "the owner's brief" are wrong. The reviewer wrote the brief and chose the location.
  The only owner words are the 11/2 instruction. Call it the reviewer's brief, and remove the location sentence entirely.
- "Surprising to the owner" is unsupported, and the reviewer introduced it. The 11/2 accuracy audit flagged Judge, Betts and
  Raleigh. State only that.
- Add under Prior knowledge: the reviewer loaded hitting_2025.json, pitching_2025.json and data/mlb/mlb_history_*_seasons.json
  in-process to print column names, row counts and season ranges. No stat values were displayed. The 11/2 accuracy audit
  displayed a few 2026 stat lines for named players, including Judge's, and those lines reached the reviewer.

## Smaller
### 8. One age convention
Use age on April 1 (`age_for`) everywhere, including the 33+ slice. Marcel uses it (projections/export/marcel_run.py:73), and so
does production's preseason path after PR #71 (`_player_age` in D:/CodexWorktrees/valucast-rollover-20261102/mlb/dynasty.py), which
is the path a learned multiplier would ship on. In-season production prefers the feed's metadata age first (mlb/dynasty.py:298).
No historical feed was archived, so that path cannot be reconstructed. Disclose the gap, and declare April 1 as a departure from
the charter's July 1.

### 9. Disclose the F1 ancestry
Marcel defaults are the published classic values for hitters. The pitcher default `era_from_fip=True` was selected on a held-out
test on 6/23/2026 (projections/models/pitcher_params.py:13), so its ancestry saw these seasons. All three orderings share F1, so
this cannot by itself create a gap between them. Disclose it. Pin defaults; never read tuned parameters or tune.py output.

### 10. Say the likely outcome plainly
With a shared F1, gaps come only from multipliers, so they may be small and the 0.02 bar may be hard to clear. Do not lower it.
Add to claim limits: a fail is a legitimate result and the hand-set curves stay. No retune. The prospective freeze can still run
as shadow.

## Revised design (replaces "Exactly one candidate" and "Comparators")

For asset i at origin y, routed role r, using only data before T_y:
- `F1`: asset's U for season y+1 from the Marcel forecast, built by `build_marcel_projections` and `build_pitcher_projections`
  with default parameters and target season y+1, in origin-y reference units. Both components summed once.
- `a`: clamp(age_for(dob, y+1), 22, 37) - 29. The clamp range matches the source curve; 29 is PEAK_AGE.
- `rho`: max(0.55, min(1, round(100 * V / (V + reg), 2) / 100)), and 0.55 when V <= 0. V is Marcel's projected PA for a routed
  hitter or IP for a routed pitcher; reg is 150 hitter, 20 RP, 45 SP.
- `B`: the minimum F1 over the frozen origin-y universe, all roles pooled, mirroring `horizon_baseline` (mlb/dynasty.py:935).

All orderings are `H3_hat = B + (F1 - B) * m`, using the routed role's multiplier for the whole asset:
- **Flat:** `m = 1`, so the ordering is F1.
- **Hand-set:** `m = (1 + 0.72 * c(age+1)/c(age) * rho + 0.48 * c(age+2)/c(age) * rho) / 2.20`, with c from the source curves and
  interpolation in `_age_multiplier`, age unclamped since the source clamps.
- **Candidate, exactly one:** `m = max(0, b0 + b1*a + b2*a^2 + b3*rho)`.

Fit per role with closed-form ridge, with each training origin z using its own B_z. Target realized H3 - B. Features (F1-B),
(F1-B)*a, (F1-B)*a^2, (F1-B)*rho. No intercept and no centering, so the prediction stays proportional to value above baseline.
Divide each feature by its training-fold population SD. Lambda 10.0. Zero searches. That is 4 coefficients per role, 12 in total.
Keep the draft's penalty convention, blocked-fit rules and solve. F1 - B is never negative, so a multiplier cannot reverse a sign.

Disclose the transfer assumptions, which only prospective scoring can test: Marcel versus Steamer as the year-1 forecast; B from
the origin universe versus the live Steamer pool; reference category SDs versus the live league's (centering constants cancel in
F1 - B); and SP/RP routing by GS/G versus position eligibility in production.

Remove the seven-predictor model, its feature list and the observed carry-forward comparator. U history is no longer a feature.

## Integration outline (replaces the blocker in open question 3)
A separate PR replaces the weighted age and reliability sum in `_horizon_profile` with `value = _apply_multiplier(total_value,
m(a, rho), baseline)`, where m is the learned multiplier. Steamer stays year 1, year weights stay in the evaluation target, and
scaling, anchors and floors are untouched. Coefficients ship as constants with a model epoch note and an owner-reviewed board
diff. The transfer assumptions above apply.

## Keep unchanged
Target, November origin, population, role routing, reference constants, folds other than the training lists, charter section 6
thresholds, bootstrap, seed and its check, exposure labels, prospective freeze, mechanical dispositions (FAIL if either gate
fails), execution protocol, and the recommendations on open questions 1 and 2.
