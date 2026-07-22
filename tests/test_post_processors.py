import unittest
from dataclasses import replace

from league_values import (
    CategorySpec,
    LeagueConfig,
    PlayerPool,
    PlayerProjection,
    ScoringMode,
    ValuationEngine,
    ValuationResult,
)
from league_values.models import RosterSettings
from league_values.post_processors import PostProcessor, ReplacementLevel, PositionScarcity, AgeCurve, VolumeMultiplier


class DoubleValueProcessor:
    """Test processor that doubles total_value."""
    def process(self, results, league):
        return [replace(r, total_value=r.total_value * 2) for r in results]


class AddFiveProcessor:
    """Test processor that adds 5 to total_value."""
    def process(self, results, league):
        return [replace(r, total_value=r.total_value + 5) for r in results]


class TestPostProcessorPipeline(unittest.TestCase):
    def _league(self):
        return LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )

    def _players(self):
        return [
            {"id": "a", "name": "A", "pool": "hitter", "stats": {"HR": 40}},
            {"id": "b", "name": "B", "pool": "hitter", "stats": {"HR": 10}},
        ]

    def test_engine_without_processors_works(self):
        engine = ValuationEngine()
        results = engine.value_players(self._players(), self._league())
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].name, "A")

    def test_engine_with_one_processor(self):
        engine = ValuationEngine(post_processors=[DoubleValueProcessor()])
        results = engine.value_players(self._players(), self._league())
        self.assertAlmostEqual(results[0].total_value, 2.0, places=3)
        self.assertAlmostEqual(results[1].total_value, -2.0, places=3)

    def test_processors_compose_in_order(self):
        # Double first, then add 5: A = 1.0 * 2 + 5 = 7.0
        engine = ValuationEngine(post_processors=[DoubleValueProcessor(), AddFiveProcessor()])
        results = engine.value_players(self._players(), self._league())
        self.assertAlmostEqual(results[0].total_value, 7.0, places=3)
        self.assertAlmostEqual(results[1].total_value, 3.0, places=3)

    def test_processors_re_sort_results(self):
        class FlipProcessor:
            def process(self, results, league):
                return [replace(r, total_value=-r.total_value) for r in results]

        engine = ValuationEngine(post_processors=[FlipProcessor()])
        results = engine.value_players(self._players(), self._league())
        self.assertEqual(results[0].name, "B")


class TestReplacementLevel(unittest.TestCase):
    def test_replacement_subtracts_baseline(self):
        roster = RosterSettings(
            teams=2, roster_size=3,
            positions={"1B": 1, "SP": 1}, bench=1,
        )
        league = LeagueConfig(
            name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),),
            roster=roster,
        )
        players = [
            {"id": "h1", "name": "Star", "pool": "hitter", "positions": ["1B"], "stats": {"HR": 40}},
            {"id": "h2", "name": "Good", "pool": "hitter", "positions": ["1B"], "stats": {"HR": 30}},
            {"id": "h3", "name": "Avg", "pool": "hitter", "positions": ["1B"], "stats": {"HR": 20}},
            {"id": "h4", "name": "Scrub", "pool": "hitter", "positions": ["1B"], "stats": {"HR": 10}},
        ]
        engine = ValuationEngine()
        raw_results = engine.value_players(players, league)
        processor = ReplacementLevel()
        adjusted = processor.process(raw_results, league)
        star = next(r for r in adjusted if r.name == "Star")
        scrub = next(r for r in adjusted if r.name == "Scrub")
        self.assertGreater(star.total_value, 0)
        self.assertLessEqual(scrub.total_value, 0.01)

    def test_replacement_no_roster_returns_unchanged(self):
        league = LeagueConfig(
            name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),),
        )
        players = [{"id": "a", "name": "A", "pool": "hitter", "stats": {"HR": 30}}]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        processor = ReplacementLevel()
        adjusted = processor.process(raw, league)
        self.assertAlmostEqual(raw[0].total_value, adjusted[0].total_value)


