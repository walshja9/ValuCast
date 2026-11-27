"""Tests for ValuCast Prospect Peak Projection v1."""
import json

import pytest

from prospects.peak_projection import PeakProjectionSentinelError
from prospects.peak_projection import RUN_PREVENTION_MIN_PITCHERS
from prospects.peak_projection import _correlation
from prospects.peak_projection import _pitcher_shape
from prospects.peak_projection import _role_probability
from prospects.peak_projection import _summary
from prospects.peak_projection import build_peak_projection
from prospects.peak_projection import check_run_prevention_sentinel
from prospects.peak_projection import run_peak_projection
from scripts.validate_prospect_peak_projection import validate_peak_projection


def test_role_probability_top_term_is_not_degenerate_across_the_real_range():
    # 7/7: the "top" (regular-or-better) term was anchored at peak_score=45.0,
    # /35.0 -- but the real board's peak_score distribution is heavily
    # right-skewed (median ~23.6, p95 ~46.1), so that anchor sat at the ~94th
    # percentile and 96% of the real 2,796-player board was pinned to an
    # identical 0.05 floor regardless of whether they were a median prospect
    # or a replacement-level one. Exercise the function across representative
    # peak_score values spanning the real distribution (not just the top
    # sliver) and confirm it actually differentiates them now.
    row = {"role": "hitter"}
    # (peak_score, expected real-board percentile it roughly represents)
    p01, p10, p25, p50, p75, p90, p95, p99 = 7.2, 11.5, 15.7, 23.6, 32.8, 41.1, 46.1, 58.1
    values = {
        pct: _role_probability(row, score, "low", 45.0)["regular_or_better"]
        for pct, score in (
            ("p01", p01), ("p10", p10), ("p25", p25), ("p50", p50),
            ("p75", p75), ("p90", p90), ("p95", p95), ("p99", p99),
        )
    }
    ordered = list(values.values())
    assert ordered == sorted(ordered)  # monotonic in peak_score
    # The bottom decile legitimately saturates at the floor and the top few
    # percent at the cap -- that's correct clamping, not the bug. The bug was
    # that 90% of the REAL DISTRIBUTION (p10 through p95) was ALSO flattened
    # onto that same floor. Assert the middle actually differentiates now.
    assert values["p01"] == values["p10"] == 0.05  # bottom decile: floor, correctly
    middle = [values["p25"], values["p50"], values["p75"], values["p90"]]
    assert len(set(middle)) == len(middle), "the middle of the real distribution must not collapse to one value"
    assert 0.05 < values["p50"] < 0.65, "the real board median must land meaningfully off both endpoints"


def _run_prevention_grade(era, whip):
    current = {"k_per_9": 9.0, "bb_per_9": 3.0, "k_bb_pct": 18.0, "era": era, "whip": whip}
    shape = _pitcher_shape(current, rank_score=50.0)
    rp = next(item for item in shape if item["label"] == "Run Prevention")
    return rp["grade"]


def test_run_prevention_grade_rewards_low_era_and_whip():
    # Run Prevention must reward low ERA/WHIP. Under the old double-negated
    # (swapped anchors + lower_is_better=True) code this was fully inverted,
    # so a 7.11 ERA / 1.97 WHIP line graded ABOVE a 1.13 / 0.66 elite line.
    elite = _run_prevention_grade(era=1.13, whip=0.66)
    terrible = _run_prevention_grade(era=7.11, whip=1.97)
    assert elite > terrible


def _row(rank, role="hitter"):
    current = (
        {
            "sample": 224,
            "sample_unit": "PA",
            "skill_band": "impact",
            "ops": 0.976,
            "iso": 0.261,
            "k_pct": 12.9,
            "bb_pct": 9.8,
            "bb_minus_k_pct": -3.1,
        }
        if role == "hitter"
        else {
            "sample": 55.7,
            "sample_unit": "IP",
            "skill_band": "starter_volume",
            "k_per_9": 13.3,
            "bb_per_9": 1.1,
            "k_bb_pct": 37.7,
            "era": 1.13,
            "whip": 0.66,
            "starter_role": True,
        }
    )
    return {
        "rank": rank,
        "name": f"Prospect {rank}",
        "mlbam_id": 10000 + rank,
        "role": role,
        "level": "AA",
        "age": 20,
        "eta": 2027,
        "score": 60.0 - rank,
        "score_source": "prospect_model_v0_6",
        "components": {
            "factual_current_context": current,
            "factual_investment_context": 82.0,
            "sample_reliability": 58.0,
            "availability": {"status": "available"},
            "availability_risk_discount": 0.0,
        },
    }


