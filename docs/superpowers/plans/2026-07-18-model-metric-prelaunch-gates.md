# Model Metric Pre-Launch Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the advisory H+P forward-rate evidence and expose enough ROS diagnostics to keep any public Skill+ display held until its inputs are honest.

**Architecture:** Derive forward actual rates from the already-archived freeze-date and current counting components, then score the two frozen projection sources against those deltas. Keep the comparison advisory and default-off. Add diagnostics to the existing H+P run manifest; do not introduce a new model, metric, dependency, rank input, or public surface.

**Tech Stack:** Python standard library, pytest, existing JSON artifacts.

## Global Constraints

- Preserve the model freeze and failed pitcher-decay flag.
- Keep Steamer as the live MLB projection source.
- Do not change ranks, values, pitcher caps, Role Watch, or publication automatically.
- Do not edit `.github/`, `plans/`, frozen forward-prospect modules/tests, or generated public artifacts.
- Do not build Hitter Skill+ or Pitcher Skill+ in this pass.
- Reuse existing actuals snapshots and pytest coverage; add no dependency.

---

### Task 1: Correct the advisory forward-rate comparison

**Files:**
- Modify: `mlb/projection_source_comparison.py`
- Modify: `templates/methodology.html`
- Test: `tests/test_mlb_projection_source_comparison.py`
- Test: `tests/test_methodology_validation.py`

**Interfaces:**
- Consumes: frozen pure rate projections plus `data/prediction_archive/valucast_actuals_snapshot/<freeze-date>.json` and current cumulative actuals.
- Produces: `_actual_rate_deltas(as_of_rows, current_rows) -> dict[str, dict]`, role-separated score summaries, and the existing advisory comparison artifact shape.

- [ ] **Step 1: Write failing delta-rate tests**

Add hitter and pitcher fixtures whose cumulative season rates differ from their post-freeze rates. Assert `_actual_rate_deltas()` returns forward PA/IP and rates reconstructed from component deltas:

```python
def test_actual_rate_deltas_rebuild_hitter_rates_from_forward_components():
    lines = _actual_rate_deltas(
        [_actual_hitter(1, pa=100, ab=90, h=20, singles=14, doubles=4, triples=0, hr=2, bb=8, hbp=1, sf=1)],
        [_actual_hitter(1, pa=160, ab=140, h=40, singles=26, doubles=8, triples=1, hr=5, bb=16, hbp=2, sf=2)],
    )
    assert lines["1"] == {
        "role": "hitter",
        "rates": {"AVG": 0.4, "OBP": 0.4833, "SLG": 0.7, "OPS": 1.1833},
        "volume": 60.0,
    }


def test_actual_rate_deltas_rebuild_pitcher_rates_from_forward_components():
    lines = _actual_rate_deltas(
        [_actual_pitcher(2, ip=40, er=12, bb=10, hits=35)],
        [_actual_pitcher(2, ip=65, er=22, bb=17, hits=55)],
    )
    assert lines["2"] == {
        "role": "pitcher",
        "rates": {"ERA": 3.6, "WHIP": 1.08},
        "volume": 25.0,
    }
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_mlb_projection_source_comparison.py -k actual_rate_deltas`

Expected: collection/import failure because `_actual_rate_deltas` does not exist.

- [ ] **Step 3: Implement the minimum component-delta reconstruction**

Add locked component tuples and two small helpers. Use non-negative deltas and return no rate line when the forward denominator is zero:

```python
HITTER_RATE_COMPONENT_KEYS = ("PA", "AB", "H", "1B", "2B", "3B", "HR", "BB", "HBP", "SF")
PITCHER_RATE_COMPONENT_KEYS = ("IP", "ER", "BB", "H_ALLOWED")


def _actual_rate_component_lines(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        mlbam_id = _mlbam_id(row)
        if not mlbam_id:
            continue
        role = _role(row)
        stats = row.get("stats") or {}
        keys = PITCHER_RATE_COMPONENT_KEYS if role == "pitcher" else HITTER_RATE_COMPONENT_KEYS
        components = {key: _finite(stats.get(key)) or 0.0 for key in keys}
        volume = components["IP" if role == "pitcher" else "PA"]
        existing = out.get(mlbam_id)
        if existing is None or volume > existing["volume"]:
            out[mlbam_id] = {"role": role, "components": components, "volume": volume}
    return out


def _actual_rate_deltas(as_of_rows: list[dict], current_rows: list[dict]) -> dict[str, dict]:
    starts = _actual_rate_component_lines(as_of_rows)
    ends = _actual_rate_component_lines(current_rows)
    out: dict[str, dict] = {}
    for mlbam_id, end in ends.items():
        start = starts.get(mlbam_id)
        if not start or start["role"] != end["role"]:
            continue
        components = {
            key: max(0.0, value - start["components"].get(key, 0.0))
            for key, value in end["components"].items()
        }
        role = end["role"]
        if role == "pitcher":
            ip = components["IP"]
            if ip <= 0:
                continue
            rates = {
                "ERA": round(9 * components["ER"] / ip, 4),
                "WHIP": round((components["BB"] + components["H_ALLOWED"]) / ip, 4),
            }
            volume = ip
        else:
            ab = components["AB"]
            obp_denom = ab + components["BB"] + components["HBP"] + components["SF"]
            if ab <= 0 or obp_denom <= 0:
                continue
            total_bases = (
                components["1B"] + 2 * components["2B"]
                + 3 * components["3B"] + 4 * components["HR"]
            )
            avg = components["H"] / ab
            obp = (components["H"] + components["BB"] + components["HBP"]) / obp_denom
            slg = total_bases / ab
            rates = {
                "AVG": round(avg, 4), "OBP": round(obp, 4),
                "SLG": round(slg, 4), "OPS": round(obp + slg, 4),
            }
            volume = components["PA"]
        out[mlbam_id] = {"role": role, "rates": rates, "volume": round(volume, 3)}
    return out
```

