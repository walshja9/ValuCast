# Risk / Uncertainty Model v1 — Design Spec

**Date:** 2026-05-28
**Scope:** Dynasty + Prospects modes only (redraft deferred to v1.1)
**Behavior:** Annotation-only — risk metadata displayed alongside existing values, no value adjustment or re-ranking

## Goal

For every dynasty/prospect player, show:

```
Dynasty Value: 76.6
Range: 55-90
Risk: High
Drivers: Pitcher prospect, ETA 2028, Mid-minors level
```

Expected value and risk are orthogonal concepts. They stay separate in v1. Future controls (sort by floor/ceiling, win-now vs rebuild lens) build on this foundation.

## Core Types

File: `src/league_values/risk.py`

```python
@dataclass(frozen=True)
class RiskDriver:
    id: str              # e.g., "pitcher_prospect", "eta_distant"
    label: str           # e.g., "Pitcher prospect", "ETA 2028"
    score_delta: float   # contribution to risk_score
    floor_drag: float    # subtracted from value for value_low
    ceiling_lift: float  # added to value for value_high

@dataclass(frozen=True)
class RiskAssessment:
    risk_score: float          # 0.0-1.0, clamped
    risk_level: str            # "Low", "Moderate", "High", "Extreme"
    value_low: float           # floor, clamped to 0
    value_high: float          # ceiling, clamped to 150
    drivers: tuple[RiskDriver, ...]

    @property
    def driver_labels(self) -> tuple[str, ...]:
        return tuple(d.label for d in self.drivers)

    def to_dict(self) -> dict:
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "value_low": self.value_low,
            "value_high": self.value_high,
            "drivers": [d.label for d in self.drivers],
        }
```

## Risk Levels

Fixed thresholds. Risk describes the player, not the population.

```python
RISK_LEVELS: tuple[tuple[float, str], ...] = (
    (0.25, "Low"),
    (0.50, "Moderate"),
    (0.75, "High"),
    (1.00, "Extreme"),
)
```

Boundary behavior: `<=` comparison. A score of exactly 0.25 is "Low".

Level descriptions:
- **Low:** established role, stable projection
- **Moderate:** some age, role, or volatility risk
- **High:** wide outcome band
- **Extreme:** long ETA, limited track record, or major uncertainty

## Value Range Computation

Asymmetric ranges via driver-contributed floor_drag and ceiling_lift. Dynasty risk is not normally distributed — prospects skew high-upside/deep-downside, aging veterans skew downside-heavy.

```
value_low  = max(0.0, value - sum(driver.floor_drag))
value_high = min(150.0, value + sum(driver.ceiling_lift))
risk_score = min(1.0, sum(driver.score_delta))
```

Each driver contributes independently. Drivers stack additively.

## Driver Registry (v1)

Every player receives the baseline driver. All other drivers fire conditionally.

| Driver ID | Condition | score | floor | ceil | Label |
|-----------|-----------|-------|-------|------|-------|
| `baseline` | always | 0.03 | 3 | 3 | "Baseline uncertainty" |
| `pitcher_type` | SP/RP positions | 0.05 | 5 | 3 | "Pitcher volatility" |
| `pitcher_prospect` | pitcher + prospect | 0.08 | 8 | 6 | "Pitcher prospect" |
| `prospect_status` | `player_type == "prospect"` | 0.10 | 8 | 10 | "Prospect" |
| `eta_distant` | prospect + `eta >= current_year + 2` | 0.12 | 8 | 5 | "ETA {eta}" |
| `eta_near` | prospect + `eta == current_year + 1` | 0.04 | 3 | 3 | "ETA {eta}" |
| `low_minors` | prospect + `level in (A, A+, CPX, R)` | 0.12 | 10 | 8 | "Low-minors level" |
| `mid_minors` | prospect + `level in (AA,)` | 0.06 | 5 | 4 | "Mid-minors level" |
| `high_minors` | prospect + `level in (AAA,)` | 0.03 | 3 | 3 | "Upper-minors level" |
| `source_spread` | prospect + numeric rank spread > threshold | 0.08 | 7 | 4 | "High source-rank spread" |
| `age_young` | prospect + `age <= 21` | 0.06 | 5 | 6 | "Age {age} (young)" |
| `age_decline` | `age >= 33` | 0.10 | 8 | 1 | "Age {age} (decline)" |
| `age_deep_decline` | `age >= 36` | 0.06 | 5 | 0 | "Age {age} (deep decline)" |
| `incomplete_profile` | prospect + missing eta/level/source_ranks | 0.05 | 5 | 3 | "Incomplete scouting profile" |
| `breakout_helium` | positive breakout label | 0.05 | 3 | 8 | "Breakout / helium" |

