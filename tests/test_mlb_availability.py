"""Tests for the ValuCast MLB availability contract."""

from mlb.availability import (
    CACHE_QUERIES_KEEP,
    _prune_stale_queries,
    _transactions_from_cache_or_fetch,
    availability_lookup,
    build_mlb_availability,
)


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
