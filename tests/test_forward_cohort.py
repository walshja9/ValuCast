"""Tests for the forward-ledger cohort builder + registry (plan 030, S1)."""
from __future__ import annotations

import json

import pytest

import scripts.build_forward_cohort_registry as reg
from prospects.forward_cohort import (
    MAX_SERVED_RANK,
    MIN_BOARD_COUNT,
    PROTOCOL_VERSION,
    build_cohort,
)


def _row(mlbam_id, name, rank, *, role="hitter", boards=None):
    return {
        "mlbam_id": mlbam_id,
        "name": name,
        "role": role,
        "rank": rank,
        "mlb_team": "BOS",
        "context_only": {"source_ranks": boards or {}},
    }


def _cohort(rows, *, registration_date="2026-07-16", archive_date="2026-07-15"):
    return build_cohort(
        board=rows, registration_date=registration_date, archive_date=archive_date
    )


def _entrant(cohort, mlbam_id):
    for e in cohort["entrants"]:
        if e["mlbam_id"] == str(mlbam_id):
            return e
    return None


# --- Eligibility edges --------------------------------------------------------

def test_exactly_two_boards_is_eligible_with_consensus():
    # board_count == MIN_BOARD_COUNT (2) clears the consensus gate; median carried.
    cohort = _cohort([_row(1, "Two Board", 400, boards={"hkb": 100, "pl": 120})])
    e = _entrant(cohort, 1)
    assert e is not None
    assert e["board_count"] == 2
    assert e["consensus_rank"] == 110  # rounded median of {100, 120}
    assert cohort["counts"]["consensus_covered"] == 1
    assert cohort["counts"]["rank_only"] == 0


def test_one_board_over_rank_floor_is_ineligible():
    # A single board is not a consensus, and rank > 250 fails the rank gate -> out.
    cohort = _cohort([_row(1, "One Board Deep", 400, boards={"hkb": 100})])
    assert _entrant(cohort, 1) is None
    assert cohort["counts"]["eligible_total"] == 0


def test_rank_exactly_250_is_eligible_rank_only():
    # rank == MAX_SERVED_RANK (250), no boards -> eligible, null consensus.
    cohort = _cohort([_row(1, "Edge In", MAX_SERVED_RANK)])
    e = _entrant(cohort, 1)
    assert e is not None
    assert e["consensus_rank"] is None
    assert e["board_count"] == 0
    assert cohort["counts"]["rank_only"] == 1
    assert cohort["counts"]["consensus_covered"] == 0


def test_rank_exactly_251_is_ineligible():
    # rank == 251, no boards -> fails both gates.
    cohort = _cohort([_row(1, "Edge Out", MAX_SERVED_RANK + 1)])
    assert _entrant(cohort, 1) is None
    assert cohort["counts"]["eligible_total"] == 0


def test_rank_only_entrant_has_null_consensus_fields():
    # rank <= 250 with a single board -> eligible on rank, consensus still null
    # (board_count 1 < MIN_BOARD_COUNT), board_count reported honestly.
    cohort = _cohort([_row(1, "Rank Only", 10, boards={"hkb": 5})])
    e = _entrant(cohort, 1)
    assert e is not None
    assert e["consensus_rank"] is None
    assert e["board_count"] == 1


# --- Consensus source hygiene -------------------------------------------------

def test_internal_and_dd_sources_excluded_from_consensus():
    # Two external boards + internal signals + a dd_* key. Only the two external
    # boards count; the internal/dd ranks never touch the median or board_count.
    cohort = _cohort([
        _row(1, "Mixed", 400, boards={
            "hkb": 100, "pl": 120,          # external -> count
            "cfr": 5, "cfr_raw": 5,          # internal -> drop
            "milb_perf": 3, "milb_breakout": 3,  # internal -> drop
            "dd_dynasty": 7,                 # dd_* -> drop
        }),
    ])
    e = _entrant(cohort, 1)
    assert e["board_count"] == 2
    assert e["consensus_rank"] == 110  # median of {100, 120} only


