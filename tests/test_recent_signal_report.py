import json

from prospects.recent_signal import build_recent_signal_report
from scripts.validate_recent_signal_report import validate_recent_signal_report


def _rank_payload(score, rank):
    return {
        "generated_at": "2026-06-16T00:00:00+00:00",
        "board": [
            {
                "mlbam_id": 1,
                "role": "hitter",
                "name": "Mover Bat",
                "mlb_team": "BOS",
                "positions": ["SS"],
                "rank": rank,
                "score": score,
            }
        ],
    }


def test_recent_signal_report_uses_valucast_archives(tmp_path):
    rank_path = tmp_path / "rank.json"
    buy_path = tmp_path / "buys.json"
    rank_archive = tmp_path / "rank_archive"
    buy_archive = tmp_path / "buy_archive"
    rank_archive.mkdir()
    buy_archive.mkdir()
    rank_path.write_text(json.dumps(_rank_payload(45.0, 20)), encoding="utf-8")
    buy_path.write_text(
        json.dumps({
            "generated_at": "2026-06-16T00:00:00+00:00",
            "board": [
                {
                    "mlbam_id": 1,
                    "role": "hitter",
                    "rank": 4,
                    "score": 58.2,
                    "reason": "Still in the buy window",
                    "terms": {"momentum": 0.7},
                }
            ],
        }),
        encoding="utf-8",
    )
    for day, score, rank in (
        ("2026-06-13", 40.0, 32),
        ("2026-06-14", 41.0, 29),
        ("2026-06-15", 43.0, 25),
        ("2026-06-16", 45.0, 20),
    ):
        (rank_archive / f"{day}.json").write_text(
            json.dumps({"date": day, "board": _rank_payload(score, rank)["board"]}),
            encoding="utf-8",
        )
    (buy_archive / "2026-06-16.json").write_text(
        json.dumps({"date": "2026-06-16", "board": []}),
        encoding="utf-8",
    )

    payload = build_recent_signal_report(
        rank_path=rank_path,
        buy_path=buy_path,
        rank_archive_dir=rank_archive,
        buy_archive_dir=buy_archive,
        generated_at="2026-06-16T00:00:00+00:00",
    )

    assert payload["validation"]["ready_for_recent_signal"] is True
    assert payload["signals"][0]["score_delta_3d"] == 5.0
    assert payload["signals"][0]["rank_delta_3d"] == 12
    assert payload["signals"][0]["buy_rank"] == 4
    assert payload["source_policy"]["external_rankings_used"] is False


def test_recent_signal_validator_blocks_score_feeding_flag(tmp_path):
    payload = build_recent_signal_report(generated_at="2026-06-16T00:00:00+00:00")
    payload["source_policy"]["feeds_buy_score"] = True
    artifact_path = tmp_path / "recent.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _payload, problems = validate_recent_signal_report(artifact_path)

    assert any("feeds_buy_score" in problem for problem in problems)