The hitter formula is `AVG=H/AB`, `OBP=(H+BB+HBP)/(AB+BB+HBP+SF)`, `SLG=TB/AB`, `OPS=OBP+SLG`. The pitcher formula is `ERA=9*ER/IP`, `WHIP=(BB+H_ALLOWED)/IP`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest -q tests/test_mlb_projection_source_comparison.py -k actual_rate_deltas`

Expected: 2 passed.

- [ ] **Step 5: Write failing path, role-veto, and advisory-copy tests**

Add a test that writes a freeze-date actuals snapshot and later cumulative actuals, calls the path loader, and asserts the scoreable population is based on the forward delta rather than cumulative PA/IP. Assert `comparison_basis.scoreable_players_by_role` reports hitters and pitchers separately, each role owns its own gate, and `publication_veto.status` remains `held` unless both role gates are active. Update the existing methodology honesty test: a legacy committed artifact without `post_freeze_component_deltas` provenance must render a repair notice and state that the stored readout is excluded from publication decisions.

- [ ] **Step 6: Verify RED**

Run: `python -m pytest -q tests/test_mlb_projection_source_comparison.py tests/test_methodology_validation.py -k 'post_freeze or scoreable_players_by_role or publication_veto or honesty_polish'`

Expected: failure because the runner still passes cumulative `_actual_lines(actuals_rows)`, emits no role counts/veto, and the page still publishes the invalid magnitude.

- [ ] **Step 7: Route the runner through the archived freeze-date actuals**

Load `<actuals_snapshot_dir>/<oldest-freeze-date>.json`, derive `_actual_rate_deltas`, and pass those lines to `build_comparison`. If the snapshot is absent, pass an empty mapping so the gate fails closed. Add `rate_actuals_method`, `scoreable_players_by_role`, per-role scores/gates, and a non-live `publication_veto`; define `marcel_beats_steamer` as true only when the overall gate and both role gates are active. Retain the advisory-only/manual-flip invariants.

In `templates/methodology.html`, render the numeric comparison only when `rate_actuals_method == "post_freeze_component_deltas"`. Otherwise state that the stored cumulative-rate readout is not a valid post-freeze score and is excluded from publication decisions. For a corrected artifact, render hitter and pitcher ratios separately and state that both roles must clear independently.

- [ ] **Step 8: Verify Task 1**

Run: `python -m pytest -q tests/test_mlb_projection_source_comparison.py tests/test_methodology_validation.py`

Expected: all tests pass.

### Task 2: Add ROS input diagnostics and keep public Skill+ held

**Files:**
- Modify: `scripts/build_valucast_hp_run.py`
- Test: `tests/test_build_valucast_hp_run.py`

**Interfaces:**
- Consumes: existing ROS rows after `apply_actuals_to_remaining`.
- Produces: per-row `actuals_applied` / `remaining_opportunity_clamped` metadata and manifest `remaining_opportunity_diagnostics` / `public_skill_metric_gate` fields.

- [ ] **Step 1: Write failing metadata and manifest tests**

Assert a matched row records whether actuals were applied and whether PA/IP was clamped to zero. Assert `build_manifest()` counts rows, matches, zero-remaining rows, and clamped rows by role. A known clamp must emit:

```python
{
    "status": "held",
    "affects_live_outputs": False,
    "reason": "remaining-opportunity clamping is present",
}
```

Assert a no-clamp fixture emits `status == "display_only_eligible"`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_build_valucast_hp_run.py -k 'metadata or public_skill_metric_gate or diagnostics'`

Expected: failures because the metadata and manifest fields do not exist.

- [ ] **Step 3: Implement the smallest diagnostics pass**

In `apply_actuals_to_remaining`, record the two booleans without changing any projected stat. In `build_manifest`, summarize:

```python
{
    "hitters": {"rows": int, "actuals_matched": int, "zero_remaining": int, "clamped_to_zero": int},
    "pitchers": {"rows": int, "actuals_matched": int, "zero_remaining": int, "clamped_to_zero": int},
}
```

Hold only the prospective display metric. Do not make the shadow build fail and do not modify any live rank/value consumer.

- [ ] **Step 4: Verify Task 2**

Run: `python -m pytest -q tests/test_build_valucast_hp_run.py`

Expected: all tests pass.

### Task 3: Regression and boundary verification

**Files:**
- Verify only; do not modify generated artifacts.

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: evidence that advisory/model-freeze boundaries remain intact.

- [ ] **Step 1: Run focused regression**

Run: `python -m pytest -q tests/test_mlb_projection_source_comparison.py tests/test_build_valucast_hp_run.py tests/test_methodology_validation.py tests/test_app.py -k 'projection_source or valucast_hp or methodology or OutcomeMix or panel_renders_high_on_prospect_card'`

Expected: all selected tests pass.

- [ ] **Step 2: Run the relevant validators**

Run: `python scripts/validate_mlb_projection_source_comparison.py && python scripts/validate_projection_scorecard.py`

Expected: both exit 0; the committed comparison remains advisory and no superiority claim is created.

- [ ] **Step 3: Inspect scope**

Run: `git diff --check && git status --short && git diff -- mlb/projection_source_comparison.py scripts/build_valucast_hp_run.py tests/test_mlb_projection_source_comparison.py tests/test_build_valucast_hp_run.py`

Expected: only the plan and four scoped implementation/test files changed; no generated data, `.github`, rank/value, Role Watch, publication, or frozen-prospect files changed.