def _rank_payload(rows):
    return {
        "rank_name": "ValuCast Prospect Rank v1 Candidate",
        "rank_version": "0.2.7",
        "status": "candidate_ready",
        "generated_at": "2026-06-15T00:00:00+00:00",
        "ranked_count": len(rows),
        "board": rows,
    }


def test_peak_summary_labels_the_sample_level():
    # (1c) TEXT LABEL ONLY: the deterministic PA cite must name its level ("over 199 AA PA")
    # so it can't read as a silent contradiction of a combined-line scouting read that pooled
    # more levels ("358 PA across AA & A+"). The scored line is unchanged; only prose labels.
    row = {
        "role": "hitter",
        "components": {
            "factual_current_context": {
                "sample": 199, "sample_unit": "PA", "level": "AA", "skill_band": "impact",
            }
        },
    }
    text = _summary(row, 55.0, "everyday_regular", "moderate")
    assert "199 AA PA" in text


def test_peak_summary_without_level_omits_the_label():
    # No level in the context -> the cite falls back to the bare sample (no dangling label).
    row = {
        "role": "hitter",
        "components": {
            "factual_current_context": {"sample": 199, "sample_unit": "PA", "skill_band": "impact"}
        },
    }
    text = _summary(row, 55.0, "everyday_regular", "moderate")
    assert "199 PA" in text
    assert "199  PA" not in text


def test_peak_projection_builds_card_ready_role_and_shape_without_rank_mutation():
    payload = build_peak_projection(_rank_payload([_row(1), _row(2, role="pitcher")]))

    assert payload["artifact"] == "valucast_prospect_peak_projection_v1"
    assert payload["status"] == "candidate_ready"
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["source_policy"]["external_rankings_used_for_score"] is False
    assert payload["source_policy"]["public_scouting_grades_used"] is False
    assert payload["projection_contract"]["feeds_live_rank"] is False
    assert payload["projection_contract"]["feeds_live_value"] is False
    assert payload["projection_contract"]["projection_kind"] == (
        "peak_role_and_skill_shape_not_full_stat_forecast"
    )
    assert payload["projection_contract"]["card_visual_version"] == "2.0.0"
    assert payload["validation"]["ready_for_card_v2"] is True

    hitter = payload["projections"][0]
    pitcher = payload["projections"][1]
    assert hitter["rank_v1_rank"] == 1
    assert hitter["peak_score"] > hitter["rank_v1_score"]
    assert hitter["usage"] == "card_visual_context_not_live_rank_or_value"
    assert hitter["card_v2"]["visual_version"] == "2.0.0"
    assert hitter["card_v2"]["role_probabilities"]["regular_or_better"] > 0
    assert hitter["card_v2"]["card_copy"].startswith("Ceiling is")
    # The floor clause must not double-print "floor" — the slug "..._floor"
    # used to render as "floor is reserve floor". "floor" appears once now.
    assert hitter["card_v2"]["card_copy"].lower().count("floor") == 1
    assert len(hitter["shape"]) == 4
    assert {item["label"] for item in hitter["shape"]} == {
        "Hit",
        "Power",
        "Approach",
        "Impact",
    }
    assert pitcher["peak_role"] in {
        "rotation_starter",
        "mid_rotation_or_better",
    }
    assert {item["label"] for item in pitcher["shape"]} == {
        "Miss",
        "Command",
        "Dominance",
        "Run Prevention",
    }