class TestPositionScarcity(unittest.TestCase):
    def test_scarce_position_gets_premium(self):
        scarcity = PositionScarcity(multipliers={"C": 1.15, "1B": 0.90, "OF": 1.00})
        league = LeagueConfig(name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),))
        # Anchor player gives the pool non-zero spread so C/1B get non-zero raw values
        players = [
            {"id": "c", "name": "Catcher", "pool": "hitter", "positions": ["C"], "stats": {"HR": 25}},
            {"id": "1b", "name": "First Base", "pool": "hitter", "positions": ["1B"], "stats": {"HR": 25}},
            {"id": "anchor", "name": "Anchor", "pool": "hitter", "positions": ["OF"], "stats": {"HR": 10}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = scarcity.process(raw, league)
        catcher = next(r for r in adjusted if r.name == "Catcher")
        first_base = next(r for r in adjusted if r.name == "First Base")
        self.assertGreater(catcher.total_value, first_base.total_value)

    def test_multi_position_uses_best(self):
        scarcity = PositionScarcity(multipliers={"C": 1.15, "1B": 0.90})
        league = LeagueConfig(name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),))
        # Anchor pins the pool floor so the dual-eligible player sits above it and
        # the best (C=1.15) multiplier is applied on the above-floor scale.
        players = [
            {"id": "dual", "name": "Dual Elig", "pool": "hitter", "positions": ["C", "1B"], "stats": {"HR": 25}},
            {"id": "anchor", "name": "Anchor", "pool": "hitter", "positions": ["OF"], "stats": {"HR": 10}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = scarcity.process(raw, league)
        dual_raw = next(r for r in raw if r.name == "Dual Elig")
        dual_adj = next(r for r in adjusted if r.name == "Dual Elig")
        # New contract: multiply on the above-floor scale (floor = pool min).
        baseline = min(r.total_value for r in raw)
        expected = baseline + 1.15 * (dual_raw.total_value - baseline)
        self.assertAlmostEqual(dual_adj.total_value, expected, places=5)

    def test_pitcher_positions(self):
        scarcity = PositionScarcity(multipliers={"SP": 1.00, "RP": 0.55})
        league = LeagueConfig(name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),))
        # Anchor player gives the pool non-zero spread so SP/RP get non-zero raw values
        players = [
            {"id": "sp", "name": "Starter", "pool": "pitcher", "positions": ["SP"], "stats": {"K": 200}},
            {"id": "rp", "name": "Reliever", "pool": "pitcher", "positions": ["RP"], "stats": {"K": 200}},
            {"id": "anchor", "name": "Anchor", "pool": "pitcher", "positions": ["SP"], "stats": {"K": 80}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = scarcity.process(raw, league)
        sp = next(r for r in adjusted if r.name == "Starter")
        rp = next(r for r in adjusted if r.name == "Reliever")
        self.assertGreater(sp.total_value, rp.total_value)

    def test_no_positions_uses_default_1(self):
        scarcity = PositionScarcity(multipliers={"C": 1.15})
        league = LeagueConfig(name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),))
        players = [{"id": "np", "name": "No Pos", "pool": "hitter", "positions": [], "stats": {"HR": 25}}]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = scarcity.process(raw, league)
        self.assertAlmostEqual(adjusted[0].total_value, raw[0].total_value)


