"""Fixture-only checks of the missing-MLBAM readiness blockers in the snapshot builder."""
import pytest

from scripts.build_public_dynasty_snapshot import _cross_universe_calibration_report

MLB_BLOCKER = "ValuCast MLB layer has rows missing MLBAM identity."
PROSPECT_BLOCKER = "Prospect Rank v1 has rows missing MLBAM identity."


def _blockers(mlb_validation, rank_validation=None):
    report = _cross_universe_calibration_report(
        [],
        {"validation": rank_validation or {}},
        {"validation": mlb_validation},
        "2026-06-13",
        "2026-06-13",
        "2026-06-13",
        0,
    )
    return report["blockers"]


@pytest.mark.parametrize(
    "mlb_validation, blocks",
    [
        ({"missing_mlbam_count": 1, "missing_mlbam_blocking_count": 0}, False),
        ({"missing_mlbam_count": 2, "missing_mlbam_blocking_count": 1}, True),
        ({"missing_mlbam_count": 1, "missing_mlbam_blocking_count": 1}, True),
        # An older artifact has no blocking count: fall back to the raw count.
        ({"missing_mlbam_count": 1}, True),
        ({"missing_mlbam_count": 0}, False),
        ({}, False),
    ],
)
def test_mlb_missing_mlbam_blocker_uses_blocking_count(mlb_validation, blocks):
    assert (MLB_BLOCKER in _blockers(mlb_validation)) is blocks


def test_prospect_rank_missing_mlbam_blocker_ignores_mlb_layer_exceptions():
    blockers = _blockers(
        {"missing_mlbam_count": 1, "missing_mlbam_blocking_count": 0},
        {"missing_mlbam_count": 1},
    )

    assert MLB_BLOCKER not in blockers
    assert PROSPECT_BLOCKER in blockers