def test_ranks_over_cap_excluded_from_consensus():
    # A deep-list rank above the 600 cap is dropped; if that leaves < 2 boards and
    # the served rank is over the floor, the player is ineligible.
    cohort = _cohort([_row(1, "Deep", 400, boards={"hkb": 100, "pl": 900})])
    # pl=900 > cap -> only hkb counts -> board_count 1, rank 400 > 250 -> out.
    assert _entrant(cohort, 1) is None


# --- No per-source ranks anywhere in the output -------------------------------

def _walk_no_source_ranks(obj, path="root"):
    if isinstance(obj, dict):
        assert "source_ranks" not in obj, f"source_ranks leaked at {path}"
        for k, v in obj.items():
            _walk_no_source_ranks(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_no_source_ranks(v, f"{path}[{i}]")


def test_no_source_ranks_key_anywhere_in_output():
    cohort = _cohort([
        _row(1, "Two Board", 50, boards={"hkb": 40, "pl": 60}),
        _row(2, "Rank Only", 20),
    ])
    _walk_no_source_ranks(cohort)
    # And no per-source rank VALUES ride along on an entrant.
    for e in cohort["entrants"]:
        assert set(e.keys()) == {
            "mlbam_id", "name", "valucast_rank", "consensus_rank", "board_count"
        }


# --- Role-blind dedup ---------------------------------------------------------

def test_role_blind_dedup_keeps_min_rank_and_counts():
    # Same mlbam_id on a hitter row (rank 300) and a pitcher row (rank 120): the
    # min-rank row wins, exactly one entrant, deduped == 1, no role field.
    cohort = _cohort([
        _row(7, "Two Way", 300, role="hitter", boards={"hkb": 100, "pl": 140}),
        _row(7, "Two Way", 120, role="pitcher", boards={"hkb": 100, "pl": 140}),
    ])
    entrants = [e for e in cohort["entrants"] if e["mlbam_id"] == "7"]
    assert len(entrants) == 1
    assert entrants[0]["valucast_rank"] == 120  # min rank wins
    assert "role" not in entrants[0]
    assert cohort["counts"]["deduped"] == 1


# --- Determinism / hash stability ---------------------------------------------

def test_hash_is_deterministic_across_rebuilds():
    rows = [
        _row(1, "A", 50, boards={"hkb": 40, "pl": 60}),
        _row(2, "B", 20),
    ]
    a = _cohort(rows)
    b = _cohort([dict(r) for r in rows])
    assert a["content_sha256"] == b["content_sha256"]
    assert a == b


def test_hash_excludes_itself_and_covers_body():
    cohort = _cohort([_row(1, "A", 50, boards={"hkb": 40, "pl": 60})])
    from prospects.forward_cohort import _content_sha256

    assert cohort["content_sha256"] == _content_sha256(cohort)
    # Mutating any body field changes the hash.
    mutated = json.loads(json.dumps(cohort))
    mutated["entrants"][0]["valucast_rank"] = 999
    assert _content_sha256(mutated) != cohort["content_sha256"]


def test_entrants_sorted_by_rank_then_id():
    cohort = _cohort([
        _row(3, "C", 30),
        _row(1, "A", 10),
        _row(2, "B", 30),
    ])
    ordered = [(e["valucast_rank"], e["mlbam_id"]) for e in cohort["entrants"]]
    assert ordered == [(10, "1"), (30, "2"), (30, "3")]


# --- Schema echo --------------------------------------------------------------

def test_frozen_schema_shape():
    cohort = _cohort([_row(1, "A", 50, boards={"hkb": 40, "pl": 60})])
    assert cohort["protocol_version"] == PROTOCOL_VERSION
    assert cohort["registration_date"] == "2026-07-16"
    assert cohort["archive_date"] == "2026-07-15"
    assert cohort["board_vintages"] is None
    elig = cohort["eligibility"]
    assert elig["min_board_count"] == MIN_BOARD_COUNT
    assert elig["max_served_rank"] == MAX_SERVED_RANK
    assert elig["dd_sources_excluded"] is True
    assert set(cohort["counts"]) == {
        "eligible_total", "consensus_covered", "rank_only", "deduped"
    }


# --- Registry: immutability + append-only + isolation -------------------------

def test_register_writes_registry_and_snapshot(tmp_path):
    board = [_row(1, "A", 50, boards={"hkb": 40, "pl": 60})]
    registry_path = tmp_path / "registry.json"
    archive_dir = tmp_path / "cohorts"
    cohort = reg.register_cohort(
        registration_date="2026-07-16",
        archive_date="2026-07-15",
        board=board,
        registry_path=registry_path,
        cohort_archive_dir=archive_dir,
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert registry["cohorts"]["2026-07-16"]["content_sha256"] == cohort["content_sha256"]
    snapshot = json.loads((archive_dir / "2026-07-16.json").read_text(encoding="utf-8"))
    assert snapshot == cohort


def test_rerun_same_date_is_hash_identical_noop(tmp_path):
    board = [_row(1, "A", 50, boards={"hkb": 40, "pl": 60})]
    registry_path = tmp_path / "registry.json"
    archive_dir = tmp_path / "cohorts"
    kwargs = dict(
        registration_date="2026-07-16",
        archive_date="2026-07-15",
        board=board,
        registry_path=registry_path,
        cohort_archive_dir=archive_dir,
    )
    first = reg.register_cohort(**kwargs)
    mtime = registry_path.stat().st_mtime_ns
    second = reg.register_cohort(**kwargs)  # identical inputs -> no-op
    assert second["content_sha256"] == first["content_sha256"]
    assert registry_path.stat().st_mtime_ns == mtime  # untouched on disk


def test_immutability_violation_raises_on_drift(tmp_path):
    registry_path = tmp_path / "registry.json"
    archive_dir = tmp_path / "cohorts"
    reg.register_cohort(
        registration_date="2026-07-16",
        archive_date="2026-07-15",
        board=[_row(1, "A", 50, boards={"hkb": 40, "pl": 60})],
        registry_path=registry_path,
        cohort_archive_dir=archive_dir,
    )
    # Same registration_date, DIFFERENT board -> different hash -> hard error.
    with pytest.raises(SystemExit, match="IMMUTABILITY VIOLATION"):
        reg.register_cohort(
            registration_date="2026-07-16",
            archive_date="2026-07-15",
            board=[_row(1, "A", 999, boards={"hkb": 40, "pl": 60})],
            registry_path=registry_path,
            cohort_archive_dir=archive_dir,
        )


def test_registry_is_append_only(tmp_path):
    registry_path = tmp_path / "registry.json"
    archive_dir = tmp_path / "cohorts"
    common = dict(registry_path=registry_path, cohort_archive_dir=archive_dir)
    reg.register_cohort(
        registration_date="2026-07-16", archive_date="2026-07-15",
        board=[_row(1, "A", 50, boards={"hkb": 40, "pl": 60})], **common,
    )
    reg.register_cohort(
        registration_date="2026-10-01", archive_date="2026-09-30",
        board=[_row(2, "B", 20)], **common,
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert set(registry["cohorts"]) == {"2026-07-16", "2026-10-01"}


def test_dev_run_out_must_be_outside_data(monkeypatch, tmp_path):
    # --dev-run --out inside data/ is rejected before anything is written.
    target = reg.ROOT / "data" / "leak.json"
    monkeypatch.setattr(
        "sys.argv",
        ["build_forward_cohort_registry.py", "--dev-run", "2026-07-15", "--out", str(target)],
    )
    with pytest.raises(SystemExit):
        reg.main()
    assert not target.exists()