class TestAgeCurve(unittest.TestCase):
    def test_young_player_boosted(self):
        curve = AgeCurve(
            hitter_curve={22: 1.65, 27: 1.25, 32: 0.87},
            pitcher_curve={22: 1.50, 27: 1.15, 32: 0.78},
        )
        league = LeagueConfig(name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),))
        # Need 3+ players for non-zero z-scores
        players = [
            {"id": "young", "name": "Young", "pool": "hitter", "stats": {"HR": 30}, "metadata": {"age": 22}},
            {"id": "old", "name": "Old", "pool": "hitter", "stats": {"HR": 30}, "metadata": {"age": 32}},
            {"id": "anchor", "name": "Anchor", "pool": "hitter", "stats": {"HR": 10}, "metadata": {"age": 27}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = curve.process(raw, league)
        young = next(r for r in adjusted if r.name == "Young")
        old = next(r for r in adjusted if r.name == "Old")
        self.assertGreater(young.total_value, old.total_value)

    def test_pitcher_uses_pitcher_curve(self):
        curve = AgeCurve(hitter_curve={25: 1.50}, pitcher_curve={25: 1.30})
        league = LeagueConfig(name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),))
        players = [
            {"id": "p1", "name": "Pitcher", "pool": "pitcher", "stats": {"K": 200}, "metadata": {"age": 25}},
            {"id": "p2", "name": "Anchor", "pool": "pitcher", "stats": {"K": 100}, "metadata": {"age": 25}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = curve.process(raw, league)
        pitcher_raw = next(r for r in raw if r.name == "Pitcher")
        pitcher_adj = next(r for r in adjusted if r.name == "Pitcher")
        # New contract: multiply on the above-floor scale (floor = pool min).
        baseline = min(r.total_value for r in raw)
        expected = baseline + 1.30 * (pitcher_raw.total_value - baseline)
        self.assertAlmostEqual(pitcher_adj.total_value, expected, places=5)

    def test_missing_age_uses_multiplier_1(self):
        curve = AgeCurve(hitter_curve={25: 1.50}, pitcher_curve={25: 1.30})
        league = LeagueConfig(name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),))
        players = [
            {"id": "no_age", "name": "No Age", "pool": "hitter", "stats": {"HR": 25}},
            {"id": "anchor", "name": "Anchor", "pool": "hitter", "stats": {"HR": 10}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = curve.process(raw, league)
        raw_noage = next(r for r in raw if r.name == "No Age")
        adj_noage = next(r for r in adjusted if r.name == "No Age")
        self.assertAlmostEqual(adj_noage.total_value, raw_noage.total_value)

    def test_interpolates_between_ages(self):
        # 22→1.60, 24→1.40 → age 23 should be 1.50
        curve = AgeCurve(hitter_curve={22: 1.60, 24: 1.40}, pitcher_curve={})
        league = LeagueConfig(name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),))
        players = [
            {"id": "mid", "name": "Mid", "pool": "hitter", "stats": {"HR": 30}, "metadata": {"age": 23}},
            {"id": "anchor", "name": "Anchor", "pool": "hitter", "stats": {"HR": 10}, "metadata": {"age": 23}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = curve.process(raw, league)
        raw_mid = next(r for r in raw if r.name == "Mid")
        adj_mid = next(r for r in adjusted if r.name == "Mid")
        # New contract: multiply on the above-floor scale (floor = pool min).
        baseline = min(r.total_value for r in raw)
        expected = baseline + 1.50 * (raw_mid.total_value - baseline)
        self.assertAlmostEqual(adj_mid.total_value, expected, places=3)


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
        # New contract: floor multiplier applied on the above-floor scale.
        baseline = min(r.total_value for r in raw)
        expected = baseline + 0.20 * (zero_raw.total_value - baseline)
        self.assertAlmostEqual(zero.total_value, expected, places=5)

    def test_sp_uses_sp_baseline(self):
        vol = VolumeMultiplier(hitter_pa=550, sp_ip=180, rp_ip=65)
        league = LeagueConfig(
            name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),),
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
        self.assertAlmostEqual(sp.total_value, sp_raw.total_value, places=5)

    def test_rp_uses_rp_baseline(self):
        vol = VolumeMultiplier(hitter_pa=550, sp_ip=180, rp_ip=65)
        league = LeagueConfig(
            name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),),
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
        # New contract: floor multiplier applied on the above-floor scale.
        baseline = min(r.total_value for r in raw)
        expected = baseline + 0.20 * (noPA_raw.total_value - baseline)
        self.assertAlmostEqual(noPA.total_value, expected, places=5)


class TestAgeCurvePitcherPool(unittest.TestCase):
    def test_starter_uses_pitcher_curve(self):
        """STARTER pool players should use pitcher curve, not hitter curve."""
        hitter_curve = {25: 1.1, 30: 1.0, 35: 0.8}
        pitcher_curve = {25: 1.05, 30: 1.0, 35: 0.7}
        ac = AgeCurve(hitter_curve, pitcher_curve)

        league = LeagueConfig(
            name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),),
        )
        players = [
            {"id": "sp1", "name": "Young SP", "pool": "starter",
             "stats": {"K": 200}, "metadata": {"age": 35}},
            {"id": "sp2", "name": "Anchor SP", "pool": "starter",
             "stats": {"K": 100}, "metadata": {"age": 35}},
        ]
        results = ValuationEngine().value_players(players, league)
        raw_sp1 = next(r for r in results if r.name == "Young SP")
        adjusted = ac.process(results, league)
        adj_sp1 = next(r for r in adjusted if r.name == "Young SP")
        # pitcher_curve age=35 → 0.7; hitter_curve age=35 → 0.8; values must differ.
        # New contract: multiply on the above-floor scale (floor = pool min).
        baseline = min(r.total_value for r in results)
        expected = baseline + 0.7 * (raw_sp1.total_value - baseline)
        self.assertAlmostEqual(adj_sp1.total_value, expected, places=3)

    def test_reliever_uses_pitcher_curve(self):
        """RELIEVER pool players should use pitcher curve, not hitter curve."""
        hitter_curve = {25: 1.1, 30: 1.0, 35: 0.8}
        pitcher_curve = {25: 1.05, 30: 1.0, 35: 0.7}
        ac = AgeCurve(hitter_curve, pitcher_curve)

        league = LeagueConfig(
            name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="SV", label="SV", pool=PlayerPool.PITCHER, stat="SV"),),
        )
        players = [
            {"id": "rp1", "name": "Old RP", "pool": "reliever",
             "stats": {"SV": 30}, "metadata": {"age": 35}},
            {"id": "rp2", "name": "Anchor RP", "pool": "reliever",
             "stats": {"SV": 10}, "metadata": {"age": 35}},
        ]
        results = ValuationEngine().value_players(players, league)
        raw_rp1 = next(r for r in results if r.name == "Old RP")
        adjusted = ac.process(results, league)
        adj_rp1 = next(r for r in adjusted if r.name == "Old RP")
        # pitcher_curve age=35 → 0.7; hitter_curve age=35 → 0.8; values must differ.
        # New contract: multiply on the above-floor scale (floor = pool min).
        baseline = min(r.total_value for r in results)
        expected = baseline + 0.7 * (raw_rp1.total_value - baseline)
        self.assertAlmostEqual(adj_rp1.total_value, expected, places=3)


