import json

from prospects.ahead_of_consensus import (
    _public_source_consensus,
    _public_source_ranks,
    build_ahead_of_consensus_report,
)
from scripts.validate_ahead_of_consensus import validate_ahead_of_consensus_report
from web.public_snapshot_models import PublicSnapshotRow


def _row(mlbam_id, name, role, rank, source_ranks, team="BOS"):
    return {
        "mlbam_id": mlbam_id,
        "role": role,
        "name": name,
        "mlb_team": team,
        "rank": rank,
        "context_only": {"source_ranks": source_ranks},
    }


def _rank_payload(rows):
    return {"generated_at": "2026-06-22T00:00:00+00:00", "board": rows}


def _build(tmp_path, rows):
    rank_path = tmp_path / "rank.json"
    rank_path.write_text(json.dumps(_rank_payload(rows)), encoding="utf-8")
    return build_ahead_of_consensus_report(
        rank_path=rank_path,
        generated_at="2026-06-22T00:00:00+00:00",
    )


def _snapshot_row(source_ranks):
    return PublicSnapshotRow(
        id="1",
        name="X",
        player_type="prospect",
        positions=(),
        team="BOS",
        age=21,
        rank=1,
        value=0.0,
        value_scale="dynasty",
        value_source="valucast",
        confidence=None,
        updated_at="2026-06-22",
        mlbam_id="1",
        source_ranks=source_ranks,
    )


def test_consensus_matches_public_snapshot_models():
    # Odd and even board counts both have to match the canonical property.
    for source_ranks in (
        {"pipeline": 8, "hkb": 9, "cfr": 17, "milb_perf": 21, "cfr_raw": 17.0},
        {"pipeline": 90, "hkb": 94, "milb_breakout": 5},
    ):
        public = _public_source_ranks(source_ranks)
        # The proprietary signals (milb_perf, milb_breakout, cfr_raw) drop out.
        assert "milb_perf" not in public
        assert "milb_breakout" not in public
        assert "cfr_raw" not in public
        snapshot_row = _snapshot_row(source_ranks)
        assert _public_source_ranks(source_ranks).keys() == snapshot_row.public_source_ranks.keys()
        assert _public_source_consensus(public) == snapshot_row.public_source_consensus


def test_divergence_sign_is_consensus_minus_valucast(tmp_path):
    # ValuCast #36 vs a public field consensus near ~92 -> a positive early call.
    payload = _build(
        tmp_path,
        [_row(1, "Hector Rodriguez", "hitter", 36, {"pipeline": 90, "hkb": 94})],
    )
    rows = payload["ahead_of_consensus"]
    assert len(rows) == 1
    call = rows[0]
    assert call["consensus_rank"] == 92
    assert call["valucast_rank"] == 36
    assert call["divergence"] == 92 - 36 == 56


def test_deep_single_board_is_excluded(tmp_path):
    # One deep board would imply a +4000 nonsense divergence; MIN_BOARDS kills it.
    payload = _build(
        tmp_path,
        [_row(2, "Deep Single", "pitcher", 166, {"cfr": 4200})],
    )
    assert payload["ahead_of_consensus"] == []
    assert payload["divergence_by_identity"] == {}


def test_two_board_strong_valucast_is_included(tmp_path):
    payload = _build(
        tmp_path,
        [_row(3, "Owen Murphy", "pitcher", 166, {"pipeline": 1000, "hkb": 1042})],
    )
    rows = payload["ahead_of_consensus"]
    assert [row["name"] for row in rows] == ["Owen Murphy"]
    assert rows[0]["board_count"] == 2
    assert rows[0]["divergence"] == 1021 - 166
    # The card badge index carries the same guarded call.
    assert "3_pitcher" in payload["divergence_by_identity"]


def test_no_consensus_row_is_excluded_and_no_badge(tmp_path):
    payload = _build(
        tmp_path,
        [_row(4, "Single Board", "hitter", 50, {"pipeline": 900})],
    )
    assert payload["ahead_of_consensus"] == []
    assert payload["divergence_by_identity"] == {}


def test_deep_valucast_rank_is_excluded(tmp_path):
    # MAX_VALUCAST_RANK guard: a player VC#400 never qualifies even with a gap.
    payload = _build(
        tmp_path,
        [_row(5, "Deep VC", "hitter", 400, {"pipeline": 800, "hkb": 820})],
    )
    assert payload["ahead_of_consensus"] == []


def test_small_divergence_is_excluded(tmp_path):
    # MIN_DIVERGENCE guard: a +10 gap is below the noise floor.
    payload = _build(
        tmp_path,
        [_row(6, "Small Gap", "hitter", 50, {"pipeline": 58, "hkb": 62})],
    )
    assert payload["ahead_of_consensus"] == []


def test_within_role_role_is_preserved(tmp_path):
    payload = _build(
        tmp_path,
        [
            _row(7, "Bat Call", "hitter", 40, {"pipeline": 200, "hkb": 220}),
            _row(8, "Arm Call", "pitcher", 60, {"pipeline": 300, "hkb": 320}),
        ],
    )
    by_role = {row["name"]: row["role"] for row in payload["ahead_of_consensus"]}
    assert by_role == {"Bat Call": "hitter", "Arm Call": "pitcher"}
    for row in payload["ahead_of_consensus"]:
        assert row["role"] in {"hitter", "pitcher"}


def test_source_policy_all_false_and_validator_green(tmp_path):
    payload = _build(
        tmp_path,
        [_row(9, "Owen Murphy", "pitcher", 166, {"pipeline": 1000, "hkb": 1042})],
    )
    policy = payload["source_policy"]
    for flag in (
        "feeds_model_score",
        "feeds_public_rank",
        "feeds_buy_score",
        "dd_values_used",
        "dd_ranks_used",
        "external_rankings_used",
        "market_values_used",
    ):
        assert policy[flag] is False

    artifact_path = tmp_path / "ahead.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    _validated, problems = validate_ahead_of_consensus_report(artifact_path)
    assert problems == []


def test_validator_blocks_score_feeding_flag(tmp_path):
    payload = _build(
        tmp_path,
        [_row(10, "Owen Murphy", "pitcher", 166, {"pipeline": 1000, "hkb": 1042})],
    )
    payload["source_policy"]["external_rankings_used"] = True
    artifact_path = tmp_path / "ahead.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    _payload, problems = validate_ahead_of_consensus_report(artifact_path)
    assert any("external_rankings_used" in problem for problem in problems)
