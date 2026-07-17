"""Board Time Machine reader (plan 026): fail-soft contract, quality flags,
aggregate-only consensus, bounded cache. Uses a fixture archive dir (never the
real ~7 MB files) so the suite stays date-stable as the archive grows, and
derives its pre/post dates from the imported epoch so a future re-baseline
does not break the tests."""
import inspect
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from prospects.buys import PROSPECT_BUYS_EPOCH
from web.board_time_machine_store import (
    _CACHE_MAX,
    _ROW_LIMIT,
    EPOCH_DATE,
    BoardTimeMachineStore,
    _consensus,
    nearest_board_date,
)


def _shift(iso: str, days: int) -> str:
    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


PRE_DATE = _shift(EPOCH_DATE, -1)     # pre-baseline side of the epoch
POST_DATE = _shift(EPOCH_DATE, 1)     # clean side
BAD_DATE = _shift(EPOCH_DATE, 2)      # malformed-file date
FIVE_BOARDS = {"fg_ord": 15, "hkb": 8, "pipeline": 3, "pl": 17, "sts": 3}


def _row(rank: int, name: str = "Fixture Player", source_ranks: dict | None = None) -> dict:
    return {
        "rank": rank,
        "name": f"{name} {rank}",
        "role": "hitter",
        "mlbam_id": str(700000 + rank),
        "mlb_team": "SEA",
        "level": "AA",
        "age": 20,
        "positions": ["SS"],
        "score": 60.0 - rank,
        "score_source": "model",
        "confidence": "medium",
        "eta": None,
        "eta_window": "one_to_two_years",
        "dynasty_signal": {},
        "context_only": {"source_ranks": source_ranks if source_ranks is not None else {}},
    }


def _payload(day: str, rows: list[dict], version: str = "9.9.9") -> dict:
    return {
        "board": rows,
        "candidate_count": len(rows),
        "date": day,
        "generated_at": f"{day}T08:00:00",
        "rank_version": version,
        "ranked_count": len(rows),
        "validation": {},
    }


class BoardTimeMachineFixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self._write(PRE_DATE, [_row(1, source_ranks=FIVE_BOARDS), _row(2)])
        self._write(EPOCH_DATE, [_row(1)])
        self._write(POST_DATE, [_row(1, source_ranks=FIVE_BOARDS), _row(2), _row(3)])
        (self.dir / f"{BAD_DATE}.json").write_text("{not valid json", encoding="utf-8")
        self.store = BoardTimeMachineStore(self.dir)

    def _write(self, day: str, rows: list[dict]):
        (self.dir / f"{day}.json").write_text(
            json.dumps(_payload(day, rows)), encoding="utf-8"
        )


class TestAvailableDates(BoardTimeMachineFixture):
    def test_sorted_iso_dates_only(self):
        (self.dir / "junk.json").write_text("{}", encoding="utf-8")
        dates = self.store.available_dates()
        self.assertEqual(dates, sorted([PRE_DATE, EPOCH_DATE, POST_DATE, BAD_DATE]))
        self.assertNotIn("junk", dates)

    def test_malformed_file_still_listed(self):
        # available_dates is stat/stem only BY DESIGN (never loads ~7 MB bodies
        # to list dates); the fail-soft honesty lives in board_for -> None.
        self.assertIn(BAD_DATE, self.store.available_dates())

    def test_cached_on_dir_mtime_and_refreshes(self):
        first = self.store.available_dates()
        self.assertIs(first, self.store.available_dates())  # same-mtime cache hit
        new_day = _shift(EPOCH_DATE, 5)
        self._write(new_day, [_row(1)])
        stamp = self.dir.stat().st_mtime + 10
        os.utime(self.dir, (stamp, stamp))
        self.assertIn(new_day, self.store.available_dates())

    def test_missing_dir_returns_empty(self):
        store = BoardTimeMachineStore(self.dir / "nope")
        self.assertEqual(store.available_dates(), [])


class TestQualityFlags(BoardTimeMachineFixture):
    def test_epoch_derived_from_import_not_hardcoded(self):
        self.assertEqual(EPOCH_DATE, "-".join(PROSPECT_BUYS_EPOCH.split("-")[:3]))
        self.assertRegex(EPOCH_DATE, r"^\d{4}-\d{2}-\d{2}$")

    def test_pre_epoch_is_pre_baseline(self):
        self.assertEqual(self.store.quality_flag(PRE_DATE), "pre-baseline")

    def test_epoch_day_itself_is_clean(self):
        self.assertEqual(self.store.quality_flag(EPOCH_DATE), "clean")

    def test_post_epoch_is_clean(self):
        self.assertEqual(self.store.quality_flag(POST_DATE), "clean")

    def test_absent_date_unavailable(self):
        self.assertEqual(self.store.quality_flag("1999-01-01"), "unavailable")

    def test_junk_shapes_unavailable(self):
        for junk in ("", "not-a-date", "2026/06/20", "../etc/passwd", f"{POST_DATE}/x"):
            self.assertEqual(self.store.quality_flag(junk), "unavailable")


