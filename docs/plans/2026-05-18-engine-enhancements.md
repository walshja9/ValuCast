# Engine Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add volume multiplier post-processor and RP-specific baseline handling so the engine produces trustworthy output for the league-values web app.

**Architecture:** Two new features: (1) a `VolumeMultiplier` post-processor that scales values by playing time using `(PA_or_IP / baseline)^0.75`, and (2) RP baseline support by splitting the `PITCHER` pool into `STARTER` and `RELIEVER` sub-pools so categories can have role-specific baselines.

**Tech Stack:** Python 3.12+, dataclasses, unittest. No external dependencies.

**Test runner:** `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`

---

### Task 1: VolumeMultiplier Post-Processor

**Files:**
- Modify: `src/league_values/post_processors.py`
- Modify: `src/league_values/__init__.py`
- Test: `tests/test_post_processors.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_post_processors.py`:

```python
from league_values.post_processors import VolumeMultiplier


class TestVolumeMultiplier(unittest.TestCase):
    def _league(self):
        return LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )

    def test_full_time_hitter_gets_1(self):
        vol = VolumeMultiplier(hitter_pa=550, sp_ip=180, rp_ip=65)
        league = self._league()
        players = [
            {"id": "full", "name": "Full Time", "pool": "hitter", "stats": {"HR": 30, "PA": 600}},
            {"id": "anchor", "name": "Anchor", "pool": "hitter", "stats": {"HR": 10, "PA": 550}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = vol.process(raw, league)
        full = next(r for r in adjusted if r.name == "Full Time")
        full_raw = next(r for r in raw if r.name == "Full Time")
        self.assertAlmostEqual(full.total_value, full_raw.total_value, places=5)

    def test_partial_hitter_gets_discount(self):
        vol = VolumeMultiplier(hitter_pa=550, sp_ip=180, rp_ip=65)
        league = self._league()
        players = [
            {"id": "partial", "name": "Partial", "pool": "hitter", "stats": {"HR": 30, "PA": 200}},
            {"id": "anchor", "name": "Anchor", "pool": "hitter", "stats": {"HR": 10, "PA": 550}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = vol.process(raw, league)
        partial_raw = next(r for r in raw if r.name == "Partial")
        partial_adj = next(r for r in adjusted if r.name == "Partial")
        # (200/550)^0.75 = ~0.51
        self.assertLess(abs(partial_adj.total_value), abs(partial_raw.total_value))

    def test_zero_pa_gets_floor(self):
        vol = VolumeMultiplier(hitter_pa=550, sp_ip=180, rp_ip=65)
        league = self._league()
        players = [
            {"id": "zero", "name": "Zero PA", "pool": "hitter", "stats": {"HR": 30, "PA": 0}},
            {"id": "anchor", "name": "Anchor", "pool": "hitter", "stats": {"HR": 10, "PA": 550}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = vol.process(raw, league)
        zero = next(r for r in adjusted if r.name == "Zero PA")
        zero_raw = next(r for r in raw if r.name == "Zero PA")
        # Floor is 0.20
        expected = zero_raw.total_value * 0.20
        self.assertAlmostEqual(zero.total_value, expected, places=5)

    def test_sp_uses_sp_baseline(self):
        vol = VolumeMultiplier(hitter_pa=550, sp_ip=180, rp_ip=65)
        league = LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),
            ),
        )
        players = [
            {"id": "sp", "name": "SP", "pool": "pitcher", "positions": ["SP"], "stats": {"K": 200, "IP": 180}},
            {"id": "anchor", "name": "Anchor", "pool": "pitcher", "positions": ["SP"], "stats": {"K": 100, "IP": 90}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = vol.process(raw, league)
        sp = next(r for r in adjusted if r.name == "SP")
        sp_raw = next(r for r in raw if r.name == "SP")
        # 180 IP >= 180 baseline → mult = 1.0
        self.assertAlmostEqual(sp.total_value, sp_raw.total_value, places=5)

    def test_rp_uses_rp_baseline(self):
        vol = VolumeMultiplier(hitter_pa=550, sp_ip=180, rp_ip=65)
        league = LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),
            ),
        )
        players = [
            {"id": "rp", "name": "RP", "pool": "pitcher", "positions": ["RP"], "stats": {"K": 80, "IP": 65}},
            {"id": "anchor", "name": "Anchor", "pool": "pitcher", "positions": ["SP"], "stats": {"K": 100, "IP": 90}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = vol.process(raw, league)
        rp = next(r for r in adjusted if r.name == "RP")
        rp_raw = next(r for r in raw if r.name == "RP")
        # 65 IP >= 65 RP baseline → mult = 1.0
        self.assertAlmostEqual(rp.total_value, rp_raw.total_value, places=5)

    def test_missing_pa_ip_gets_floor(self):
        vol = VolumeMultiplier(hitter_pa=550, sp_ip=180, rp_ip=65)
        league = self._league()
        players = [
            {"id": "noPA", "name": "No PA", "pool": "hitter", "stats": {"HR": 30}},
            {"id": "anchor", "name": "Anchor", "pool": "hitter", "stats": {"HR": 10, "PA": 550}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = vol.process(raw, league)
        noPA = next(r for r in adjusted if r.name == "No PA")
        noPA_raw = next(r for r in raw if r.name == "No PA")
        expected = noPA_raw.total_value * 0.20
        self.assertAlmostEqual(noPA.total_value, expected, places=5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | grep -E "VolumeMultiplier|FAIL|ERROR"`