def _row_with_v2_inputs(rank=1):
    row = _row(rank)
    row["dynasty_signal"] = {
        "role_or_better_probability": 0.6,
        "star_ceiling_probability": 0.2,
    }
    row["context_only"] = {
        "best_single_level_stat_line": {
            "level": "AA",
            "sample": 250,
            "sample_unit": "PA",
            "reason": "current_level_too_thin_best_prior_level",
            "avg": 0.300,
            "obp": 0.380,
            "slg": 0.520,
            "ops": 0.900,
            "iso": 0.220,
            "k_pct": 18.0,
            "bb_pct": 11.0,
        },
        "stat_line_translated": {
            "role": "hitter",
            "season": 2026,
            "level": "AA",
            "level_label": "AA",
            "sample": 250,
            "sample_unit": "PA",
            "low_sample": False,
            "confidence": "moderate",
            "stats": [
                {"key": "k_pct", "label": "K%", "fmt": "pct", "milb": 18.0, "mlb": 20.5, "mlb_avg": 22.0},
                {"key": "iso", "label": "ISO", "fmt": "iso", "milb": 0.220, "mlb": 0.170, "mlb_avg": 0.150},
            ],
        },
    }
    return row


def test_peak_v2_uses_best_single_and_model_role_probabilities():
    payload = build_peak_projection(_rank_payload([_row_with_v2_inputs(1)]))
    proj = payload["projections"][0]
    v2 = proj["peak_v2"]

    assert v2["model_version"] == "2.1.0"
    assert v2["status"] == "shadow_observe_only"
    assert v2["shape_basis"] == "best_single_level"
    assert v2["role_probability_source"] == "model_dynasty_signal"
    assert v2["role_probability_basis"] == "cumulative_uncalibrated_outcome_distribution"
    probs = v2["role_probabilities"]
    # Cumulative outlook: star-ceiling is a SUBSET of role-or-better, so it can never
    # exceed it (the inversion the de-cumulated buckets used to show).
    assert set(probs) == {"reaches_role_or_better", "reaches_star_ceiling", "bust_risk"}
    assert probs["reaches_role_or_better"] == 0.6  # role_or_better_probability passthrough
    assert probs["reaches_star_ceiling"] == 0.2  # star_ceiling_probability, <= role-or-better
    assert probs["reaches_star_ceiling"] <= probs["reaches_role_or_better"]
    assert probs["bust_risk"] == 0.4  # 1 - role_or_better
    assert v2["mlb_equivalent"]["rates"]["iso"]["mlb"] == 0.170
    assert len(v2["shape"]) == 4
    # v1 fields untouched
    assert proj["peak_score"] > proj["rank_v1_score"]
    assert proj["card_v2"]["role_probabilities"]["regular_or_better"] > 0

    v2_summary = payload["v2"]
    assert v2_summary["feeds_card"] is False
    assert v2_summary["best_single_level_shape_count"] == 1
    assert v2_summary["model_role_probability_count"] == 1


def test_peak_v2_falls_back_when_no_owned_inputs():
    v2 = build_peak_projection(_rank_payload([_row(1)]))["projections"][0]["peak_v2"]
    assert v2["shape_basis"] == "current"
    assert v2["role_probability_source"] == "heuristic_fallback"
    assert v2["mlb_equivalent"] is None
    assert v2["delta_vs_v1_peak_score"] == 0.0


def test_peak_projection_thin_rows_get_neutral_shape_and_lower_confidence():
    row = _row(1)
    row["components"].pop("factual_current_context")
    row["components"]["sample_reliability"] = 28.0
    row["components"]["availability"] = {"status": "injured"}
    row["components"]["availability_risk_discount"] = 0.10

    payload = build_peak_projection(_rank_payload([row]))
    projection = payload["projections"][0]

    assert payload["validation"]["ready_for_card_v2"] is True
    assert projection["risk_band"] == "high"
    assert projection["confidence"] == "low"
    assert len(projection["shape"]) == 4
    assert all(20 <= item["grade"] <= 80 for item in projection["shape"])


def test_run_and_validate_peak_projection(tmp_path):
    rank_path = tmp_path / "rank.json"
    artifact_path = tmp_path / "peak.json"
    rank_path.write_text(
        json.dumps(_rank_payload([_row(1), _row(2, role="pitcher")])),
        encoding="utf-8",
    )

    # archive_dir MUST be redirected: the default writes a dated snapshot into
    # the REAL data/prediction_archive/ trail, and this test's synthetic
    # "Prospect 1/2" rows once leaked in as 2026-06-15.json and polluted the
    # rank-history artifact (fake mlbam 10001/10002 at ranks 1-2).
    result = run_peak_projection(
        rank_path=rank_path,
        artifact_path=artifact_path,
        archive_dir=tmp_path / "archive",
    )
    assert (tmp_path / "archive" / "2026-06-15.json").exists()
    payload, problems = validate_peak_projection(artifact_path)

    assert result["ready_for_card_v2"] is True
    assert payload["artifact"] == "valucast_prospect_peak_projection_v1"
    assert problems == []