class TestBoardFor(BoardTimeMachineFixture):
    def test_happy_path_view_shape(self):
        view = self.store.board_for(POST_DATE)
        self.assertEqual(view["date"], POST_DATE)
        self.assertEqual(view["rank_version"], "9.9.9")
        self.assertEqual(view["generated_at"], f"{POST_DATE}T08:00:00")
        self.assertEqual(view["quality"], "clean")
        self.assertEqual(view["total_rows"], 3)
        self.assertEqual(len(view["rows"]), 3)
        row = view["rows"][0]
        self.assertEqual(row["rank"], 1)
        self.assertEqual(row["team"], "SEA")       # mapped from mlb_team
        self.assertEqual(row["level"], "AA")
        self.assertEqual(row["score"], 59.0)       # archived score verbatim
        self.assertEqual(row["eta_display"], "~1-2 yr")

    def test_no_per_source_ranks_on_any_row(self):
        view = self.store.board_for(POST_DATE)
        for row in view["rows"]:
            self.assertNotIn("source_ranks", row)
            self.assertNotIn("context_only", row)
            if row["consensus"] is not None:
                self.assertEqual(set(row["consensus"]), {"median", "board_count"})

    def test_quality_pre_baseline_vs_clean(self):
        self.assertEqual(self.store.board_for(PRE_DATE)["quality"], "pre-baseline")
        self.assertEqual(self.store.board_for(EPOCH_DATE)["quality"], "clean")

    def test_missing_date_fails_soft(self):
        self.assertIsNone(self.store.board_for("1999-01-01"))

    def test_malformed_json_fails_soft(self):
        self.assertIsNone(self.store.board_for(BAD_DATE))

    def test_non_dict_payload_fails_soft(self):
        day = _shift(EPOCH_DATE, 6)
        (self.dir / f"{day}.json").write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIsNone(self.store.board_for(day))

    def test_junk_date_never_reaches_filesystem(self):
        for junk in ("", "../secrets", "a/b", f"{POST_DATE}/../x", "not-a-date"):
            self.assertIsNone(self.store.board_for(junk))

    def test_row_limit_bounds_rendered_rows(self):
        store = BoardTimeMachineStore(self.dir, row_limit=2)
        view = store.board_for(POST_DATE)
        self.assertEqual(len(view["rows"]), 2)
        self.assertEqual(view["total_rows"], 3)   # truncation stays disclosed
        self.assertGreater(_ROW_LIMIT, 0)


class TestBoardCache(BoardTimeMachineFixture):
    def test_cache_is_bounded(self):
        days = [_shift(EPOCH_DATE, 10 + i) for i in range(_CACHE_MAX + 3)]
        for day in days:
            self._write(day, [_row(1)])
            self.assertIsNotNone(self.store.board_for(day))
        self.assertLessEqual(len(self.store._board_cache), _CACHE_MAX)

    def test_same_mtime_returns_cached_view(self):
        first = self.store.board_for(POST_DATE)
        self.assertIs(first, self.store.board_for(POST_DATE))

    def test_mtime_change_invalidates(self):
        self.store.board_for(POST_DATE)
        path = self.dir / f"{POST_DATE}.json"
        self._write(POST_DATE, [_row(9)])
        stamp = path.stat().st_mtime + 10
        os.utime(path, (stamp, stamp))
        view = self.store.board_for(POST_DATE)
        self.assertEqual(view["rows"][0]["rank"], 9)


class TestConsensus(unittest.TestCase):
    def test_five_boards_aggregate_median(self):
        self.assertEqual(_consensus(FIVE_BOARDS), {"median": 8, "board_count": 5})

    def test_single_board_is_not_a_consensus(self):
        self.assertIsNone(_consensus({"pl": 17}))

    def test_internal_sources_excluded(self):
        self.assertIsNone(_consensus({"cfr": 4, "milb_perf": 2, "milb_breakout": 1}))
        self.assertEqual(
            _consensus({"cfr": 4000, "fg_ord": 10, "hkb": 20}),
            {"median": 15, "board_count": 2},
        )

    def test_deep_list_ranks_capped(self):
        self.assertIsNone(_consensus({"fg_ord": 601, "hkb": 700}))

    def test_even_count_median_rounds(self):
        self.assertEqual(_consensus({"fg_ord": 10, "hkb": 11}), {"median": 10, "board_count": 2})

    def test_empty_and_none(self):
        self.assertIsNone(_consensus({}))
        self.assertIsNone(_consensus(None))


class TestNearestBoardDate(unittest.TestCase):
    DATES = ["2026-06-13", "2026-06-20", "2026-07-01"]

    def test_before_range(self):
        self.assertEqual(nearest_board_date("2026-06-01", self.DATES), "2026-06-13")

    def test_after_range(self):
        self.assertEqual(nearest_board_date("2027-01-01", self.DATES), "2026-07-01")

    def test_between_picks_closer(self):
        self.assertEqual(nearest_board_date("2026-06-21", self.DATES), "2026-06-20")
        self.assertEqual(nearest_board_date("2026-06-29", self.DATES), "2026-07-01")

    def test_junk_falls_back_to_latest(self):
        self.assertEqual(nearest_board_date("junk", self.DATES), "2026-07-01")
        self.assertEqual(nearest_board_date(None, self.DATES), "2026-07-01")

    def test_empty_dates(self):
        self.assertIsNone(nearest_board_date("2026-06-20", []))


class TestNetworkFree(unittest.TestCase):
    def test_reader_module_is_structurally_network_free(self):
        import web.board_time_machine_store as module

        source = inspect.getsource(module)
        for token in ("urllib", "requests", "http.client", "socket"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