Expected: ImportError — `VolumeMultiplier` doesn't exist.

- [ ] **Step 3: Implement VolumeMultiplier**

Add to `src/league_values/post_processors.py`:

```python
class VolumeMultiplier:
    """Scale values by playing time: (PA_or_IP / baseline)^0.75.

    Full-time players (PA >= hitter_pa or IP >= sp/rp_ip) get 1.0.
    Partial-season players get a discount. Floor is 0.20.
    RP detection: 'RP' in positions and 'SP' not in positions.
    """

    FLOOR = 0.20
    EXPONENT = 0.75

    def __init__(self, hitter_pa: float = 550, sp_ip: float = 180, rp_ip: float = 65) -> None:
        self.hitter_pa = hitter_pa
        self.sp_ip = sp_ip
        self.rp_ip = rp_ip

    def process(
        self,
        results: list[ValuationResult],
        league: LeagueConfig,
    ) -> list[ValuationResult]:
        return [replace(r, total_value=r.total_value * self._multiplier(r)) for r in results]

    def _multiplier(self, result: ValuationResult) -> float:
        player = result.player
        if player.pool is PlayerPool.HITTER:
            pa = player.stats.get("PA", 0.0) or player.stats.get("AB", 0.0)
            return self._compute(pa, self.hitter_pa)
        elif player.pool is PlayerPool.PITCHER:
            ip = player.stats.get("IP", 0.0)
            is_rp = "RP" in player.positions and "SP" not in player.positions
            baseline = self.rp_ip if is_rp else self.sp_ip
            return self._compute(ip, baseline)
        return 1.0

    def _compute(self, volume: float, baseline: float) -> float:
        if volume <= 0:
            return self.FLOOR
        if volume >= baseline:
            return 1.0
        return max(self.FLOOR, (volume / baseline) ** self.EXPONENT)
```

- [ ] **Step 4: Export VolumeMultiplier from __init__.py**

Add `VolumeMultiplier` to the import from `post_processors` and to `__all__` in `src/league_values/__init__.py`.

- [ ] **Step 5: Run all tests**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: All tests PASS (70 existing + 6 new = 76).

- [ ] **Step 6: Commit**

```bash
git add src/league_values/post_processors.py src/league_values/__init__.py tests/test_post_processors.py
git commit -m "feat: add VolumeMultiplier post-processor — (PA_or_IP/baseline)^0.75"
```

---

### Task 2: RP Pool Split — Add STARTER and RELIEVER to PlayerPool

**Files:**
- Modify: `src/league_values/models.py`
- Test: `tests/test_models.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models.py`:

