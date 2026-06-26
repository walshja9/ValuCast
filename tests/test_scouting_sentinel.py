"""Semantic sentinel for the scouting "no current sample" read.

The deterministic/LLM ValuCast Read must never claim "No current performance
sample is available" / "organizational depth" / no-sample low-confidence for a
prospect who HAS a non-empty current stat line. A stale artifact once shipped
~100 such contradictory reports (e.g. Ronny Hernandez 90 PA .329/.456/.671) and
PASSED validation. These tests lock the sentinel that now fails the build loud.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scouting import repository
from scouting.repository import (
    ScoutingRepositorySentinelError,
    _no_sample_contradiction,
    _no_sample_contradictions,
    build_scouting_repository,
    run_scouting_repository,
)


# The exact lead sentence the read emits for a genuinely sample-less prospect.
NO_SAMPLE_READ = (
    "No current performance sample is available for this 21-year-old C; there is "
    "no current evidence for how the bat produces. Hold the role call; the only "
    "supported floor today is organizational depth. Anything stronger is "
    "projection; confidence: low."
)
NORMAL_READ = (
    "The damage is the carrying tool over a 62 PA sample at Single-A, so "
    "confidence is low. A power-first line shows up in the rates."
)


def _row(stat_line, *, is_prospect=True, name="Test Prospect"):
    return SimpleNamespace(
        name=name,
        is_prospect=is_prospect,
        stat_line=stat_line,
    )


def _report(text, *, name="Test Prospect"):
    return {"name": name, "report": text}


# Real current lines (non-empty: real PA/IP + rate values).
HITTER_LINE = {"pa": 90, "avg": 0.329, "obp": 0.456, "slg": 0.671, "ops": 1.127, "iso": 0.342}
PITCHER_LINE = {"ip": 12.7, "era": 2.10, "whip": 0.95, "k_per_9": 13.0, "bb_per_9": 2.1}
# Genuinely sample-less inputs.
SAMPLE_ONLY = {"pa": 40}
EMPTY_LINE = {}


def test_no_sample_template_with_real_stat_line_trips_sentinel():
    # Ronny Hernandez case: no-sample read + non-empty hitter line -> contradiction.
    row = _row(HITTER_LINE, name="Ronny Hernandez")
    report = _report(NO_SAMPLE_READ, name="Ronny Hernandez")
    assert _no_sample_contradiction(row, report) is True
    assert _no_sample_contradictions([row], [report]) == ["Ronny Hernandez"]


def test_no_sample_template_with_real_pitcher_line_trips_sentinel():
    # Fernando Perez case: no-sample read + non-empty pitcher line -> contradiction.
    row = _row(PITCHER_LINE, name="Fernando Perez")
    report = _report(NO_SAMPLE_READ, name="Fernando Perez")
    assert _no_sample_contradiction(row, report) is True


def test_genuinely_sample_less_no_sample_report_passes():
    # Sample-only dict and empty line are NOT performance samples: no false positive.
    for line in (SAMPLE_ONLY, EMPTY_LINE, None):
        row = _row(line)
        report = _report(NO_SAMPLE_READ)
        assert _no_sample_contradiction(row, report) is False


def test_normal_report_with_real_stat_line_passes():
    # A normal stat-grounded read never contains the no-sample marker -> no trip.
    row = _row(HITTER_LINE)
    report = _report(NORMAL_READ)
    assert _no_sample_contradiction(row, report) is False


def test_non_prospect_no_sample_text_is_not_flagged():
    # The no-sample template is a prospect read; MLB rows are out of scope.
    row = _row(HITTER_LINE, is_prospect=False)
    report = _report(NO_SAMPLE_READ)
    assert _no_sample_contradiction(row, report) is False


def _write_snapshot(tmp_path, stat_line):
    payload = {
        "schema_version": "1.1",
        "artifact": "valucast_public_dynasty_snapshot",
        "generated_at": "2026-06-16T00:00:00+00:00",
        "generated_by": "valucast",
        "source_policy": {
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used_for_score": False,
            "market_values_used_for_score": False,
        },
        "validation": {
            "ready_for_live_consumers": False,
            "duplicate_identity_count": 0,
            "required_fields_complete": True,
        },
        "players": [
            {
                "id": "vc_prospect_1_hitter",
                "player_type": "prospect",
                "name": "Ronny Hernandez",
                "mlbam_id": 1,
                "role": "hitter",
                "bats": "R",
                "throws": "R",
                "positions": ["C"],
                "team": "BOS",
                "mlb_team": "BOS",
                "age": 21,
                "rank": 1,
                "value": 40.0,
                "value_scale": "0_100_valucast_dynasty_score",
                "value_source": "prospect_model_v0_6",
                "confidence": "medium",
                "updated_at": "2026-06-16T00:00:00+00:00",
                "status": "candidate_ready",
                "prospect_rank": 1,
                "level": "A+",
                "eta": 2027,
                "score_source": "prospect_model_v0_6",
                "stat_line": dict(stat_line),
                "context": {
                    "stat_line_source": "valucast_input_contract",
                    "stat_line_source_kind": "current_season",
                    "stat_line_sample": stat_line.get("pa", 90),
                    "stat_line_sample_unit": "PA",
                    "stat_line_sample_season": 2026,
                },
            }
        ],
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_build_gate_closes_when_no_sample_read_contradicts_real_line(tmp_path, monkeypatch):
    # End-to-end: force the read generator to emit the no-sample template for a
    # prospect that has a real stat line. The build must close the ready gate and
    # name the offender. (Forcing the read isolates the SENTINEL from the upstream
    # read-logic fix, so this test fails loud on a regression of either layer.)
    snapshot_path = _write_snapshot(tmp_path, HITTER_LINE)
    monkeypatch.setattr(
        repository.prospect_percentiles, "identity_line", lambda row, pct: NO_SAMPLE_READ
    )

    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )

    validation = payload["validation"]
    assert validation["no_sample_contradiction_count"] == 1
    assert validation["no_sample_contradiction_players"] == ["Ronny Hernandez"]
    assert validation["ready_for_repository"] is False
    assert any("no-sample read" in b for b in validation["blockers"])


def test_build_gate_open_for_genuinely_sample_less_prospect(tmp_path, monkeypatch):
    # Sample-only line: the no-sample read is LEGITIMATE, so the sentinel must not
    # fire (no false positive on a player who really has no performance sample).
    snapshot_path = _write_snapshot(tmp_path, SAMPLE_ONLY)
    monkeypatch.setattr(
        repository.prospect_percentiles, "identity_line", lambda row, pct: NO_SAMPLE_READ
    )

    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )

    validation = payload["validation"]
    assert validation["no_sample_contradiction_count"] == 0
    assert validation["no_sample_contradiction_players"] == []
    assert not any("no-sample read" in b for b in validation["blockers"])


def test_run_repository_fails_loud_and_does_not_publish(tmp_path, monkeypatch):
    # The full build step must raise (non-zero exit) on the contradiction and must
    # NOT write the artifact, so a bad/stale repository can never publish.
    snapshot_path = _write_snapshot(tmp_path, HITTER_LINE)
    artifact_path = tmp_path / "reports.json"
    monkeypatch.setattr(
        repository.prospect_percentiles, "identity_line", lambda row, pct: NO_SAMPLE_READ
    )

    with pytest.raises(ScoutingRepositorySentinelError) as exc:
        run_scouting_repository(snapshot_path=snapshot_path, artifact_path=artifact_path)

    assert "Ronny Hernandez" in str(exc.value)
    assert not artifact_path.exists()


def test_run_repository_publishes_when_read_is_consistent(tmp_path):
    # Healthy data (the read-logic fix in place): a real line gets a stat-grounded
    # read, no contradiction, artifact publishes. Guards against a false-positive
    # sentinel that would block healthy builds.
    snapshot_path = _write_snapshot(tmp_path, HITTER_LINE)
    artifact_path = tmp_path / "reports.json"

    result = run_scouting_repository(snapshot_path=snapshot_path, artifact_path=artifact_path)

    assert result["ready_for_repository"] is True
    assert artifact_path.exists()
    written = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert written["validation"]["no_sample_contradiction_count"] == 0
    assert "No current performance sample is available" not in written["reports"][0]["report"]
