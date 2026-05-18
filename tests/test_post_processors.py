import unittest
from dataclasses import replace

from league_values import (
    CategorySpec,
    LeagueConfig,
    PlayerPool,
    ScoringMode,
    ValuationEngine,
    ValuationResult,
)
from league_values.models import RosterSettings
from league_values.post_processors import PostProcessor, ReplacementLevel, PositionScarcity, AgeCurve


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
        players = [{"id": "dual", "name": "Dual Elig", "pool": "hitter", "positions": ["C", "1B"], "stats": {"HR": 25}}]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = scarcity.process(raw, league)
        self.assertAlmostEqual(adjusted[0].total_value, raw[0].total_value * 1.15, places=5)

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
        self.assertAlmostEqual(pitcher_adj.total_value, pitcher_raw.total_value * 1.30, places=5)

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
        self.assertAlmostEqual(adj_mid.total_value, raw_mid.total_value * 1.50, places=3)