```python
from league_values.models import CategorySpec, PlayerPool, Direction


class TestPlayerPoolRP(unittest.TestCase):
    def test_starter_and_reliever_exist(self):
        self.assertEqual(PlayerPool.STARTER.value, "starter")
        self.assertEqual(PlayerPool.RELIEVER.value, "reliever")

    def test_pitcher_category_applies_to_starter(self):
        cat = CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K")
        self.assertTrue(cat.applies_to(PlayerPool.STARTER))
        self.assertTrue(cat.applies_to(PlayerPool.RELIEVER))
        self.assertTrue(cat.applies_to(PlayerPool.PITCHER))

    def test_starter_only_category(self):
        cat = CategorySpec(id="QS", label="QS", pool=PlayerPool.STARTER, stat="QS")
        self.assertTrue(cat.applies_to(PlayerPool.STARTER))
        self.assertFalse(cat.applies_to(PlayerPool.RELIEVER))
        self.assertFalse(cat.applies_to(PlayerPool.HITTER))

    def test_reliever_only_category(self):
        cat = CategorySpec(id="SV", label="SV", pool=PlayerPool.RELIEVER, stat="SV")
        self.assertTrue(cat.applies_to(PlayerPool.RELIEVER))
        self.assertFalse(cat.applies_to(PlayerPool.STARTER))
        self.assertFalse(cat.applies_to(PlayerPool.HITTER))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -p "test_models.py" -v`
Expected: AttributeError — `PlayerPool.STARTER` doesn't exist.

- [ ] **Step 3: Add STARTER and RELIEVER to PlayerPool**

In `src/league_values/models.py`, update the enum:

```python
class PlayerPool(str, Enum):
    ALL = "all"
    HITTER = "hitter"
    PITCHER = "pitcher"
    STARTER = "starter"
    RELIEVER = "reliever"
```

- [ ] **Step 4: Update `CategorySpec.applies_to` for pool hierarchy**

`PITCHER` categories should apply to both `STARTER` and `RELIEVER` players. `STARTER`/`RELIEVER` categories only apply to their exact match. Update in `src/league_values/models.py`:

```python
def applies_to(self, player_pool: PlayerPool | str) -> bool:
    player_pool = _enum_value(PlayerPool, player_pool)
    if self.pool is PlayerPool.ALL:
        return True
    if self.pool is player_pool:
        return True
    # PITCHER categories apply to both STARTER and RELIEVER
    if self.pool is PlayerPool.PITCHER and player_pool in (PlayerPool.STARTER, PlayerPool.RELIEVER):
        return True
    return False
```

- [ ] **Step 5: Run all tests**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/league_values/models.py tests/test_models.py
git commit -m "feat: add STARTER and RELIEVER pool types with PITCHER hierarchy"
```

---

### Task 3: RP-Specific Baselines in DD 7x7 Preset

**Files:**
- Modify: `src/league_values/presets.py`
- Modify: `tests/test_dd_preset.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dd_preset.py`:

```python
from league_values.models import PlayerPool


