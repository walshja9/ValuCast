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
    # Three boards so it clears the featured floor (the main board).
    payload = _build(
        tmp_path,
        [_row(1, "Hector Rodriguez", "hitter", 36, {"pipeline": 90, "hkb": 94, "sts": 92})],
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


def test_two_board_call_is_thin_not_featured(tmp_path):
    # A 2-board call is guarded (computes a consensus) but too weakly corroborated
    # to feature: it goes to the opt-in thin list, NOT the main board, and gets no
    # featured-only badge.
    payload = _build(
        tmp_path,
        [_row(3, "Owen Murphy", "pitcher", 166, {"pipeline": 250, "hkb": 280})],
    )
    assert payload["ahead_of_consensus"] == []
    thin = payload["ahead_of_consensus_thin"]
    assert [row["name"] for row in thin] == ["Owen Murphy"]
    assert thin[0]["board_count"] == 2
    assert thin[0]["divergence"] == 265 - 166  # median(250, 280) - 166
    assert "3_pitcher" not in payload["divergence_by_identity"]


def test_active_mlb_row_is_not_featured_thin_or_badged(tmp_path):
    # Rookie-retention keeps a call-up RANKED, but "ahead of consensus" is a
    # claim about a minor-leaguer: boards delist call-ups, so the "gap" is an
    # eligibility artifact. A stamped row must vanish from featured, thin, AND
    # the badge map (Guzman case, 7/4).
    row = _row(9, "Retained Callup", "hitter", 15, {"pipeline": 250, "hkb": 280, "sts": 265})
    row["active_mlb_roster"] = True
    payload = _build(tmp_path, [row])
    assert payload["ahead_of_consensus"] == []
    assert payload["ahead_of_consensus_thin"] == []
    assert payload["divergence_by_identity"] == {}
    assert payload["guards"]["excludes_active_mlb_roster"] is True


def test_live_roster_join_excludes_unstamped_row(tmp_path):
    # The committed board artifact can predate the stamp (or a same-day
    # call-up): the live report joins current roster status as a belt.
    roster_path = tmp_path / "roster.json"
    roster_path.write_text(
        json.dumps({"profiles": [{"mlbam_id": 9, "active_mlb_roster": True}]}),
        encoding="utf-8",
    )
    rank_path = tmp_path / "rank.json"
    rank_path.write_text(
        json.dumps(_rank_payload([
            _row(9, "Called Up Today", "hitter", 15, {"pipeline": 250, "hkb": 280, "sts": 265}),
            _row(3, "Owen Murphy", "pitcher", 166, {"pipeline": 250, "hkb": 280, "sts": 265}),
        ])),
        encoding="utf-8",
    )
    payload = build_ahead_of_consensus_report(
        rank_path=rank_path,
        roster_status_path=roster_path,
        generated_at="2026-07-04T00:00:00+00:00",
    )
    assert [row["name"] for row in payload["ahead_of_consensus"]] == ["Owen Murphy"]
    assert "9_hitter" not in payload["divergence_by_identity"]


def test_three_board_call_is_featured(tmp_path):
    payload = _build(
        tmp_path,
        [_row(3, "Owen Murphy", "pitcher", 166, {"pipeline": 250, "hkb": 280, "sts": 265})],
    )
    assert [row["name"] for row in payload["ahead_of_consensus"]] == ["Owen Murphy"]
    assert payload["ahead_of_consensus_thin"] == []
    assert "3_pitcher" in payload["divergence_by_identity"]
    assert payload["guards"]["featured_min_boards"] == 3


def test_boards_beyond_consensus_cap_are_excluded(tmp_path):
    # Deep-list ranks (sts/cfr run thousands deep) past the cap don't count as
    # top-prospect consensus, so a call backed only by capped-out boards drops.
    payload = _build(
        tmp_path,
        [_row(3, "Deep Pair", "pitcher", 166, {"pipeline": 1000, "hkb": 1042})],
    )
    assert payload["ahead_of_consensus"] == []
    assert payload["divergence_by_identity"] == {}


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
            _row(7, "Bat Call", "hitter", 40, {"pipeline": 200, "hkb": 220, "sts": 210}),
            _row(8, "Arm Call", "pitcher", 60, {"pipeline": 280, "hkb": 295, "sts": 288}),
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
