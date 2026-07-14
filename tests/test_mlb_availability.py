"""Tests for the ValuCast MLB availability contract."""

import json

import pytest

from mlb.availability import (
    CACHE_QUERIES_KEEP,
    _check_transaction_count_ratio_guard,
    _prune_stale_queries,
    _transactions_from_cache_or_fetch,
    availability_lookup,
    build_mlb_availability,
)
from scripts.validate_mlb_availability import validate_mlb_availability


def _projection(mlbam_id=101, name="Player One"):
    return {
        "id": f"mlbam_{mlbam_id}",
        "name": name,
        "pool": "hitter",
        "stats": {"PA": 600},
        "metadata": {"mlbam_id": str(mlbam_id)},
    }


def _tx(
    tx_id,
    mlbam_id,
    name,
    description,
    effective_date,
    type_code="SC",
    type_desc="Status Change",
):
    return {
        "id": tx_id,
        "date": effective_date,
        "effectiveDate": effective_date,
        "typeCode": type_code,
        "typeDesc": type_desc,
        "person": {"id": mlbam_id, "fullName": name},
        "toTeam": {"abbreviation": "BOS", "name": "Boston Red Sox"},
        "description": description,
    }


def test_mlb_availability_marks_latest_injured_list_status_by_mlbam():
    payload = build_mlb_availability(
        [_projection(101, "Starter One")],
        generated_at="2026-06-14T12:00:00Z",
        transactions=[
            _tx(
                1,
                101,
                "Starter One",
                "Boston Red Sox placed RHP Starter One on the 15-day injured list.",
                "2026-05-01",
            )
        ],
    )

    profile = availability_lookup(payload)["101"]
    assert profile["status"] == "injured"
    assert profile["active_injury_risk"] is True
    assert profile["list_type"] == "15-day injured list"
    assert payload["validation"]["risk_profile_count"] == 1
    assert payload["source_policy"]["name_matching_used"] is False


def test_mlb_availability_activation_clears_previous_injured_status():
    payload = build_mlb_availability(
        [_projection(101, "Starter One")],
        generated_at="2026-06-14T12:00:00Z",
        transactions=[
            _tx(
                1,
                101,
                "Starter One",
                "Boston Red Sox placed RHP Starter One on the 15-day injured list.",
                "2026-05-01",
            ),
            _tx(
                2,
                101,
                "Starter One",
                "Boston Red Sox activated RHP Starter One from the 15-day injured list.",
                "2026-05-20",
            ),
        ],
    )

    profile = availability_lookup(payload)["101"]
    assert profile["status"] == "available"
    assert profile["active_injury_risk"] is False
    assert payload["validation"]["risk_profile_count"] == 0
    assert payload["validation"]["available_after_il_count"] == 1


def test_mlb_availability_rehab_assignment_remains_active_risk_until_activation():
    payload = build_mlb_availability(
        [_projection(101, "Starter One")],
        generated_at="2026-06-14T12:00:00Z",
        transactions=[
            _tx(
                1,
                101,
                "Starter One",
                "Boston Red Sox placed RHP Starter One on the 15-day injured list.",
                "2026-05-01",
            ),
            _tx(
                2,
                101,
                "Starter One",
                "Boston Red Sox sent RHP Starter One on a rehab assignment to Worcester Red Sox.",
                "2026-05-20",
                type_code="ASG",
                type_desc="Assigned",
            ),
        ],
    )

    profile = availability_lookup(payload)["101"]
    assert profile["status"] == "rehab"
    assert profile["active_injury_risk"] is True
    assert payload["validation"]["rehab_count"] == 1


def test_mlb_availability_ignores_untracked_transaction_identities():
    payload = build_mlb_availability(
        [_projection(101, "Starter One")],
        generated_at="2026-06-14T12:00:00Z",
        transactions=[
            _tx(
                1,
                999,
                "Other Player",
                "Boston Red Sox placed RHP Other Player on the 15-day injured list.",
                "2026-05-01",
            )
        ],
    )

    assert availability_lookup(payload) == {}
    assert payload["validation"]["profile_count"] == 0