### Driver notes

- **Level drivers** are mutually exclusive (only one fires).
- **ETA drivers** are mutually exclusive (distant vs near).
- **age_decline and age_deep_decline** stack intentionally. A 37-year-old gets both: floor_drag 13, ceiling_lift 1.
- **age_young** is prospect-only. A 21-year-old MLB player is not inherently riskier in the same way.
- **pitcher_type** is softened for MLB arms (floor 5). The real weight comes from **pitcher_prospect** stacking on top for prospect pitchers.
- **source_spread** filters to numeric values, requires >= 2 valid ranks. Threshold to be determined from inspecting actual DD feed distribution before implementation.
- **breakout_helium** fires only on positive labels: `{"major_breakout", "breakout", "rising"}`. Negative trend labels (slipping, falling) are a future driver, not v1.
- **limited_mlb_sample** deferred from v1 — no reliable sample-size signal in the DD feed.

### Archetype examples

**Aaron Judge (MLB, OF, age 33):**
- Drivers: baseline + age_decline
- Score: 0.13 → Low
- Range: 121.5 → 110-126

**Paul Skenes (MLB, SP, age 23):**
- Drivers: baseline + pitcher_type
- Score: 0.08 → Low
- Range: 148.0 → 140-150 (clamped)

**Trey Yesavage (prospect, SP, age 23, AA, ETA 2027):**
- Drivers: baseline + pitcher_type + pitcher_prospect + prospect_status + eta_distant + mid_minors
- Score: 0.44 → Moderate
- Range: 98.2 → 61-128

**17yo complex-league prospect (prospect, SS, age 17, CPX, ETA 2030):**
- Drivers: baseline + prospect_status + eta_distant + low_minors + age_young + incomplete_profile (likely)
- Score: 0.48+ → Moderate/High
- Range: 5.2 → 0-40

## RiskModel Class

```python
class RiskModel:
    POSITIVE_BREAKOUT_LABELS = {"major_breakout", "breakout", "rising"}

    def __init__(self, current_year: int | None = None):
        self.current_year = current_year or date.today().year

    def evaluate_dynasty(self, row, value: float | None = None) -> RiskAssessment:
        """Evaluate risk for a dynasty/prospect row.

        Uses duck typing — row must have: player_type, positions, age,
        dynasty_value. Optional: eta, level, source_ranks, breakout_label.
        """
        value = row.dynasty_value if value is None else value
        drivers = self._dynasty_drivers(row)
        return self._build_assessment(value, drivers)

    def evaluate_redraft(self, player, result=None, metadata=None):
        raise NotImplementedError  # v1.1

    def _dynasty_drivers(self, row) -> list[RiskDriver]:
        # Detects all applicable drivers from row attributes.
        # See Driver Registry above for full logic.
        ...

    def _build_assessment(self, value: float, drivers: list[RiskDriver]) -> RiskAssessment:
        risk_score = min(1.0, sum(d.score_delta for d in drivers))
        floor_drag = sum(d.floor_drag for d in drivers)
        ceiling_lift = sum(d.ceiling_lift for d in drivers)
        value_low = max(0.0, value - floor_drag)
        value_high = min(150.0, value + ceiling_lift)

        risk_level = "Extreme"
        for threshold, level in RISK_LEVELS:
            if risk_score <= threshold:
                risk_level = level
                break

        return RiskAssessment(
            risk_score=round(risk_score, 3),
            risk_level=risk_level,
            value_low=round(value_low, 1),
            value_high=round(value_high, 1),
            drivers=tuple(drivers),
        )
```

### Design constraints