def test_peak_projection_validator_rejects_public_scouting_grade_flag(tmp_path):
    payload = build_peak_projection(_rank_payload([_row(1)]))
    payload["source_policy"]["public_scouting_grades_used"] = True
    artifact_path = tmp_path / "peak.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_peak_projection(artifact_path)

    assert "source_policy.public_scouting_grades_used must be false" in problems


def test_peak_projection_validator_rejects_stale_card_copy(tmp_path):
    payload = build_peak_projection(_rank_payload([_row(1)]))
    projection = payload["projections"][0]
    projection["card_v2"]["card_copy"] = "Peak view: everyday regular; floor is reserve floor."
    artifact_path = tmp_path / "peak.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_peak_projection(artifact_path)

    assert any("stale card_v2 card_copy" in problem for problem in problems)


# --- Run Prevention semantic sentinel -------------------------------------

# A spread of (ERA, WHIP, Run Prevention grade) pitcher shapes. The grades here
# are CORRECT: elite ERA/WHIP -> high grade, terrible ERA/WHIP -> low grade.
# corr(ERA, grade) is strongly negative, matching healthy production data.
_PITCHER_GRID = [
    # era,  whip, correct Run Prevention grade
    (1.05, 0.70, 80),
    (1.80, 0.85, 75),
    (2.40, 0.95, 70),
    (2.90, 1.05, 60),
    (3.30, 1.15, 55),
    (3.80, 1.25, 50),
    (4.20, 1.30, 45),
    (4.70, 1.40, 40),
    (5.10, 1.55, 35),
    (5.70, 1.65, 30),
    (6.30, 1.80, 25),
    (7.10, 1.97, 20),
    (1.30, 0.75, 78),
    (6.80, 1.90, 22),
]


def _pitcher_projection(index, era, whip, run_prevention_grade):
    return {
        "mlbam_id": 50000 + index,
        "name": f"Pitcher {index}" if index else "Kade Anderson",
        "role": "pitcher",
        "shape": [
            {"label": "Miss", "grade": 55, "source": "K/9"},
            {"label": "Command", "grade": 55, "source": "BB/9"},
            {"label": "Dominance", "grade": 55, "source": "K-BB%"},
            {"label": "Run Prevention", "grade": run_prevention_grade, "source": "ERA / WHIP"},
        ],
    }


def _sentinel_inputs(grid):
    """Build matching (projections, rank_payload) where the rank payload carries
    the ERA each Run Prevention grade was built from, keyed by MLBAM+role."""
    projections = []
    board = []
    for index, (era, whip, grade) in enumerate(grid):
        projections.append(_pitcher_projection(index, era, whip, grade))
        board.append(
            {
                "mlbam_id": 50000 + index,
                "role": "pitcher",
                "components": {"factual_current_context": {"era": era, "whip": whip}},
            }
        )
    return projections, {"board": board}


def test_run_prevention_sentinel_passes_on_correct_grades():
    projections, rank_payload = _sentinel_inputs(_PITCHER_GRID)
    summary = check_run_prevention_sentinel(projections, rank_payload)

    assert summary["status"] == "ok"
    assert summary["graded_pitcher_count"] == len(_PITCHER_GRID)
    assert summary["violation_count"] == 0
    assert summary["violation_rate"] == 0.0
    # Strongly negative on healthy data; the -0.20 gate has wide margin.
    assert summary["era_grade_correlation"] < -0.6


def test_run_prevention_sentinel_raises_on_inverted_grades():
    # Flip every grade around the 20-80 axis: low ERA now graded LOW (the bug
    # that shipped a 7.11 ERA at 80 and a 1.0 ERA at 20).
    inverted_grid = [(era, whip, 100 - grade) for era, whip, grade in _PITCHER_GRID]
    projections, rank_payload = _sentinel_inputs(inverted_grid)

    with pytest.raises(PeakProjectionSentinelError) as excinfo:
        check_run_prevention_sentinel(projections, rank_payload)

    message = str(excinfo.value)
    assert "Run Prevention sentinel FAILED" in message
    # The first inverted row is Kade Anderson (elite ERA graded as poor).
    assert "Kade Anderson" in message