# 7/7: the query cache key includes end_date, and production always fetches a
# fixed season-start through today -- so every daily run added a fresh,
# near-duplicate, ever-larger entry and nothing ever pruned the old ones. Grew
# to 100MB+ over ~23 days and broke the daily refresh's GitHub push 3 runs
# straight before this was caught.
def test_prune_stale_queries_keeps_only_the_most_recent_entries():
    queries = {
        f"2026-03-01:2026-06-{day:02d}:sportId=1": {
            "fetched_at": f"2026-06-{day:02d}T12:00:00Z",
            "end_date": f"2026-06-{day:02d}",
            "transactions": [{"id": day}],
        }
        for day in range(1, 21)
    }
    assert len(queries) == 20

    _prune_stale_queries(queries)

    assert len(queries) == CACHE_QUERIES_KEEP
    kept_days = sorted(v["end_date"] for v in queries.values())
    assert kept_days == [f"2026-06-{day:02d}" for day in range(21 - CACHE_QUERIES_KEEP, 21)]


def test_prune_stale_queries_is_a_noop_under_the_keep_limit():
    queries = {"only-key": {"fetched_at": "2026-06-01T00:00:00Z", "transactions": []}}
    _prune_stale_queries(queries)
    assert len(queries) == 1


def test_transactions_from_cache_or_fetch_prunes_after_each_new_fetch():
    cache = {
        "queries": {
            f"2026-03-01:2026-06-{day:02d}:sportId=1": {
                "fetched_at": f"2026-06-{day:02d}T12:00:00Z",
                "end_date": f"2026-06-{day:02d}",
                "transactions": [],
            }
            for day in range(1, 11)
        }
    }

    _transactions_from_cache_or_fetch(
        start_date="2026-03-01",
        end_date="2026-06-11",
        cache=cache,
        fetcher=lambda start, end: [{"id": 1}],
        fetched_at="2026-06-11T12:00:00Z",
    )

    assert len(cache["queries"]) == CACHE_QUERIES_KEEP


# 7/13: build-chain audit F4 -- transaction_count only checked "<= 0", so a
# feed that silently halves still validates clean and overwrites a good
# artifact. Same-season day-over-day drop >10% must refuse to overwrite.
def _availability_payload(season, transaction_count, artifact="valucast_mlb_availability"):
    return {
        "artifact": artifact,
        "season": season,
        "validation": {"transaction_count": transaction_count},
    }


def test_transaction_count_ratio_guard_raises_on_same_season_halving(tmp_path):
    artifact_path = tmp_path / "valucast_mlb_availability.json"
    artifact_path.write_text(
        json.dumps(_availability_payload(2026, 8000)), encoding="utf-8"
    )
    new_payload = _availability_payload(2026, 4000)

    with pytest.raises(RuntimeError, match="4000.*8000|transaction_count"):
        _check_transaction_count_ratio_guard(new_payload, artifact_path)


def test_transaction_count_ratio_guard_allows_missing_or_different_season(tmp_path):
    artifact_path = tmp_path / "valucast_mlb_availability.json"
    new_payload = _availability_payload(2026, 4000)

    # No prior artifact on disk yet.
    _check_transaction_count_ratio_guard(new_payload, artifact_path)

    # Prior artifact exists but is a different season (rollover) -- no raise.
    artifact_path.write_text(
        json.dumps(_availability_payload(2025, 8000)), encoding="utf-8"
    )
    _check_transaction_count_ratio_guard(new_payload, artifact_path)


def test_transaction_count_ratio_guard_escape_hatch_env_var(tmp_path, monkeypatch):
    artifact_path = tmp_path / "valucast_mlb_availability.json"
    artifact_path.write_text(
        json.dumps(_availability_payload(2026, 8000)), encoding="utf-8"
    )
    new_payload = _availability_payload(2026, 4000)

    monkeypatch.setenv("VALUCAST_SKIP_AVAILABILITY_RATIO_GUARD", "1")
    _check_transaction_count_ratio_guard(new_payload, artifact_path)


def test_validate_mlb_availability_flags_degraded_transaction_count(tmp_path):
    path = tmp_path / "valucast_mlb_availability.json"
    payload = {
        "artifact": "valucast_mlb_availability",
        "generated_at": "2026-06-14T12:00:00Z",
        "source_policy": {
            "kind": "official_mlb_transaction_availability",
            "name_matching_used": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
            "public_prospect_ranks_used": False,
            "official_mlb_transactions_used": True,
        },
        "validation": {
            "ready_for_mlb_dynasty_layer": True,
            "duplicate_identity_count": 0,
            "transaction_count": 50,
        },
        "profiles": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    problems = validate_mlb_availability(path)

    assert any("transaction_count 50" in problem for problem in problems)