- **No web layer imports.** `risk.py` lives in `src/league_values/` and uses duck typing for row input. No dependency on `DynastyRankingRow` or any `web/` module.
- **Injected year.** `current_year` passed at construction, defaults to `date.today().year`. ETA risk is relative to this year. Use the feed's season year when available.
- **Source rank cleaning.** Filter to numeric values (`int` or `float`), require >= 2 valid entries before computing spread.
- **`_build_assessment` is shared.** The `evaluate_redraft` path (v1.1) will use the same aggregation logic with different drivers.

## Web Integration

### Wiring (app.py)

Risk assessments are computed as a dict mapping, not mutated onto frozen rows:

```python
risk_model = RiskModel(current_year=feed_season_year)
risk_assessments = {
    row.id: risk_model.evaluate_dynasty(row)
    for row in dynasty_rows
}
```

Passed to templates alongside existing context:

```python
return render_template(
    "partials/dynasty_rankings.html",
    rows=dynasty_rows,
    risk_assessments=risk_assessments,
    ...
)
```

Templates access via:

```jinja2
{% set risk = risk_assessments.get(row.id) %}
```

### Rankings table

Add Risk and Range columns to dynasty/prospects tables:

```
| Rank | Player        | Value | Risk     | Range   |
|------|---------------|-------|----------|---------|
| 1    | Paul Skenes   | 148.0 | Low      | 140-150 |
| 15   | Trey Yesavage | 98.2  | Moderate | 61-128  |
| 250  | J. Complex    | 5.2   | High     | 0-40    |
```

Risk level displayed as a color badge:
- **Low** — green
- **Moderate** — amber/yellow
- **High** — orange
- **Extreme** — red

### Player detail modal

Below the existing value display, add a risk block:

```
Risk: High
Range: 62-118
Drivers: Pitcher volatility, Pitcher prospect, ETA 2028
```

Driver labels listed as a comma-separated line or bullet list depending on count.

### CSV export

Add four columns to dynasty/prospects CSV export:
- `Risk Level`
- `Value Low`
- `Value High`
- `Risk Drivers` (comma-joined labels)

### No new routes

Risk data flows through existing dynasty/prospect templates and export routes. No sorting or filtering by risk in v1.

## Testing

### tests/test_risk.py (~40 tests)

**Driver detection** — one test per driver verifying it fires and doesn't fire under correct conditions. Stub rows via `SimpleNamespace` (duck typing, no web imports needed).

**Driver stacking:**
- `test_drivers_stack_additively`
- `test_risk_score_clamped_at_1`
- `test_floor_clamped_at_0`
- `test_ceiling_clamped_at_150`

**Risk level thresholds:**
- `test_level_low_at_0`
- `test_level_low_at_boundary_025`
- `test_level_moderate_above_025`
- `test_level_high_above_050`
- `test_level_extreme_above_075`
- `test_level_extreme_at_1`

**Archetype integration tests:**
- `test_archetype_mlb_veteran_stable` — Low
- `test_archetype_mlb_pitcher_young` — Low
- `test_archetype_prospect_pitcher_mid` — Moderate
- `test_archetype_prospect_complex_young` — High/Extreme
- `test_archetype_mlb_aging_decline` — Moderate

**RiskAssessment helpers:**
- `test_driver_labels_property`
- `test_to_dict_structure`

**RiskModel constructor:**
- `test_default_year_is_current`
- `test_injected_year_used_for_eta`

**Mapping:**
- `test_risk_assessments_keyed_by_row_id`

### tests/test_app.py (6 tests added to existing file)

- `test_dynasty_table_shows_risk_column`
- `test_prospects_table_shows_risk_column`
- `test_dynasty_player_detail_shows_risk_block`
- `test_prospect_player_detail_shows_risk_block`
- `test_dynasty_export_includes_risk_columns`
- `test_prospects_export_includes_risk_columns`

## Future (not v1)

- **Sort/filter by risk:** Sort by floor, ceiling, risk-adjusted value. Team lens (win-now, balanced, rebuild).
- **Redraft risk (v1.1):** Playing-time fragility, no-ROS/actuals-only, small sample, injury/role uncertainty, volatile rate stats. Uses `evaluate_redraft()` through a post-processor wrapper.
- **Negative trend driver:** `slipping`, `falling`, `major_fall` labels → separate `negative_trend` driver.
- **Market calibration model:** ADP/expert rank comparison layer.
- **Trained ML replacement:** Once backtested, replace transparent scoring with a trained model calibrated against actual outcome variance.
