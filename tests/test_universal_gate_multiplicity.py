"""Tests for the universal-gate multiplicity report (audit repair R3)."""
import copy
import json

import numpy as np

from prospects.universal_gate_multiplicity import (
    ARTIFACT_PATH,
    FAMILY_ALPHA,
    build_gate_multiplicity,
    validate_gate_multiplicity,
)


def _committed():
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def _records(deltas):
    """Synthetic gate records with a controllable per-item separation."""
    rng = np.random.default_rng(0)
    records = []
    for index, delta in enumerate(deltas):
        # baseline error 0.20; model error 0.20*(1 - delta/100) so delta% is exact
        baseline = np.full(400, 0.20)
        model = np.full(400, 0.20 * (1 - delta / 100.0))
        clusters = np.arange(400)
        # bootstrap draws with tiny noise for a finite SE
        from prospects.universal_gate_multiplicity import _bootstrap

        boot = _bootstrap(model + rng.normal(0, 1e-9, 400), baseline, clusters)
        records.append(
            {
                "role": "hitter" if index % 2 else "pitcher",
                "target": f"t{index}",
                "metric": "brier_score",
                "baseline": "historical_neighbors_25",
                "sample_size": 400,
                "served_gate_status": "active" if delta >= 2.0 else "fallback",
                "served_improvement_pct": round(delta, 4),
                "point": boot["point"],
                "draws": boot["draws"],
            }
        )
    return records


def test_committed_multiplicity_validates():
    assert validate_gate_multiplicity(_committed()) == []


def test_committed_reports_the_full_family_and_carries_served_status():
    payload = _committed()
    assert payload["family"]["family_size"] == 24
    assert payload["family"]["family_wise_alpha"] == FAMILY_ALPHA
    assert payload["procedure"]["feeds_gate_decision"] is False
    # every gate carries a served status verbatim so no decision can be read as changed
    assert len(payload["gates"]) == 24
    for gate in payload["gates"]:
        assert gate["served_gate_status"] in {
            "active",
            "fallback",
            "insufficient_sample",
            "failed",
        }


def test_bonferroni_is_strictly_stricter_than_nominal():
    payload = _committed()
    family = payload["family"]
    assert family["bonferroni_two_sided_z"] > family["nominal_two_sided_z"]
    assert (
        family["bonferroni_significant_gates"] <= family["nominal_significant_gates"]
    )
    # a Bonferroni survivor is always also nominally significant
    for gate in payload["gates"]:
        if gate["bonferroni_significant"]:
            assert gate["nominal_significant"]


def test_committed_stores_no_consensus_leakage():
    text = json.dumps(_committed())
    for banned in ("source_rank", "consensus_rank", "eephus", "board_count"):
        assert banned not in text


def test_build_flags_significance_by_family_correction():
    # 24 gates: one strongly separated (survives Bonferroni), rest flat.
    deltas = [30.0] + [0.0] * 23
    payload = build_gate_multiplicity(_records(deltas), input_sha256="0" * 64)
    assert validate_gate_multiplicity(payload) == []
    assert payload["family"]["family_size"] == 24
    strong = next(g for g in payload["gates"] if g["target"] == "t0")
    assert strong["nominal_significant"] is True
    assert strong["bonferroni_significant"] is True
    # a flat gate is neither
    flat = next(g for g in payload["gates"] if g["target"] == "t1")
    assert flat["nominal_significant"] is False
    assert flat["bonferroni_significant"] is False


def test_nominal_significance_is_driven_by_the_percentile_ci_not_wald_z():
    # FIX 2: pitcher representative_ip's percentile CI excludes 0 even though the
    # symmetric Wald |z| < 1.96 (skewed bootstrap). It must read as nominally
    # significant off the CI, and its descriptive z stays sub-threshold.
    payload = _committed()
    ip = next(
        g
        for g in payload["gates"]
        if g["role"] == "pitcher" and g["target"] == "representative_ip"
    )
    assert ip["ci_low"] is not None and ip["ci_high"] is not None
    ci_excludes_zero = ip["ci_low"] > 0 or ip["ci_high"] < 0
    assert ip["nominal_significant"] is ci_excludes_zero
    assert ci_excludes_zero is True
    # descriptive z is reported but is NOT the criterion (would have said "no")
    assert abs(ip["bootstrap_z_descriptive"]) < payload["family"]["nominal_two_sided_z"]


def test_every_committed_flag_agrees_with_its_own_percentile_ci():
    # FIX 2 invariant: nominal/bonferroni flags are exactly "the matching
    # percentile CI excludes 0" for every gate.
    for gate in _committed()["gates"]:
        nominal = gate["ci_low"] is not None and (
            gate["ci_low"] > 0 or gate["ci_high"] < 0
        )
        bonf = gate["bonferroni_ci_low"] is not None and (
            gate["bonferroni_ci_low"] > 0 or gate["bonferroni_ci_high"] < 0
        )
        assert gate["nominal_significant"] is nominal
        assert gate["bonferroni_significant"] is bonf


def test_validator_rejects_flag_that_disagrees_with_its_ci():
    broken = copy.deepcopy(_committed())
    # Flip a flat gate's nominal flag on without moving its CI off 0.
    for gate in broken["gates"]:
        if not gate["nominal_significant"]:
            gate["nominal_significant"] = True
            broken["family"]["nominal_significant_gates"] += 1
            break
    problems = validate_gate_multiplicity(broken)
    assert any("nominal_significant disagrees with its CI" in p for p in problems)


def test_validator_rejects_bonferroni_without_nominal():
    payload = build_gate_multiplicity(_records([30.0] + [0.0] * 23), input_sha256="0" * 64)
    broken = copy.deepcopy(payload)
    # force an inconsistent flag: bonferroni True but nominal False
    for gate in broken["gates"]:
        if gate["target"] == "t1":
            gate["bonferroni_significant"] = True
            broken["family"]["bonferroni_significant_gates"] += 1
            break
    problems = validate_gate_multiplicity(broken)
    assert any("bonferroni-significant but not nominal" in p for p in problems)


def test_validator_rejects_feeds_gate_decision():
    broken = copy.deepcopy(_committed())
    broken["procedure"]["feeds_gate_decision"] = True
    problems = validate_gate_multiplicity(broken)
    assert any("feeds_gate_decision must be false" in p for p in problems)