class TestDD7x7RPBaselines(unittest.TestCase):
    def test_dd_7x7_has_rp_baselines(self):
        config = dd_7x7()
        self.assertIn("RP_K", config.league_baselines)
        self.assertIn("RP_ERA", config.league_baselines)
        self.assertIn("RP_WHIP", config.league_baselines)

    def test_dd_7x7_has_reliever_categories(self):
        config = dd_7x7()
        reliever_ids = {c.id for c in config.categories if c.pool is PlayerPool.RELIEVER}
        self.assertIn("RP_K", reliever_ids)
        self.assertIn("RP_SV_HLD", reliever_ids)

    def test_dd_7x7_starter_categories_exclude_sv_hld(self):
        config = dd_7x7()
        starter_ids = {c.id for c in config.categories if c.pool is PlayerPool.STARTER}
        self.assertNotIn("SV_HLD", starter_ids)
        self.assertNotIn("RP_SV_HLD", starter_ids)
        self.assertIn("SP_K", starter_ids)

    def test_dd_7x7_total_categories(self):
        """7 hitting + 6 SP-specific + 6 RP-specific = 19 categories."""
        config = dd_7x7()
        self.assertEqual(len(config.categories), 19)

    def test_dd_7x7_rp_player_valued(self):
        config = dd_7x7()
        players = [
            {
                "id": "closer", "name": "Closer", "pool": "reliever",
                "stats": {"K": 65, "QS": 0, "SV_HLD": 35, "L": 2, "ERA": 2.50, "WHIP": 1.00, "K_BB": 4.0},
            },
            {
                "id": "sp", "name": "Starter", "pool": "starter",
                "stats": {"K": 200, "QS": 18, "SV_HLD": 0, "L": 7, "ERA": 3.20, "WHIP": 1.10, "K_BB": 3.5},
            },
        ]
        results = value_players(players, config)
        self.assertEqual(len(results), 2)
        # Both should have non-zero values
        for r in results:
            self.assertNotEqual(r.total_value, 0.0, f"{r.name} got zero value")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -p "test_dd_preset.py" -v`
Expected: Failures — no RP baselines or reliever categories in DD 7x7 yet.

- [ ] **Step 3: Update DD 7x7 preset with SP/RP split**

Replace the pitching categories in `DD_7X7_CATEGORIES` in `src/league_values/presets.py`. Instead of 7 pitcher categories with `pool=PlayerPool.PITCHER`, split into 6 SP-specific and 6 RP-specific:

```python
DD_7X7_CATEGORIES: tuple[CategorySpec, ...] = (
    # Hitting (7 cats) — unchanged
    CategorySpec(id="R", label="Runs", pool=PlayerPool.HITTER, stat="R", weight=0.12),
    CategorySpec(id="HR", label="Home Runs", pool=PlayerPool.HITTER, stat="HR", weight=0.16),
    CategorySpec(id="RBI", label="RBI", pool=PlayerPool.HITTER, stat="RBI", weight=0.13),
    CategorySpec(id="SB", label="Stolen Bases", pool=PlayerPool.HITTER, stat="SB", weight=0.10),
    CategorySpec(id="AVG", label="Batting Average", pool=PlayerPool.HITTER, stat="AVG", weight=0.14),
    CategorySpec(id="OPS", label="OPS", pool=PlayerPool.HITTER, stat="OPS", weight=0.25),
    CategorySpec(
        id="SO", label="Strikeouts", pool=PlayerPool.HITTER, stat="SO",
        direction=Direction.LOWER_IS_BETTER, weight=0.14,
    ),
    # SP categories (6) — SP weights from DD's valuation_config.py
    CategorySpec(id="SP_K", label="K (SP)", pool=PlayerPool.STARTER, stat="K", weight=0.20),
    CategorySpec(id="SP_QS", label="QS", pool=PlayerPool.STARTER, stat="QS", weight=0.18),
    CategorySpec(
        id="SP_L", label="Losses (SP)", pool=PlayerPool.STARTER, stat="L",
        direction=Direction.LOWER_IS_BETTER, weight=0.08,
    ),
    CategorySpec(
        id="SP_ERA", label="ERA (SP)", pool=PlayerPool.STARTER, stat="ERA",
        direction=Direction.LOWER_IS_BETTER, weight=0.28,
    ),
    CategorySpec(
        id="SP_WHIP", label="WHIP (SP)", pool=PlayerPool.STARTER, stat="WHIP",
        direction=Direction.LOWER_IS_BETTER, weight=0.25,
    ),
    CategorySpec(id="SP_K_BB", label="K/BB (SP)", pool=PlayerPool.STARTER, stat="K_BB", weight=0.15),
    # RP categories (6) — RP weights from DD's valuation_config.py
    CategorySpec(id="RP_K", label="K (RP)", pool=PlayerPool.RELIEVER, stat="K", weight=0.18),
    CategorySpec(id="RP_SV_HLD", label="SV+HLD", pool=PlayerPool.RELIEVER, stat="SV_HLD", weight=0.18),
    CategorySpec(
        id="RP_L", label="Losses (RP)", pool=PlayerPool.RELIEVER, stat="L",
        direction=Direction.LOWER_IS_BETTER, weight=0.06,
    ),
    CategorySpec(
        id="RP_ERA", label="ERA (RP)", pool=PlayerPool.RELIEVER, stat="ERA",
        direction=Direction.LOWER_IS_BETTER, weight=0.24,
    ),
    CategorySpec(
        id="RP_WHIP", label="WHIP (RP)", pool=PlayerPool.RELIEVER, stat="WHIP",
        direction=Direction.LOWER_IS_BETTER, weight=0.22,
    ),
    CategorySpec(id="RP_K_BB", label="K/BB (RP)", pool=PlayerPool.RELIEVER, stat="K_BB", weight=0.12),
)
```

Update `DD_7X7_BASELINES` to include RP-specific baselines:

```python
DD_7X7_BASELINES: dict[str, tuple[float, float]] = {
    # Hitting
    "R": (75.0, 25.0),
    "HR": (22.0, 12.0),
    "RBI": (72.0, 28.0),
    "SB": (12.0, 15.0),
    "AVG": (0.252, 0.028),
    "OPS": (0.720, 0.085),
    "SO": (140.0, 35.0),
    # SP baselines
    "SP_K": (120.0, 49.0),
    "SP_QS": (9.0, 6.0),
    "SP_L": (7.0, 3.0),
    "SP_ERA": (4.13, 1.07),
    "SP_WHIP": (1.26, 0.18),
    "SP_K_BB": (3.17, 1.27),
    # RP baselines (from DD's LEAGUE_AVG/STD_PITCHING_RP)
    "RP_K": (48.0, 26.0),
    "RP_SV_HLD": (11.0, 11.0),
    "RP_L": (3.0, 2.0),
    "RP_ERA": (4.13, 1.80),
    "RP_WHIP": (1.32, 0.29),
    "RP_K_BB": (2.84, 1.39),
}
```

- [ ] **Step 4: Fix existing DD preset tests**

Update `tests/test_dd_preset.py` — the existing tests check for 14 categories and pitcher pool. Update:
- `test_dd_7x7_loads`: change `len(config.categories)` assertion from 14 to 19
- `test_dd_7x7_has_correct_pitching_cats`: update to check for SP_ and RP_ prefixed IDs
- `test_dd_7x7_inverse_cats`: update to include SP_L, SP_ERA, SP_WHIP, RP_L, RP_ERA, RP_WHIP
- `test_dd_7x7_has_league_baselines`: change `"K"` to `"SP_K"` and `"ERA"` to `"SP_ERA"`
- `test_dd_7x7_produces_results`: change player pools from `"pitcher"` to `"starter"` / `"reliever"`

- [ ] **Step 5: Run all tests**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/league_values/presets.py tests/test_dd_preset.py
git commit -m "feat: split DD 7x7 pitching into SP/RP pools with separate baselines"
```

