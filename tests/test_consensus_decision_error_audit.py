import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.audit_consensus_decisions import (
    age_bin,
    availability_bin,
    build_audit,
    confidence_bin,
    coverage_bin,
    gap_bin,
    level_bin,
    rank_bin,
    reliability_bin,
    sample_bin,
    wilson_interval,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _call(
    mlbam_id: int,
    role: str,
    status: str,
    *,
    days: int = 20,
    ahead_since: str = "2026-06-01",
    initial_gap: int = 75,
    consensus_then: int = 100,
) -> dict:
    return {
        "identity_key": f"{mlbam_id}_{role}",
        "name": f"Player {mlbam_id}",
        "status": status,
        "days_tracked": days,
        "ahead_since": ahead_since,
        "initial_gap": initial_gap,
        "consensus_then": consensus_then,
    }


def _row(
    mlbam_id: int,
    role: str,
    *,
    rank: int,
    age: int,
    level: str,
    sample: float,
    confidence: str,
    reliability: float,
    availability: str,
    score_source: str = "prospect_model_v0_6",
) -> dict:
    return {
        "mlbam_id": mlbam_id,
        "name": f"Player {mlbam_id}",
        "role": role,
        "rank": rank,
        "age": age,
        "level": level,
        "confidence": confidence,
        "score_source": score_source,
        "components": {
            "sample_reliability": reliability,
            "availability": {"status": availability, "sample": sample},
        },
        "context_only": {
            "stat_line_sample": sample,
            "source_ranks": {"pipeline": 80, "hkb": 100, "sts": 120},
        },
    }


def _fixture_inputs(tmp_path: Path) -> tuple[Path, Path]:
    scorecard_path = tmp_path / "scorecard.json"
    archive_dir = tmp_path / "archive"
    _write_json(
        scorecard_path,
        {
            "artifact": "valucast_ahead_of_consensus_scorecard",
            "as_of": "2026-06-30",
            "summary": {
                "decided_count": 3,
                "wins": 1,
                "decided_rate": 0.333,
                "control_lift": 0.9,
            },
            "calls": [
                _call(1, "hitter", "open_toward"),
                _call(2, "pitcher", "open_away"),
                _call(3, "hitter", "retired_we_backed_off"),
                _call(4, "hitter", "open_flat"),
                _call(5, "hitter", "open_toward", days=10),
            ],
        },
    )
    _write_json(
        archive_dir / "2026-06-01.json",
        {
            "board": [
                _row(
                    1,
                    "hitter",
                    rank=25,
                    age=19,
                    level="A+",
                    sample=150,
                    confidence="high",
                    reliability=50,
                    availability="available",
                ),
                _row(
                    2,
                    "pitcher",
                    rank=40,
                    age=22,
                    level="AA",
                    sample=50,
                    confidence="medium",
                    reliability=25,
                    availability="thin_current_sample",
                ),
                _row(
                    3,
                    "hitter",
                    rank=100,
                    age=24,
                    level="AAA",
                    sample=400,
                    confidence="low",
                    reliability=24.99,
                    availability="injured",
                ),
            ]
        },
    )
    return scorecard_path, archive_dir


def test_build_audit_filters_and_reconciles_matured_decisions(tmp_path):
    scorecard_path, archive_dir = _fixture_inputs(tmp_path)

    payload = build_audit(
        scorecard_path=scorecard_path,
        archive_dir=archive_dir,
        generated_at="2026-07-31T12:00:00+00:00",
    )

    assert payload["quality"] == {
        "expected_decided_count": 3,
        "joined_decided_count": 3,
        "join_errors": [],
        "ready": True,
    }
    assert payload["overall"]["n"] == 3
    assert payload["overall"]["wins"] == 1
    assert payload["overall"]["moved_away"] == 1
    assert payload["overall"]["retracted"] == 1
    assert payload["overall"]["win_rate"] == 0.333
    for rows in payload["dimensions"].values():
        assert sum(row["n"] for row in rows) == 3


def test_build_audit_fails_closed_on_missing_claim_time_row(tmp_path):
    scorecard_path, archive_dir = _fixture_inputs(tmp_path)
    archive = json.loads((archive_dir / "2026-06-01.json").read_text(encoding="utf-8"))
    archive["board"] = archive["board"][:-1]
    _write_json(archive_dir / "2026-06-01.json", archive)

    with pytest.raises(ValueError, match="exact claim-time join"):
        build_audit(scorecard_path=scorecard_path, archive_dir=archive_dir)


def test_build_audit_fails_closed_on_duplicate_identity(tmp_path):
    scorecard_path, archive_dir = _fixture_inputs(tmp_path)
    archive = json.loads((archive_dir / "2026-06-01.json").read_text(encoding="utf-8"))
    archive["board"].append(dict(archive["board"][0]))
    _write_json(archive_dir / "2026-06-01.json", archive)

    with pytest.raises(ValueError, match="duplicate identity"):
        build_audit(scorecard_path=scorecard_path, archive_dir=archive_dir)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "missing"),
        (19, "19_or_younger"),
        (20, "20_21"),
        (21, "20_21"),
        (22, "22_23"),
        (23, "22_23"),
        (24, "24_or_older"),
    ],
)
def test_age_bins(value, expected):
    assert age_bin(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ACL", "complex_rookie"),
        ("DSL", "complex_rookie"),
        ("Rk", "complex_rookie"),
        ("A", "a_a_plus"),
        ("A+", "a_a_plus"),
        ("AA", "aa"),
        ("AAA", "aaa"),
        (None, "other_missing"),
    ],
)
def test_level_bins(value, expected):
    assert level_bin(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "missing"), (24.99, "below_25"), (25, "25_49_99"), (49.99, "25_49_99"), (50, "50_plus")],
)
def test_reliability_bins(value, expected):
    assert reliability_bin(value) == expected


