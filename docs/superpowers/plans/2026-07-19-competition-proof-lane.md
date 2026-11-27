# Competition Proof Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register and run honest, outcome-grounded ValuCast comparisons against anonymous public baseline classes without changing any live score, rank, value, cap, or publication decision.

**Architecture:** Add one pure comparison module that freezes matched ranked cohorts and grades them only when realized fantasy outcomes exist. A small build script consumes the existing dated ValuCast archives plus private source metadata and emits private evidence plus a sanitized public artifact. Missing outcomes produce `collecting`, never a superiority claim.

**Tech Stack:** Python standard library, NumPy already used by the repository, pytest, committed JSON artifacts.

## Global Constraints

- Preserve the model freeze and failed decay flag.
- Comparison data is display/research-only and never feeds live rank, value, Role Watch, pitcher caps, or publication.
- Do not backdate a prediction or overwrite a registered cohort.
- Claim superiority only for the registered task, cohort, horizon, and anonymous baseline class.
- Use a paired hierarchical bootstrap that resamples completed cohorts first and matched players within each sampled cohort; publish the full denominator.
- No industry-standard superiority claim is authorized below 150 unique matched players, below 5% relative improvement, with a non-positive confidence-interval guard, with worse top-k regret, or when any completed cohort or role is more than 5% worse on the primary metric.
- Public artifacts use anonymous source classes; source identity and capture hashes remain private.

---

### Task 1: Freeze the proof contract

**Files:**
- Create: `plans/032-competition-proof-lane.md`
- Modify: `plans/README.md`

**Interfaces:**
- Consumes: the approved two-stage validation design and existing Plan 030 forward-ledger conventions.
- Produces: frozen track definitions, metrics, claim gates, and source rules used by Task 2.

- [ ] **Step 1: Write the registration**

Register two independent tracks: four-year prospect fantasy value versus a public prospect-board baseline, and 2026 rest-of-season pitcher fantasy value versus a public pitcher-skill baseline. Freeze percentile-rank MAE as primary, pairwise concordance and top-k regret as confirmers, three independent cohorts as the minimum, and two-sided 95% percentile intervals from the paired hierarchical bootstrap that resamples completed cohorts first and matched players within each sampled cohort as the superiority gate.

- [ ] **Step 2: Record the plan in the index**

Add Plan 032 as `REGISTERED + DARK`; explicitly state that both tracks begin in `collecting` status.

### Task 2: Build the smallest executable comparison lane

**Files:**
- Create: `tests/test_competition_proof.py`
- Create: `prospects/competition_benchmark.py`
- Create: `scripts/build_competition_benchmark.py`
- Create privately: `data/private/competition/sources.json`
- Create privately: `data/private/competition/benchmark.json`
- Create: `data/validation/valucast_competition_evidence.json`

**Interfaces:**
- Consumes: `build_track(cohorts: list[dict], outcomes: dict, criteria: dict) -> dict` inputs containing immutable ranked rows and realized scores.
- Produces: a private benchmark with per-track coverage, paired error comparison, confirmers, and an evidence-gated status, plus a sanitized public evidence artifact.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_missing_outcomes_cannot_claim_superiority():
    result = build_track([cohort], {}, criteria)
    assert result["status"] == "collecting"

def test_superiority_requires_sample_cohorts_and_positive_ci():
    result = build_track(three_resolved_cohorts, outcomes, criteria)
    assert result["status"] == "validated_superiority"
    assert result["primary"]["error_delta_ci_low"] > 0