---

### Task 4: Update Integration Tests and DD Comparison

**Files:**
- Modify: `tests/test_integration.py`
- Modify: `tests/test_dd_comparison.py`
- Modify: `tests/dd_test_data.json` (update RP player pools)

- [ ] **Step 1: Update integration test players**

In `tests/test_integration.py`, update the `PLAYERS` list:
- Change Burns (`"pool": "pitcher"`) to `"pool": "starter"`
- Change Clase (`"pool": "pitcher"`) to `"pool": "reliever"`
- Add `"IP"` to pitcher stats so VolumeMultiplier works
- Add `"PA"` to hitter stats

Update the engine instantiation to include `VolumeMultiplier` in the full pipeline test.

- [ ] **Step 2: Update DD comparison test data**

Write a small script or manually update `tests/dd_test_data.json`: for each player where `pool == "pitcher"`, set `pool` to `"starter"` or `"reliever"` based on their positions (RP in positions and SP not → "reliever", else "starter").

Update `tests/test_dd_comparison.py`:
- `to_player_projection()`: map pool correctly (pitcher→starter/reliever based on positions)
- `is_reliever()`: check pool == "reliever" instead of position-based detection
- Update the `dd_7x7()` config references if needed

- [ ] **Step 3: Run all tests**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py tests/test_dd_comparison.py tests/dd_test_data.json
git commit -m "test: update integration and DD comparison for SP/RP pool split + volume multiplier"
```

---

### Task 5: Update Exports & Push

**Files:**
- Modify: `src/league_values/__init__.py` (if not already done in Task 1)

- [ ] **Step 1: Verify all exports**

Ensure `VolumeMultiplier` is in `__init__.py` imports and `__all__`. (Should already be done in Task 1, but verify.)

- [ ] **Step 2: Run full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: All tests PASS (target: ~85+ tests).

- [ ] **Step 3: Push**

```bash
git push origin master
```