class TestVolumeMultiplierPools(unittest.TestCase):
    """Verify VolumeMultiplier works with STARTER and RELIEVER pool types."""

    def _make_result(self, pool, positions, stats, total_value=10.0, pid="1"):
        player = PlayerProjection(
            id=pid, name="Test" + pid, pool=pool, positions=positions, stats=stats,
        )
        return ValuationResult(
            player=player, total_value=total_value, raw_values={}, z_scores={}, category_values={},
        )

    def _floor(self, pool, positions, stats):
        # Full-volume anchor pinned at total_value 0.0 so the pool floor is 0
        # and f(v) = 0 + mult*(v - 0) = mult*v, isolating the multiplier.
        return self._make_result(pool, positions, stats, total_value=0.0, pid="floor")

    def test_starter_pool_uses_sp_baseline(self):
        vm = VolumeMultiplier()
        result = self._make_result("starter", ("SP",), {"IP": 90.0})
        floor = self._floor("starter", ("SP",), {"IP": 180.0})
        processed = vm.process([result, floor], LeagueConfig(name="t", scoring_mode="categories", categories=(
            CategorySpec(id="K", label="K", pool="pitcher", stat="K"),
        )))
        target = next(r for r in processed if r.player.id == "1")
        # 90/180 = 0.5, ^0.75 ≈ 0.5946; floor at 0 → f(v)=mult*v
        self.assertAlmostEqual(target.total_value, 10.0 * (90 / 180) ** 0.75, places=2)

    def test_reliever_pool_uses_rp_baseline(self):
        vm = VolumeMultiplier()
        result = self._make_result("reliever", ("RP",), {"IP": 65.0})
        floor = self._floor("reliever", ("RP",), {"IP": 65.0})
        processed = vm.process([result, floor], LeagueConfig(name="t", scoring_mode="categories", categories=(
            CategorySpec(id="K", label="K", pool="pitcher", stat="K"),
        )))
        target = next(r for r in processed if r.player.id == "1")
        # 65/65 = 1.0
        self.assertAlmostEqual(target.total_value, 10.0, places=2)

    def test_reliever_pool_partial_ip(self):
        vm = VolumeMultiplier()
        result = self._make_result("reliever", ("RP",), {"IP": 30.0})
        floor = self._floor("reliever", ("RP",), {"IP": 65.0})
        processed = vm.process([result, floor], LeagueConfig(name="t", scoring_mode="categories", categories=(
            CategorySpec(id="K", label="K", pool="pitcher", stat="K"),
        )))
        target = next(r for r in processed if r.player.id == "1")
        # 30/65 ≈ 0.4615, ^0.75 ≈ 0.5329; floor at 0 → f(v)=mult*v
        self.assertAlmostEqual(target.total_value, 10.0 * (30 / 65) ** 0.75, places=2)