```

- [ ] **Step 2: Run the tests and confirm RED**

Run: `python -m pytest tests/test_competition_proof.py -q`
Expected: collection failure because `prospects.competition_benchmark` does not exist.

- [ ] **Step 3: Implement the minimal evaluator**

Implement deterministic cohort hashing, common-player ranking, percentile-rank absolute error, a paired hierarchical bootstrap that resamples completed cohorts first and matched players within each sampled cohort, pairwise concordance, top-k realized-value regret, coverage/sample gates, and four honest statuses: `collecting`, `no_significant_difference`, `validated_superiority`, and `validated_underperformance`.

- [ ] **Step 4: Run the tests and confirm GREEN**

Run: `python -m pytest tests/test_competition_proof.py -q`
Expected: all tests pass.

- [ ] **Step 5: Register the first two cohorts**

The builder must freeze the 2026-07-19 prospect-board intersection of 2,611 matched players and the 2026-07-17 pitcher-skill intersection of 12/12 published starters. It must record source identity and hashes only in the private registry and emit both tracks as `collecting` because no registered horizon has matured.

- [ ] **Step 6: Verify the artifact and regressions**

Run:

```powershell
python scripts/build_competition_benchmark.py --write
python -m pytest tests/test_competition_proof.py tests/test_forward_cohort.py tests/test_forward_scoreboard.py -q
python -m pytest -q
```

Expected: the artifact validates, targeted tests pass, and the full suite passes.

### Task 3: Run a claim-blocked, source-anonymous historical replay

**Files:**
- Create: `docs/superpowers/specs/2026-07-19-competition-historical-replay-design.md`
- Extend privately: `data/private/competition/sources.json`
- Modify: `scripts/build_competition_benchmark.py`
- Create: `data/validation/valucast_competition_evidence.json`
- Modify: `tests/test_competition_proof.py`
- Modify: `plans/032-competition-proof-lane.md`

**Interfaces:**
- Consumes: `prospects.rank_backtest._fold_board_scores`, the committed prospect
  input contract, dated public preseason prospect boards from 2019/2020/2022,
  and `prospects.competition_benchmark.build_cohort/build_track`.
- Produces: deterministic private research evidence with combined and per-role
  historical comparisons whose `claim_authorized` value is always false; the
  public artifact remains empty.

- [x] **Step 1: Capture immutable public-board rows**

Store source identity, capture hashes, and row evidence only in the private
registry. Use 2019 for the 2018 ValuCast fold, 2020 for 2019, and 2022 for 2021;
all three boards precede their four-year outcome windows. Public outputs expose
only aggregate results and an anonymous source class.

- [x] **Step 2: Write failing behavior tests**

```python
def test_historical_replay_never_authorizes_a_claim():
    result = build_research_replay(synthetic_contract, synthetic_boards)
    assert result["status"] == "research_only"
    assert result["claim_authorized"] is False


def test_historical_replay_drops_ambiguous_name_matches():
    result = match_board_rows(ambiguous_contract_rows, board_rows)
    assert result["matched"] == []
    assert result["ambiguous"] == 1
```

- [x] **Step 3: Run the tests and confirm RED**

Run: `python -m pytest tests/test_competition_proof.py -q`
Expected: failure because the claim-blocked private replay is not yet represented
by the benchmark builder.

- [x] **Step 4: Implement the minimal replay**

Build ValuCast rank rows from the three neutralized fold scores, resolve only
unique normalized-name-and-role matches, evaluate the 91 matched players (30,
26, and 35 by cohort) in combined/hitter/pitcher views with the existing
benchmark functions, preserve the evaluator's raw statistical status under
`statistical_status`, and override the externally usable status to
`research_only` with `claim_authorized: false`. Record the underpowered
91-player result as descriptive historical estimates whose underlying current-
policy state is `collecting` under the 150-unique-player floor, including the
combined MAE values 0.306106 versus 0.277446, delta -0.028661, 95% CI
[-0.088668, 0.022223], and the 2019 fold's 28.4% combined-MAE loss to the 2020
public-board baseline. This `research_only` replay is not a superiority verdict.

- [x] **Step 5: Verify the replay and regressions**

Run:

```powershell
python scripts/build_competition_benchmark.py --write
python -m pytest tests/test_competition_proof.py tests/test_prospect_rank_backtest.py -q
python -m ruff check scripts/build_competition_benchmark.py tests/test_competition_proof.py
python -m pytest -q
```

Expected: the replay artifact is deterministic, every comparison remains
claim-blocked, targeted tests pass, lint passes, and the full suite passes.