def test_run_prevention_sentinel_raises_on_hard_direction_violations():
    # The violation-rate gate is a second line of defense, independent of the
    # correlation gate. This grid is strongly anti-correlated overall (so it
    # PASSES the corr <= -0.20 check) but contains a couple of hard direction
    # violations (an elite ERA graded poor, a blow-up ERA graded elite) above the
    # 5% rate. The sentinel must still raise on those.
    grid = [
        (1.20, 0.75, 78),
        (1.60, 0.85, 74),
        (2.10, 0.95, 68),
        (2.60, 1.05, 62),
        (3.10, 1.12, 56),
        (3.60, 1.20, 52),
        (4.10, 1.28, 48),
        (4.60, 1.38, 44),
        (5.10, 1.50, 38),
        (5.60, 1.62, 32),
        (6.10, 1.78, 26),
        (6.60, 1.90, 22),
        (2.90, 1.05, 35),  # violation: ERA <= 3.00 graded < 40
        (5.80, 1.66, 65),  # violation: ERA >= 5.50 graded > 60
    ]
    projections, rank_payload = _sentinel_inputs(grid)

    # Confirm this exercises the violation gate, not the correlation gate.
    eras = [era for era, _w, _g in grid]
    grades = [grade for _e, _w, grade in grid]
    assert _correlation(eras, grades) <= -0.20

    with pytest.raises(PeakProjectionSentinelError) as excinfo:
        check_run_prevention_sentinel(projections, rank_payload)
    assert "violate the ERA" in str(excinfo.value)


def test_run_prevention_sentinel_passes_with_too_few_pitchers():
    # Conservative by design: below the minimum sample, the correlation is not
    # trustworthy, so the sentinel records "insufficient_sample" and passes
    # rather than risk a false positive on healthy-but-tiny boards.
    small_grid = _PITCHER_GRID[: RUN_PREVENTION_MIN_PITCHERS - 1]
    projections, rank_payload = _sentinel_inputs(small_grid)

    summary = check_run_prevention_sentinel(projections, rank_payload)

    assert summary["status"] == "insufficient_sample"
    assert summary["era_grade_correlation"] is None


def test_build_peak_projection_blocks_inverted_run_prevention_artifact():
    # End-to-end: a build whose Run Prevention grades are inverted must raise
    # from build_peak_projection (before any artifact is written), naming an
    # example so the failure is actionable.
    rows = []
    for index, (era, whip, _grade) in enumerate(_PITCHER_GRID):
        row = _row(index + 1, role="pitcher")
        row["components"]["factual_current_context"]["era"] = era
        row["components"]["factual_current_context"]["whip"] = whip
        rows.append(row)

    # Correct grades build cleanly and record the sentinel summary.
    payload = build_peak_projection(_rank_payload(rows))
    sentinel = payload["validation"]["run_prevention_sentinel"]
    assert sentinel["status"] == "ok"
    assert sentinel["violation_count"] == 0

    # Now invert the built Run Prevention grades and re-run the sentinel via the
    # public check to prove the build-step guard rejects the inverted artifact.
    inverted = payload["projections"]
    for row in inverted:
        for item in row["shape"]:
            if item["label"] == "Run Prevention":
                item["grade"] = 100 - item["grade"]
    with pytest.raises(PeakProjectionSentinelError):
        check_run_prevention_sentinel(inverted, _rank_payload(rows))


def test_cohered_role_probabilities_follow_floored_ceiling():
    from prospects.peak_projection import _cohere_role_probabilities

    probs = {"regular_or_better": 0.059, "bench_or_platoon": 0.741, "depth_or_reserve": 0.2}

    cohered = _cohere_role_probabilities(probs, "everyday_regular", "hitter", "medium")
    assert max(cohered, key=cohered.get) == "regular_or_better"
    assert sorted(cohered.values()) == sorted(probs.values())

    # gates mirror the label floor: high risk, pitchers, non-floored tiers untouched
    assert _cohere_role_probabilities(probs, "everyday_regular", "hitter", "high") == probs
    assert _cohere_role_probabilities(probs, "everyday_regular", "pitcher", "medium") == probs
    assert _cohere_role_probabilities(probs, "bench_or_platoon_bat", "hitter", "medium") == probs
