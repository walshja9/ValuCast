# R&D Brief: A better prospect *outcome* model (beat the kNN wall)

**Audience:** Codex (or any engineer picking this up).
**Status:** candidate implemented on `codex/prospect-outcome-knn-rd`. Data
artifacts are intentionally NOT regenerated here -- regenerate them only after
review/sign-off (see Evaluation harness).

---

## 1. TL;DR

The prospect board's front-office grade is **hard-capped at B+ (87)** unless the
**outcome** model's promotion gate (`model_board_gate`) goes `active`. That gate
only goes active if the model beats its **best baseline out-of-sample by ≥2%**.
The best baseline is a **k-nearest-neighbors (kNN)** predictor, and today the
ridge model **loses** to it. Worse: ensembling (ridge + prior + kNN) cannot beat
kNN either, because kNN is already the best component.

**Your mission:** build an outcome predictor that genuinely beats the pooled kNN
baseline out-of-sample by ≥2% on the existing walk-forward CV. That is the *only*
way to lift the B+ cap. This is real modeling work, not plumbing.

This is explicitly **not** achievable by:
- blending/ensembling the current ridge, prior, and kNN (proven below), or
- removing baselines from the gate (that would be dishonest — don't).

---

## 2. Why this matters (context)

We want lower-minors (Single-A / High-A) prospects scored on their **current
stats**, not pedigree. Foundation already done on this branch: `LEVEL_CODE` and
`EXPECTED_AGE` in `prospects/model.py` were extended to include `A` and `A+`
(ordering-preserving codes; on-track ages). That makes ~1,781 lower-minors
players eligible for stat-based scoring.

But on its own that change **regresses** the validated grade from **B+ (87) →
C+ (76)**, because:
- the **impact** gate drops from `active` → `fallback` (it beats its best
  baseline by only ~1.4%, under the 2% bar), costing 15 points, and
- the **outcome** gate stays `fallback` (model loses to kNN), keeping the 87 cap.

A separate, already-shipped fix (`_confidence` now tracks the real current
sample instead of the score source, commit `e18755f` on `master`) resolved the
immediate production symptom (stale board). This brief is about *quality*: making
lower-minors stat-scoring a net **improvement**, not a regression.

---

## 3. The grade rubric and the B+ cap (read this carefully)

File: `prospects/outcome_backtest.py`.

Grade bands (`_GRADE_BANDS`, ~line 189):
```
A=93, A-=90, B+=87, B=83, B-=80, C+=75, C=70
```

Raw score (~lines 228-237):
```
+25  dynasty_gate == active
+20  adapter_gate == active
+15  model_impact_gate == active
+10  model_board_gate == active   (else +4 if fallback, else 0)
+10  realized_samples >= MIN_REALIZED_OUTCOME_SAMPLE
+10  v07 ready_for_backtest
+5   forward_status == review_ready  (else +2 if collecting)
+5   no v07 blockers
```

**The cap (~lines 264-274):**
```python
score_cap = 100
if model_board_gate != "active":
    score_cap = min(score_cap, 87 if bucket_cohort_ready else 84)
...
score = min(raw_score, score_cap)
```

So: **without an active outcome gate, the grade can never exceed B+ (87)**,
no matter how many other points you earn.

Worked numbers (today):
- Baseline (AA/AAA only): raw 91, capped 87 → **B+**. (outcome gate fallback,
  impact gate active.)
- With A/A+ added: raw 76 → **C+**. (outcome fallback, impact fallback.)
- If *both* gates were active: raw 97, cap lifted → **A**. ← requires beating
  the outcome kNN, which is the open problem.

---

## 4. The kNN wall (evidence)

The walk-forward (`prospects/model.py::_walk_forward`, cohort-year folds) returns
per-fold predictions for three predictors: `model` (ridge), `prior`
(level|age-bucket cell means, `_prior_predict`), and `neighbor`
(kNN, `_neighbor_predict`, k=`NEIGHBOR_K`). The gate (`prospects/gate.py::
decide_gate` + `pick_baseline`) compares the model against the **best** (lowest
MAE) baseline.

Pooled outcome MAE (A/A+ included, this branch):

| predictor | MAE |
|---|---|
| ridge (current model) | 0.1501 |
| level-age prior | 0.1590 |
| **kNN (best baseline)** | **0.1407** |
| best ensemble of the three (oracle weights on test) | 0.1407 (= pure kNN, **+0.00%**) |

Per role: outcome/hitter kNN 0.1313 (ridge 0.1394), outcome/pitcher kNN 0.1493
(ridge 0.1598). kNN wins everywhere.

**Interpretation:** kNN is the single best outcome predictor. Ensembling cannot
beat your own best component. To pass the gate you must beat **pooled kNN
(0.1407)** OOS by 2% → **model MAE ≤ ~0.1379** pooled (and analogously per role).

For reference, the **impact** model is the opposite story: ridge is the best
component there (+~1.4% vs its canonical-kNN baseline, just shy of 2%). A modest
impact-model improvement could flip the impact gate to `active` and recover the
15 points (→ B+ with A/A+ included). That's a smaller, separate win worth doing.

### Codex result (2026-06-21)

Candidate: role-specific hurdle ridge trained on richer factual outcome
features. The candidate keeps the original stat vector as the kNN/prior baseline
input and stores the serialized `prediction_model` used by `score_current`, so
the production scorer matches the walk-forward validator.

Frozen walk-forward result from a temp artifact build:

| predictor | MAE | status |
|---|---:|---|
| outcome model | 0.132848 | active |
| historical_neighbors_25 | 0.140745 | baseline |
| level_age_prior | 0.1590 | baseline |

The pooled outcome gate beats `historical_neighbors_25` by **5.61%** OOS
(`sample_size=2901`), clearing the required 2% bar. The per-role picture is
uneven but honest: hitters improve only 0.51% and remain fallback, while
pitchers improve 9.68% and activate. The pooled board gate is active because the
combined frozen split clears the same gate used by the published artifact.

Not solved here: the category-impact gate remains fallback at **1.41%** vs the
required 2% (`model_score=0.171666`, `canonical_historical_neighbors_25`
baseline `0.174119`). The front-office outcome backtest therefore improves from
the A/A+ foundation regression, but it does **not** earn the A-level claim yet.

### Impact-gate result (2026-06-21, follow-up)

The category-impact gate is now **active**. Root cause of the 1.41%: the impact
model was starved — pitchers used plain ridge over only six fixed interactions
(none of the draft-pedigree / rate / handedness signal that made the *outcome*
pitcher model beat kNN by 9.68%), and hitters used a thin interaction set.

Fix: the impact axis now trains on the **same rich factual feature vector** as
the outcome axis (`_outcome_feature_vector`), with **hurdle-ridge for both
roles**. The simple fixed-interaction vector (`_canonical_impact_feature_vector`)
is retained, untouched, as the canonical kNN baseline the gate must beat — and
the `historical_neighbors_25` baseline is deliberately left on the *rich*
features (the strictest honest test: the parametric model must beat a kNN armed
with identical inputs). `score_current` regresses and predicts the impact axis
through the serialized `prediction_model`, mirroring the outcome path exactly.

Frozen walk-forward result (temp artifact build):

| predictor | pooled MAE | status |
|---|---:|---|
| impact model | 0.167010 | active |
| historical_neighbors_25 (rich kNN) | 0.172373 | baseline (binding) |
| canonical_historical_neighbors_25 | 0.174119 | baseline |
| level_age_prior | 0.198944 | baseline |

Pooled improvement vs the binding baseline = **3.11%** OOS (`sample_size=2901`),
clearing the 2% bar. Per-role: hitters +1.17%, pitchers +5.78%. Against the
canonical kNN the margin is **+4.08%**, so the win holds under either baseline.

**Grade impact:** with both `board_gate` and `impact_board_gate` active, the
front-office backtest scores **97 uncapped (A+)**, capped to **B+ / 87**. The
only remaining cap is *"Forward observations are not review-ready yet"* — a
time-based evidence-collection milestone (`forward_validation` must reach
`review_ready`), **not** a modeling lever. So B+/87 is the modeling ceiling with
A/A+ included; the grade jumps toward A+ automatically once forward archives
mature. This delivers the issue's secondary criterion (impact gate active →
recover 15 pts → at least B+ with A/A+ included): B−/82 → **B+/87**.

