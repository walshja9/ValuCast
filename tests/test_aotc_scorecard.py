"""Ahead-of-the-Curve scorecard: earliest-call date + consensus catch-up + gate."""
import json

from scripts.build_ahead_of_consensus_scorecard import build_scorecard


def _snapshot(archive_dir, date_str, source_ranks):
    """One dated board snapshot with a single guarded early call (VC #10)."""
    board = {
        "board": [
            {
                "mlbam_id": 1,
                "role": "hitter",
                "name": "Early Call",
                "rank": 10,
                "context_only": {"source_ranks": source_ranks},
            }
        ]
    }
    (archive_dir / f"{date_str}.json").write_text(json.dumps(board), encoding="utf-8")


def test_catch_up_and_earliest_date(tmp_path):
    # Day 1: field has him ~#85 (median of 80/90), VC #10 -> divergence 75, guarded.
    _snapshot(tmp_path, "2026-06-01", {"pipeline": 80, "hkb": 90})
    # Day 3: field moved toward us (median 55). catch_up = 85 - 55 = 30.
    _snapshot(tmp_path, "2026-06-03", {"pipeline": 50, "hkb": 60})

    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-03T00:00:00+00:00")

    assert payload["summary"]["resolved_count"] == 1
    call = payload["calls"][0]
    assert call["ahead_since"] == "2026-06-01"     # earliest guarded date, not day 3
    assert call["consensus_then"] == 85
    assert call["consensus_now"] == 55
    assert call["consensus_catch_up"] == 30
    assert call["moved_toward_valucast"] is True
    assert payload["summary"]["moved_toward_count"] == 1
    # 2-day horizon is far below the publish gate -> number stays withheld.
    assert payload["gate"]["publishable"] is False
    # Independence firewall.
    assert payload["source_policy"]["feeds_model_score"] is False


def test_field_moving_away_is_not_a_catch_up(tmp_path):
    _snapshot(tmp_path, "2026-06-01", {"pipeline": 60, "hkb": 70})   # median 65
    _snapshot(tmp_path, "2026-06-05", {"pipeline": 90, "hkb": 100})  # median 95 -> moved AWAY
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-05T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["consensus_catch_up"] == -30
    assert call["moved_toward_valucast"] is False
    assert payload["summary"]["moved_toward_count"] == 0


def test_empty_archive_is_safe(tmp_path):
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-05T00:00:00+00:00")
    assert payload["status"] == "blocked"
    assert payload["calls"] == []
    assert payload["gate"]["publishable"] is False
