"""v1.1 feed fields: coercion, sparkline geometry, card surfaces."""
import unittest

import app as app_module
from web.dynasty_models import DynastyRankingRow
from web.value_spark import build_spark

HX = {"HX-Request": "true"}


def _record(**over):
    base = {
        "id": "dd_prospect_test", "player_type": "prospect", "name": "Test Guy",
        "positions": ["SS"], "mlb_team": "SEA", "age": 20,
        "dynasty_rank": 5, "dynasty_value": 70.0, "status": "minors",
        "mlbam_id": "806954", "level": "MLB", "eta": 2026,
    }
    base.update(over)
    return base


def _row(record):
    return DynastyRankingRow(
        id=record["id"],
        name=record["name"],
        player_type=record["player_type"],
        positions=DynastyRankingRow._normalize_positions(record.get("positions") or []),
        team=record.get("mlb_team", ""),
        age=DynastyRankingRow._coerce_int(record.get("age")),
        dynasty_rank=record["dynasty_rank"],
        dynasty_value=record["dynasty_value"],
        status=record.get("status"),
        mlbam_id=record.get("mlbam_id"),
        level=record.get("level"),
        eta=DynastyRankingRow._coerce_int(record.get("eta")),
        value_history=DynastyRankingRow._coerce_value_history(
            record.get("value_history")
        ),
        mlb_stat_line=DynastyRankingRow._coerce_dict(record.get("mlb_stat_line")),
        stat_line_translated=DynastyRankingRow._coerce_dict(
            record.get("stat_line_translated")
        ),
        combined_season_stat_line=DynastyRankingRow._coerce_dict(
            record.get("combined_season_stat_line")
        ),
        metadata=record,
    )


class TestOptionalFieldCoercion(unittest.TestCase):
    def test_new_fields_default_safely_when_absent(self):
        row = _row(_record())
        self.assertEqual(row.value_history, ())
        self.assertIsNone(row.mlb_stat_line)
        self.assertIsNone(row.stat_line_translated)
        self.assertIsNone(row.combined_season_stat_line)

    def test_value_history_coerces_pairs_and_drops_garbage(self):
        row = _row(_record(value_history=[
            ["2026-05-14", 55.2], ["2026-05-15", "56.1"],
            ["bad-pair"], [None, 1.0], ["2026-05-16", None],
        ]))
        self.assertEqual(row.value_history,
                         (("2026-05-14", 55.2), ("2026-05-15", 56.1)))

    def test_stringly_numbers_coerce(self):
        row = _row(_record(
            eta="2027", age="20", breakout_rank_change="-6"))
        self.assertEqual(row.eta, 2027)
        self.assertEqual(row.age, 20)
        self.assertFalse(hasattr(row, "breakout_rank_change"))
        self.assertEqual(row.metadata["breakout_rank_change"], "-6")

    def test_dict_fields_reject_non_dicts(self):
        row = _row(_record(
            mlb_stat_line=["not", "a", "dict"],
            stat_line_translated="nope",
            combined_season_stat_line="nope",
        ))
        self.assertIsNone(row.mlb_stat_line)
        self.assertIsNone(row.stat_line_translated)
        self.assertIsNone(row.combined_season_stat_line)


class TestBuildSpark(unittest.TestCase):
    def test_geometry_and_delta(self):
        spark = build_spark((("2026-05-14", 50.0), ("2026-05-21", 55.0),
                             ("2026-05-28", 52.5)))
        self.assertEqual(spark["direction"], "up")
        self.assertEqual(spark["delta"], 2.5)
        self.assertEqual(spark["min"], 50.0)
        self.assertEqual(spark["max"], 55.0)
        self.assertEqual(len(spark["points"].split()), 3)
        self.assertEqual(spark["first_date"], "2026-05-14")
        self.assertEqual(spark["last_date"], "2026-05-28")

    def test_flat_series_does_not_divide_by_zero(self):
        spark = build_spark((("2026-05-14", 50.0), ("2026-05-15", 50.0)))
        self.assertEqual(spark["direction"], "flat")

    def test_fewer_than_two_points_is_none(self):
        self.assertIsNone(build_spark(()))
        self.assertIsNone(build_spark((("2026-05-14", 50.0),)))

    def test_window_days_trims_to_recent_points(self):
        pts = (("2026-06-13", 40.0), ("2026-06-25", 50.0),
               ("2026-06-30", 55.0), ("2026-07-04", 52.0))
        spark = build_spark(pts, window_days=7)
        self.assertEqual(spark["first_date"], "2026-06-30")
        self.assertEqual(spark["delta"], -3.0)
        self.assertEqual(spark["window_days"], 4)  # actual span, not the request

    def test_oversized_window_clamps_to_available_history(self):
        # 30d asked, 21d of records: label must show the true span.
        pts = (("2026-06-13", 40.0), ("2026-07-04", 52.0))
        spark = build_spark(pts, window_days=30)
        self.assertEqual(spark["window_days"], 21)

    def test_window_leaving_one_point_returns_none(self):
        pts = (("2026-06-01", 40.0), ("2026-07-04", 52.0))
        self.assertIsNone(build_spark(pts, window_days=7))


class _CardCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()


class TestSparkOnCards(_CardCase):
    def test_dynasty_card_renders_spark_when_history_present(self):
        row = next((r for r in app_module.dd_store.get_all()
                    if len(r.value_history) >= 2), None)
        if row is None:
            self.skipTest("committed feed predates value_history")
        resp = self.client.get(f"/player/{row.id}?mode=dd_dynasty", headers=HX)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"form-curve", resp.data)


class TestCallUpMlbLine(_CardCase):
    def test_mlb_line_absent_for_pure_minors(self):
        row = next(r for r in app_module.dd_store.get_all()
                   if r.is_prospect and r.level not in (None, "MLB"))
        resp = self.client.get(f"/player/{row.id}?mode=dd_dynasty", headers=HX)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"2026 MLB Stats", resp.data)


class TestTranslatedBlock(_CardCase):
    def test_translated_block_renders_when_present(self):
        row = next((r for r in app_module.dd_store.get_all()
                    if r.is_prospect and (r.stat_line_translated or {}).get("stats")),
                   None)
        if row is None:
            self.skipTest("committed feed predates stat_line_translated")
        resp = self.client.get(f"/player/{row.id}?mode=dd_dynasty", headers=HX)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"MLB-Equivalent Rates", resp.data)

    def test_pool_label_carries_combined_line_caveat(self):
        row = next((r for r in app_module.dd_store.get_all()
                    if r.is_prospect and getattr(r, "combined_season_stat_line", None)), None)
        if row is None:
            self.skipTest("feed predates combined_season_stat_line")
        resp = self.client.get(f"/player/{row.id}?mode=dd_dynasty", headers=HX)
        if b"ValuCast hitter pool" in resp.data:
            self.assertIn(b"all levels", resp.data)
            self.assertIn(b"100+ PA", resp.data)
            self.assertIn(b"combined 2026 line", resp.data)


if __name__ == "__main__":
    unittest.main()