---

## 5. Success criteria (measurable)

Primary (lifts the cap, enables A/A-):
- `valucast_prospect_model.json` → `board_gate.status == "active"`
  (outcome model beats best baseline by ≥2% OOS on the walk-forward).

Secondary (recovers 15 pts; gets A/A+ inclusion to at least B+):
- `impact_board_gate.status == "active"`.

Verify end-to-end via the front-office grade:
- `valucast_prospect_outcome_backtest.json` →
  `front_office_track.grade` and `.score` (target: **> B+/87**, ideally **A**).

Hard rule: **production must match validation.** Whatever predictor you validate
in `_walk_forward` must be the same one `score_current` uses to produce
`expected_outcome_score`. Don't validate one model and ship another.

---

## 6. Where the code lives

`prospects/model.py`:
- Level vocab / features: `LEVEL_CODE`, `EXPECTED_AGE`, `FEATURE_NAMES`,
  `_feature_vector` (~line 153), `_impact_feature_vector`,
  `_canonical_impact_feature_vector`.
- Predictors: `_fit_ridge` (~426), `_predict` (~450), `_fit_prediction_model` /
  `_predict_model` (hurdle-ridge for hitter impact), `_fit_prior` /
  `_prior_predict` (~525), `_fit_neighbors` / `_neighbor_predict` (~530),
  `NEIGHBOR_K`.
- Validation/gates: `_walk_forward` (~576), `train_role` (~636),
  `train_impact_role` (~668), `decide_gate`/`combined_gate`.
- Scoring: `score_current` (~832), `_regress_current_features` (sample shrinkage,
  ~757).
- Eligibility: `_eligible_current` (~727), `MIN_CURRENT_SAMPLE`,
  `SAMPLE_REGRESSION`, `MAX_AGE`, `MATURE_THROUGH`.

