import inspect

import pytest

import scripts.backfill_extended_prospect_outcomes as backfill
from scripts.backfill_extended_prospect_outcomes import backfill_outcomes


def _prepared():
    return {
        "artifact": "valucast_extended_prospect_history_prepared",
        "mode": "prepare_only",
        "source_policy": {"outcomes_read": False},
        "rows": [
            {"mlbam_id": 1, "role": "hitter", "cohort_year": 2009},
            {"mlbam_id": 2, "role": "pitcher", "cohort_year": 2010},
            {"mlbam_id": 3, "role": "hitter", "cohort_year": 2011},
        ],
    }


def test_backfill_preserves_cached_empty_bust_and_fetches_only_missing():
    calls = []

    def fetcher(mlbam_id, role):
        calls.append((mlbam_id, role))
        return [{"year": 2015, "pa": 200}] if role == "hitter" else []

    result = backfill_outcomes(
        _prepared()["rows"],
        {"1_hitter": []},
        fetcher=fetcher,
        max_workers=1,
    )

    assert calls == [(2, "pitcher"), (3, "hitter")]
    assert result["cache"]["1_hitter"] == []
    assert result["cache"]["2_pitcher"] == []
    assert result["status"] == "ready"
    assert result["remaining"] == []


def test_backfill_fails_closed_on_fetch_failure_without_inventing_bust():
    result = backfill_outcomes(
        _prepared()["rows"],
        {},
        fetcher=lambda *_: None,
        max_workers=1,
    )

    assert result["status"] == "blocked"
    assert result["cache"] == {}
    assert result["remaining"] == ["1_hitter", "2_pitcher", "3_hitter"]


def test_backfill_canonicalizes_cached_and_fetched_team_splits_to_full_seasons():
    def fetcher(_mlbam_id, role):
        if role == "pitcher":
            return [
                {"year": 2016, "ip": 3.2},
                {"year": 2016, "ip": 27.2},
                {"year": 2016, "ip": 31.1},
            ]
        return []

    result = backfill_outcomes(
        _prepared()["rows"],
        {
            "1_hitter": [
                {"year": 2015, "pa": 100},
                {"year": 2015, "pa": 150},
                {"year": 2015, "pa": 250},
            ]
        },
        fetcher=fetcher,
        max_workers=1,
    )

    assert result["cache"]["1_hitter"] == [{"year": 2015, "pa": 250}]
    assert result["cache"]["2_pitcher"] == [{"year": 2016, "ip": 31.1}]


def test_helper_requires_explicit_fetcher_and_module_has_no_file_runner_or_cli():
    assert inspect.signature(backfill_outcomes).parameters["fetcher"].default is inspect.Parameter.empty
    assert not hasattr(backfill, "run_from_files")
    assert not hasattr(backfill, "main")
    source = inspect.getsource(backfill)
    assert "__main__" not in source
    assert "_atomic_json" not in source


def test_helper_cannot_reach_a_default_fetcher():
    with pytest.raises(TypeError, match="fetcher"):
        backfill_outcomes(_prepared()["rows"], {}, max_workers=1)