@pytest.mark.parametrize(
    ("role", "value", "expected"),
    [
        ("hitter", None, "missing"),
        ("hitter", 99, "below_100_pa"),
        ("hitter", 100, "100_199_pa"),
        ("hitter", 200, "200_399_pa"),
        ("hitter", 400, "400_plus_pa"),
        ("pitcher", 19.9, "below_20_ip"),
        ("pitcher", 20, "20_49_99_ip"),
        ("pitcher", 50, "50_99_99_ip"),
        ("pitcher", 100, "100_plus_ip"),
    ],
)
def test_role_specific_sample_bins(role, value, expected):
    assert sample_bin(role, value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(25, "25_49"), (50, "50_99"), (100, "100_199"), (200, "200_plus")],
)
def test_gap_bins(value, expected):
    assert gap_bin(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, "1_50"), (50, "1_50"), (51, "51_100"), (101, "101_250"), (251, "251_plus")],
)
def test_rank_bins(value, expected):
    assert rank_bin(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(2, "2"), (3, "3_4"), (4, "3_4"), (5, "5_plus")],
)
def test_coverage_bins(value, expected):
    assert coverage_bin(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("available", "available"),
        ("thin_current_sample", "limited"),
        ("limited_upper_level_sample", "limited"),
        ("injured", "unavailable"),
        ("inactive", "unavailable"),
        ("stale", "unavailable"),
        (None, "other_missing"),
    ],
)
def test_availability_bins(value, expected):
    assert availability_bin(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("low", "low"), ("medium", "medium"), ("high", "high"), (None, "other_missing")],
)
def test_confidence_bins(value, expected):
    assert confidence_bin(value) == expected


def test_wilson_interval_and_small_cell_labels(tmp_path):
    lower, upper = wilson_interval(42, 151)
    assert 0.21 < lower < 0.22
    assert 0.35 < upper < 0.36

    scorecard_path, archive_dir = _fixture_inputs(tmp_path)
    payload = build_audit(scorecard_path=scorecard_path, archive_dir=archive_dir)
    assert payload["overall"]["evidence_status"] == "insufficient"
    assert all(
        row["evidence_status"] == "insufficient"
        for rows in payload["dimensions"].values()
        for row in rows
    )


def test_artifact_cannot_publish_sources_or_feed_the_model(tmp_path):
    scorecard_path, archive_dir = _fixture_inputs(tmp_path)
    payload = build_audit(scorecard_path=scorecard_path, archive_dir=archive_dir)
    rendered = json.dumps(payload, sort_keys=True)

    for forbidden in ("pipeline", "hkb", "sts", "source_ranks", '"boards"'):
        assert forbidden not in rendered
    assert payload["boundaries"] == {
        "feeds_model_score": False,
        "feeds_rank_or_value": False,
        "feeds_publication": False,
        "public_surface": False,
        "authorizes_new_claim": False,
    }


def test_script_entry_point_can_import_repo_modules():
    result = subprocess.run(
        [sys.executable, "scripts/audit_consensus_decisions.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_provenance_hash_is_line_ending_neutral(tmp_path):
    # Review F1: the recorded hash must name the canonical LF content, so a
    # Windows (CRLF) checkout and a Linux checkout record the same provenance.
    from scripts.audit_consensus_decisions import _sha256

    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{"a": 1}\n{"b": 2}\n')
    crlf.write_bytes(b'{"a": 1}\r\n{"b": 2}\r\n')
    assert _sha256(lf) == _sha256(crlf)


def test_committed_audit_artifact_rebuilds_exactly():
    # The exact rebuild is only defined against the artifact's recorded
    # inputs. The scorecard refreshes daily, so once its hash moves past the
    # recorded provenance this test SKIPS instead of failing every future
    # merge-ref CI run (review F1); an archive changing while the scorecard
    # hash still matches is genuine provenance drift and still fails.
    from scripts.audit_consensus_decisions import DEFAULT_SCORECARD_PATH, _sha256

    path = ROOT / "data" / "validation" / "valucast_consensus_decision_error_audit.json"
    committed = json.loads(path.read_text(encoding="utf-8"))
    if _sha256(DEFAULT_SCORECARD_PATH) != committed["source_hashes"]["scorecard_sha256"]:
        pytest.skip(
            "scorecard has refreshed past the committed audit artifact; "
            "exact rebuild is only defined against its recorded inputs"
        )
    rebuilt = build_audit(generated_at=committed["generated_at"])

    assert committed["quality"]["joined_decided_count"] == 151
    assert committed["overall"]["wins"] == 42
    assert rebuilt == committed