class TestMultiplierSignCorrectness(unittest.TestCase):
    """Regression: multiplicative processors must be monotone on SIGNED values.

    These pin the two direction bugs the shift-onto-above-replacement fix
    addresses. Multiplying a signed z-sum directly ranked below-average
    low-volume players TOO HIGH and mediocre young players TOO LOW.
    """

    def _mk(self, name, total_value, positions=(), pool="hitter", metadata=None, stats=None):
        player = PlayerProjection(
            id=name, name=name, pool=pool, positions=tuple(positions),
            stats=stats or {}, metadata=metadata or {},
        )
        return ValuationResult(
            player=player, total_value=total_value,
            raw_values={}, z_scores={}, category_values={},
        )

    def _league(self):
        return LeagueConfig(name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),))

    def test_below_average_low_volume_ranks_worse_than_high_volume(self):
        # Requirement (a): a below-average (negative value) player with LOW
        # volume must rank WORSE than the SAME player with more volume.
        # Anchor pins the pool floor so the below-avg player sits above it.
        vol = VolumeMultiplier(hitter_pa=550)
        anchor = self._mk("Floor", -5.0, stats={"PA": 550})
        low_vol = self._mk("LowVol", -2.0, stats={"PA": 150})   # PA=150 -> heavy discount
        high_vol = self._mk("HighVol", -2.0, stats={"PA": 500})  # PA=500 -> mild discount

        out = vol.process([anchor, low_vol, high_vol], self._league())
        low = next(r for r in out if r.name == "LowVol").total_value
        high = next(r for r in out if r.name == "HighVol").total_value
        self.assertLess(low, high)

    def test_mediocre_young_not_ranked_below_identical_old(self):
        # Requirement (b): a mediocre (below-average) 22yo must NOT rank below
        # an identical-value 30yo once the youth boost is applied.
        curve = AgeCurve(
            hitter_curve={22: 1.65, 30: 0.97},
            pitcher_curve={22: 1.50, 30: 0.88},
        )
        anchor = self._mk("Floor", -6.0, metadata={"age": 30})
        young = self._mk("Young22", -2.0, metadata={"age": 22})
        old = self._mk("Old30", -2.0, metadata={"age": 30})

        out = curve.process([anchor, young, old], self._league())
        y = next(r for r in out if r.name == "Young22").total_value
        o = next(r for r in out if r.name == "Old30").total_value
        self.assertGreater(y, o)

    def test_full_volume_and_peak_age_unchanged(self):
        # Output scale preserved: a player at multiplier 1.0 (full volume,
        # peak-age boost of exactly 1.0) is untouched regardless of floor.
        vol = VolumeMultiplier(hitter_pa=550)
        anchor = self._mk("Floor", -3.0, stats={"PA": 550})
        full = self._mk("Full", 4.0, stats={"PA": 600})
        out = vol.process([anchor, full], self._league())
        self.assertAlmostEqual(next(r for r in out if r.name == "Full").total_value, 4.0, places=6)

    def test_scarcity_premium_does_not_invert_negative_values(self):
        # Requirement (c): a below-average (negative value) player at a SCARCE
        # position (premium multiplier > 1) must rank ABOVE the identical-value
        # player at a discounted position -- never below it. A raw signed
        # multiply pushes the scarce player MORE negative (worse), inverting the
        # intended premium; the above-floor shift keeps it monotone.
        scarcity = PositionScarcity(multipliers={"C": 1.20, "1B": 0.85})
        anchor = self._mk("Floor", -6.0, positions=("OF",))
        scarce = self._mk("Catcher", -2.0, positions=("C",))
        deep = self._mk("FirstBase", -2.0, positions=("1B",))

        out = scarcity.process([anchor, scarce, deep], self._league())
        c = next(r for r in out if r.name == "Catcher").total_value
        fb = next(r for r in out if r.name == "FirstBase").total_value
        self.assertGreater(c, fb)
        # And the raw signed multiply WOULD have inverted it (sanity on the trap):
        self.assertLess(-2.0 * 1.20, -2.0 * 0.85)

    def test_scarcity_neutral_multiplier_unchanged(self):
        # A multiplier of exactly 1.0 (no scarcity signal) leaves the value
        # untouched regardless of the pool floor.
        scarcity = PositionScarcity(multipliers={"C": 1.20})
        anchor = self._mk("Floor", -3.0, positions=("C",))
        neutral = self._mk("Neutral", 4.0, positions=("OF",))  # OF not in map -> 1.0
        out = scarcity.process([anchor, neutral], self._league())
        self.assertAlmostEqual(next(r for r in out if r.name == "Neutral").total_value, 4.0, places=6)
