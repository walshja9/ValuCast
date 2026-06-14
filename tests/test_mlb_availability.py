"""Tests for the ValuCast MLB availability contract."""

from mlb.availability import (
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