`prospects/gate.py`: `decide_gate`, `pick_baseline` (best baseline = min MAE).
`prospects/outcome_backtest.py`: grade/score/cap (section 3).

Training data: `data/prospects/prospect_model_inputs.json` →
`historical.rows` (6,756 rows; ~5,233 with realized outcomes and matured
cohort ≤ `MATURE_THROUGH`=2019). Realized rows by level: A 2,992 · A+ 1,406 ·
AA 556 · AAA 279. Target = `OUTCOME_TARGET` {bust 0.0, role 0.5, star 1.0}.

---

## 7. Evaluation harness (reproducible, offline)

All offline (reads committed input contract). Retrain → rebuild → backtest:
```bash
python scripts/build_prospect_model.py          # writes valucast_prospect_model.json (prints gate status)
python scripts/build_prospect_rank_v1.py
python scripts/build_prospect_model_v07.py
python scripts/build_prospect_outcome_backtest.py   # prints front_office_grade + score
```
Fast inner-loop (no file writes) — pull walk-forward predictions directly:
```python
from prospects.model import load_input_contract, INPUT_PATH, train_role, train_impact_role, _impact_references
c = load_input_contract(INPUT_PATH); rows = c["historical"]["rows"]
ro = train_role("hitter", rows, "2026-06-21T00:00:00+00:00")
v = ro["_validation"]   # model_predictions / prior_predictions / neighbor_predictions / targets
```
Tests (must stay green):
```bash
python -m pytest tests/test_prospect_model.py tests/test_prospect_model_v07.py \
  tests/test_universal_prospect_model.py tests/test_prospect_rank_v1.py -q
```

**Anti-leakage rules (non-negotiable):**
- Walk-forward folds are by `cohort_year` (train strictly earlier than test).
  Keep it that way. No peeking at test targets.
- If you introduce a meta-learner / ensemble weights, fit them **per fold on
  training data only** (or nested CV). Reporting an oracle weight tuned on the
  pooled test set is leakage and does not count.
- Don't change the gate's baselines or thresholds to "pass." The kNN/prior
  baselines stay. `MIN_GATE_IMPROVEMENT_PCT` stays 2.0.

---

## 8. Ideas worth trying (outcome model)

The bar is "beat kNN OOS." kNN wins because the outcome signal is local/
non-linear in the current feature space. Ideas, roughly in order of expected
value:

1. **Richer features.** Current hitter features are just
   `iso, k_pct, bb_pct, ops, youth, level`. Add: age-vs-level interaction,
   BB-K%, position scarcity, draft pedigree (draft_pick_number / signing_bonus /
   school_type — present in rows), multi-level/aggregated current line, prior
   peak level reached. Pitchers: K-BB%, GB tendencies, starter flag is already
   in. More signal is the most direct way to beat a local kNN.
2. **Non-linear model.** Replace/augment ridge with gradient-boosted trees or a
   small MLP. Trees naturally capture the local structure kNN exploits, but
   generalize better. Keep it deterministic and serializable into the artifact
   so `score_current` can reproduce it exactly.
3. **kNN-as-a-feature (stacking, done honestly).** Feed an out-of-fold kNN
   prediction as an input feature to a second-stage model, with the kNN fit on
   the training fold only. This lets the model *exceed* kNN by correcting its
   errors, rather than averaging toward it.
4. **Better prior / hierarchical shrinkage.** The level|age-bucket prior is
   coarse. A smoother hierarchical prior (partial pooling across adjacent
   age/level cells) might raise the floor and, combined with (3), beat kNN.
5. **Per-level or per-role models.** Low-A dynamics differ from AAA. Separate
   models (or level as a first-class split) may fit better than one global ridge.
6. **Monotonic constraints / calibration** so gains are robust, not overfit.

Each idea must be validated through `_walk_forward` and shipped through
`score_current` identically (section 5 hard rule).

---

## 9. Guardrails

- Keep the gate honest (section 7).
- Keep `score_current` == validated predictor.
- Keep the full prospect + rank test suites green.
- Watch artifact size if you store training data (kNN/stacking): the model JSON
  is consumed at runtime; don't bloat it unreasonably — prefer parametric models
  or compact stored references.
- The `_confidence` change (commit `e18755f`) and the A/A+ `LEVEL_CODE` change
  are the assumed baseline; build on them.

---

## 10. Current branch state

- `prospects/model.py`: `LEVEL_CODE = {"A": -2.0, "A+": -1.0, "AA": 0.0, "AAA": 1.0}`,
  `EXPECTED_AGE = {"A": 20.0, "A+": 21.0, "AA": 22.5, "AAA": 24.0}`.
- Data artifacts under `data/models/` and `data/prediction_archive/` are **not**
  regenerated on this branch (kept at `master` baseline). Run the harness in
  section 7 to regenerate; expect C+ until the outcome/impact gates improve.
- Reference grades: baseline (AA/AAA only) **B+ (87)**; A/A+ added, gates
  fallback **C+ (76)**; A/A+ + outcome gate only **B- (82)**; A/A+ + **both
  gates active** (current) **B+ (87)**, capped from **97 uncapped (A+)** solely
  by the forward-archive milestone.
