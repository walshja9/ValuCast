"""ValuCast value-core invariant harness.

One adversarial fixture per confirmed defect from the value-core audit. This is
the standing regression gate AND the MLE-rewrite acceptance test.

State (against shipped master — defect fixes B/C/D/E/F/G live in 962c920 /
d423ee0 / 94151a8):

  GREEN (gate the shipped standalone fixes; a regression flips them red):
    B  INV-THIN-1     thin-penalty keyed to current-line thinness
    C  INV-RISK-1     IL discount applied == discount the card reports
    D  INV-GRADFLOOR-1 grad floor reaches active-roster graduates with an MLB row
    E  INV-BADLINE-1  sub-floor (IP<10) line can't be ruled "bad" and pull a score
    F  INV-TELEMETRY-1 reported callup-bridge count == rows actually written
    G  INV-NORM-1     equal raw scores -> equal normalized scores

  XFAIL(strict) — standalone display-coherence fix (MLE rewrite shelved); flip
  to XPASS the moment the fix aligns display/calibration to the scored line:
    A      INV-SELECT-1  displayed line == scored (max-sample) line
    A-tail INV-SELECT-2  bucket calibration reads the scored line, not the display

D and F drive the REAL build path (scripts/build_public_dynasty_snapshot.py::
build_snapshot) with synthetic inputs — no hardcoded buggy source — so they gate
the wiring, not a restated arithmetic. The two strict xfails track the standalone
A/A-tail display-coherence fix (keep the max-sample scored line; move the displayed
and bucket-calibration line onto it): strict=True makes an unexpected PASS a CI
failure, so the day that fix lands the marker is removed deliberately.

Run:  pytest tests/test_value_core_invariants.py -v

Fixture archetypes (per brief): fast-promote, thin-gaudy, severe-IL,
role-count-imbalanced, freshly-graduated active-roster.
"""

import importlib.util
from pathlib import Path

import pytest

from prospects.model import _current_line_is_bad
from prospects.rank_v1 import (
    MODERATE_THIN_CAREER_SOFTENER,
    _apply_role_quantile_model_score_normalization,
    _bucket_calibration_adjustment,
    _input_row_sort_key,
    _model_score_field_normalized_key,
    _model_score_field_percentile_key,
)
from prospects.availability import (
    apply_availability_adjustment,
    MAX_IL_RISK_DISCOUNT,
)

REPO = Path(__file__).resolve().parent.parent


def _load_snapshot_module():
    path = REPO / "scripts" / "build_public_dynasty_snapshot.py"
    spec = importlib.util.spec_from_file_location("snapshot_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# A (CRITICAL) — INV-SELECT-1: the line that produces the score == the line shown
# --------------------------------------------------------------------------- #
def test_A_scored_line_equals_shown_line_fast_promote():
    """INV-SELECT-1. A fast-promoted prospect (AA big sample + AAA small sample,
    both current-season) must SHOW the same line that produced the SCORE.

    Today: _select_current_records scores max-sample (AA 209) while _input_row_sort_key
    shows highest-level (AAA 77) — the card shows AAA though ~76% of the number comes
    from AA. With the MLE rewrite shelved, the fix is now standalone display-coherence:
    keep the max-sample scored line and align the displayed (and bucket-calibration)
    line to it, rather than re-scoring. strict-xfail until that display fix lands.

    Lazy import: _select_current_records is the scoring selector the display fix must
    align to; imported locally so the file stays collectable if it ever moves.
    """
    from prospects.model import _select_current_records
    aa = {
        "mlbam_id": 100001, "name": "Fast Promote", "role": "hitter",
        "position": "SS", "level": "AA", "age": 21, "plate_appearances": 209.0,
        "source_kind": "current_season", "sample_season": 2026,
        "ops": 0.760, "iso": 0.150,
    }
    aaa = {
        "mlbam_id": 100001, "name": "Fast Promote", "role": "hitter",
        "position": "SS", "level": "AAA", "age": 21, "plate_appearances": 77.0,
        "source_kind": "current_season", "sample_season": 2026,
        "ops": 0.820, "iso": 0.190,
    }
    current = {"hitters": [aa, aaa]}

    scored = _select_current_records(current, "hitter")
    assert len(scored) == 1
    scored_line = scored[0]

    shown_line = max([aa, aaa], key=lambda r: _input_row_sort_key(r, "hitter"))

    assert scored_line["level"] == shown_line["level"], (
        f"scored {scored_line['level']} ({scored_line['plate_appearances']} PA) "
        f"!= shown {shown_line['level']} ({shown_line['plate_appearances']} PA)"
    )


# --------------------------------------------------------------------------- #
# A-tail (ship-sooner sub-fix) — INV-SELECT-2: bucket calibration reads the
# scored line, not the display line.
# --------------------------------------------------------------------------- #
def test_A_tail_bucket_calibration_reads_scored_line_not_display():
    """INV-SELECT-2. The upper-level-low-impact -1.5 penalty must key off the
    line that produced the score. Here the display line is a low-impact AAA cup
    of coffee (iso .05/ops .65) while the SCORED line was a high-impact AA line.
    The penalty fires off the display line's iso/ops -> mis-applied (~29 rows).
    """
    display_low_impact = {
        "mlbam_id": 100002, "role": "hitter", "level": "AAA",
        "iso": 0.050, "ops": 0.650,
    }
    components = {
        "availability": {"sample": 230.0, "sample_unit": "PA", "status": "available"},
        "factual_current_context": {"source_kind": "current_season"},
        "sample_reliability": 70.0,
    }
    _, out = _bucket_calibration_adjustment(
        score=60.0, source="prospect_model_v0_6", layer_profile={"role": "hitter"},
        input_row=display_low_impact, universe_row={"role": "hitter"},
        components=components,
    )
    buckets = {
        rule["bucket"]
        for rule in (out.get("bucket_calibration", {}) or {}).get("rules", [])
    }
    # Scored line was high-impact AA -> the low-impact penalty must NOT apply.
    assert "upper_level_low_impact_hitter_model_sample" not in buckets, (
        "penalty applied from display-line iso/ops, not the scored line"
    )


# --------------------------------------------------------------------------- #
# B (HIGH, contested) — INV-THIN-1: thin-current penalty is monotone in the
# CURRENT line's thinness (catalog choice: penalty proportional to current-line
# thinness, not pooled/layer reliability). Pending owner ratification, but the
# fixture is red under the catalog's chosen invariant.
# --------------------------------------------------------------------------- #
def _thin_penalty(current_pa, pooled_reliability):
    components = {
        "availability": {
            "sample": current_pa, "sample_unit": "PA", "status": "thin_current_sample",
        },
        "factual_current_context": {"source_kind": "current_season"},
        "sample_reliability": pooled_reliability,  # layer/pooled, decoupled from current line
    }
    _, out = _bucket_calibration_adjustment(
        score=50.0, source="prospect_model_v0_6", layer_profile={"role": "hitter"},
        input_row={"mlbam_id": 1, "role": "hitter", "level": "AAA"},
        universe_row={"role": "hitter"}, components=components,
    )
    for rule in (out.get("bucket_calibration", {}) or {}).get("rules", []):
        if rule["bucket"] == "thin_current_sample_confidence":
            return abs(float(rule["adjustment"]))
    return 0.0


def test_B_thin_penalty_monotone_in_current_line_thinness():
    """INV-THIN-1. The thinner current line must be penalized at least as hard.
    Thin-gaudy archetype: a 2-PA line on a player whose POOLED reliability is high
    vs a 200-PA line whose pooled reliability is low. The penalty currently scales
    by pooled reliability, so the 2-PA line is penalized LESS (Spearman -0.26).
    """
    pen_thin = _thin_penalty(current_pa=2.0, pooled_reliability=80.0)
    pen_full = _thin_penalty(current_pa=200.0, pooled_reliability=20.0)
    assert pen_thin >= pen_full, (
        f"2-PA penalty {pen_thin} < 200-PA penalty {pen_full}: penalty keyed to "
        f"pooled reliability, not current-line thinness"
    )


# --------------------------------------------------------------------------- #
# C (HIGH, blocked on ruling) — INV-RISK-1: the risk discount the card reports
# equals the discount actually applied to the score. Holds under EITHER ruling
# (0.12 vs 0.40); only the magnitude is owner's call. Severe-IL archetype.
# --------------------------------------------------------------------------- #
def test_C_il_discount_applied_matches_reported():
    """INV-RISK-1. Producer (_profile) writes risk_discount=0.30 for a severe-IL
    prospect (basis official_mlb_il, capped at MAX_IL_RISK_DISCOUNT=0.40). The
    consumer must apply what the card reports. Today apply_availability_adjustment
    re-clamps to MAX_RISK_DISCOUNT=0.12, so the card says 30% but the score takes 12%.

    NOTE: the 0.12-vs-0.40 magnitude is the owner's pending ruling; this test
    asserts only the consistency invariant (applied == reported), which is
    violated either way.
    """
    profile = {
        "risk_discount": 0.30, "risk_basis": "official_mlb_il",
        "status": "injured", "risk_level": "high", "sample": 220.0,
    }
    assert profile["risk_discount"] <= MAX_IL_RISK_DISCOUNT
    adjusted, components = apply_availability_adjustment(100.0, {}, profile)
    reported = components["availability"]["risk_discount"]
    applied = round(1.0 - adjusted / 100.0, 4)
    assert applied == reported == profile["risk_discount"], (
        f"reported {reported} / applied {applied} / profile {profile['risk_discount']}"
    )


# --------------------------------------------------------------------------- #
# D (HIGH) — INV-GRADFLOOR-1: a graduated player who retains a prospect value
# must have the transition floor reach his served MLB row. Freshly-graduated
# active-roster archetype. Driven through the REAL build_snapshot path.
# --------------------------------------------------------------------------- #
def _build_active_roster_graduate_snapshot():
    """Drive the real build_snapshot with a Guzman-style active-roster graduate.

    700001 (Guzman): retained 53.17 on active_mlb_roster_board, thin 2.97 MLB-layer
            row, on the active roster -> must be floored (D's target population:
            in active_mlb_ids AND in mlb_identity_ids AND not in graduated_ids).
    800001 (Active Bridge): main board, active roster, NO mlb row -> active bridge.
    800002 (Grad Bridge): active_mlb_roster_board, active roster, NO mlb row ->
            graduated bridge. Gives callup_bridge_rows = 2 (active+graduated) so the
            telemetry fix (F) is exercised on the same build.
    No debut date -> floor decays on the rookie-ratio fallback (ratio 0 -> decay 0).
    """
    snap = _load_snapshot_module()
    prospect_rank = {
        "generated_at": "2026-06-27",
        "board": [
            {"mlbam_id": "800001", "name": "Active Bridge", "role": "hitter",
             "score": 40.0, "rank": 1, "level": "AAA"},
        ],
        "active_mlb_roster_board": [
            {"mlbam_id": "700001", "name": "Denzer Guzman", "role": "hitter",
             "score": 53.17, "rank": 90, "level": "AAA"},
            {"mlbam_id": "800002", "name": "Grad Bridge", "role": "hitter",
             "score": 35.0, "rank": 95, "level": "AAA"},
        ],
    }
    mlb_layer = {
        "generated_at": "2026-06-27",
        "players": [
            {"mlbam_id": "700001", "name": "Denzer Guzman", "role": "hitter",
             "value": 2.97, "rank": 500, "positions": ["SS"]},
        ],
    }
    mlb_roster_status = {"profiles": [
        {"mlbam_id": "700001", "active_mlb_roster": True},
        {"mlbam_id": "800001", "active_mlb_roster": True},
        {"mlbam_id": "800002", "active_mlb_roster": True},
    ]}
    return snap.build_snapshot(
        prospect_rank, mlb_layer=mlb_layer, mlb_roster_status=mlb_roster_status,
        generated_at="2026-06-27",
    )


def test_D_grad_floor_reaches_active_roster_graduate_with_mlb_row():
    """INV-GRADFLOOR-1. Denzer Guzman case: 53.17 retained, thin 2.97 MLB row,
    evicted from the main board AND skipped by graduated_callup_bridge_rows
    (already in the MLB layer). The floor must still reach his served MLB row.

    Real-wiring gate: drives build_snapshot end-to-end and asserts (a) the served
    MLB row is floored above the thin 2.97, (b) graduation_transition.applied is
    True for him, (c) the snapshot-level grad floor count is non-zero. Pre-fix
    (floor source omits graduated_floor_extra_rows) all three fail -> this gates
    the shipped fix, it does not restate it.
    """
    payload = _build_active_roster_graduate_snapshot()
    guzman = [p for p in payload["players"] if p.get("mlbam_id") == "700001"]
    assert len(guzman) == 1, f"expected one served Guzman row, got {len(guzman)}"
    row = guzman[0]
    assert row["player_type"] == "mlb"
    assert row["value"] > 2.97, (
        f"Guzman served at {row['value']} despite 53.17 retained value — "
        f"floor source omits the active-roster graduate"
    )
    assert (row.get("graduation_transition") or {}).get("applied") is True, (
        "graduation_transition.applied is not True for the active-roster graduate"
    )
    assert payload["validation"]["graduation_transition_floor_count"] >= 1, (
        "grad_floor_count=0 — the floor reached no one"
    )


# --------------------------------------------------------------------------- #
# E (MEDIUM) — INV-BADLINE-1: a sub-floor current line (IP<10) cannot be ruled
# "bad" and pull a score. Thin-gaudy/blowup archetype (symmetric to hitter floor).
# --------------------------------------------------------------------------- #
def test_E_tiny_pitcher_blowup_is_not_bad_line():
    """INV-BADLINE-1. The pitcher egregious branch (era>=7.50 or k_bb<=0) returns
    True BEFORE the ip<10 floor; the hitter branch floors first ('1 PA .000 = noise').
    A 2-IP blowup must not read as a bad line.
    """
    tiny_blowup = {"era": 27.0, "whip": 3.00, "k_bb_pct": 0.0, "innings_pitched": 2.0}
    assert _current_line_is_bad(tiny_blowup, "pitcher") is False, (
        "2-IP blowup classified bad: egregious branch precedes the IP floor"
    )


# --------------------------------------------------------------------------- #
# F (LOW, telemetry) — INV-TELEMETRY-1: reported bridge-row count == rows written.
# Driven through the REAL build path (shares the build with D).
# --------------------------------------------------------------------------- #
def test_F_bridge_row_count_matches_written():
    """INV-TELEMETRY-1. Validation must report the count of callup-bridge rows
    actually written to the snapshot (active + graduated), not just the active
    subset. The shared build writes 2 bridge rows (one active, one graduated);
    pre-fix telemetry reported len(active_callup_bridge_rows)=1.

    Real-wiring gate: count the bridge rows actually present in the served players
    and assert the reported count equals it — tied to served reality, not a
    restated arithmetic identity.
    """
    payload = _build_active_roster_graduate_snapshot()
    written = [p for p in payload["players"] if p.get("active_mlb_callup_bridge") is True]
    reported = payload["validation"]["active_mlb_callup_bridge_count"]
    assert reported == len(written), (
        f"telemetry reports {reported} callup-bridge rows but {len(written)} were "
        f"written to the snapshot"
    )
    # Guard the archetype actually exercises both bridge populations (active +
    # graduated), so the test can't pass by both sides being trivially equal at 0.
    assert len(written) == 2, (
        f"expected 2 written bridge rows (1 active + 1 graduated), got {len(written)}"
    )


# --------------------------------------------------------------------------- #
# G (LOW) — INV-NORM-1: equal raw scores -> equal normalized scores (no tie-split
# by mlbam_id). Role-count-imbalanced/tie archetype.
# --------------------------------------------------------------------------- #
def test_G_tied_raw_scores_get_equal_percentile():
    """INV-NORM-1. Two hitters with identical raw expected_outcome_score must get
    an identical percentile (and therefore an identical normalized score). Today
    the percentile sort tiebreaks on mlbam_id, so tied rows get consecutive
    percentiles (the lower id deflated). The fix assigns tie blocks a shared
    mean-rank percentile. Asserting on percentile is faithful: the normalized
    value can mask the split when the pooled distribution is locally flat, but the
    percentile split is always present and is what corrupts the served score when
    the pool has spread.
    """
    field = "expected_outcome_score"
    pct_key = _model_score_field_percentile_key(field)
    vals = [0.05, 0.12, 0.23, 0.34, 0.41, 0.50, 0.50, 0.63, 0.74, 0.88, 0.96]
    rows = [{"mlbam_id": i, "role": "hitter", field: v} for i, v in enumerate(vals, start=1)]

    _apply_role_quantile_model_score_normalization(rows)
    tied = {r["mlbam_id"]: r.get(pct_key) for r in rows if r[field] == 0.50}
    assert len(set(tied.values())) == 1, f"equal raw 0.50 -> unequal percentile {tied}"


# --------------------------------------------------------------------------- #
# Moderate-thin haircut — INV-THIN-2: a NO-PEDIGREE thin scored line (its own
# model reliability below the floor, but NOT availability-flagged
# thin_current_sample, so B never fires) takes a confidence haircut; a PEDIGREED
# thin line does not (its value has independent support). Closes the gap below B
# that put Ronny Hernandez (94 PA, rel 32) at #18 vs consensus #460, without
# burying pedigreed thin prospects (Willits, consensus #3). Mutually exclusive
# with B; full-sample leans (reliability >= floor) untouched by the zero-anchor.
# --------------------------------------------------------------------------- #
def _moderate_thin_penalty(
    reliability, pedigree=False, career_entry=None, draft_year=None, current_season=None
):
    input_row = {"mlbam_id": 2, "role": "hitter", "level": "A+"}
    if pedigree:
        input_row["draft_pick_number"] = 1  # 1-1 pick -> _high_pedigree
    if draft_year is not None:
        input_row["draft_year"] = draft_year
    factual = {"source_kind": "current_season"}
    if current_season is not None:
        factual["sample_season"] = current_season  # drives pedigree-staleness decay
    components = {
        # status != "thin_current_sample" so B's haircut does NOT fire (this is the gap).
        "availability": {"sample": 94.0, "sample_unit": "PA", "status": "available"},
        "factual_current_context": factual,
        "sample_reliability": reliability,
    }
    _, out = _bucket_calibration_adjustment(
        score=50.0, source="prospect_model_v0_6", layer_profile={"role": "hitter"},
        input_row=input_row, universe_row={"role": "hitter"}, components=components,
        career_entry=career_entry,
    )
    for rule in (out.get("bucket_calibration", {}) or {}).get("rules", []):
        if rule["bucket"] == "moderate_thin_sample_confidence":
            return abs(float(rule["adjustment"]))
    return 0.0


# A multi-year prior track record of durable contact + discipline (K% <= 15, BB% >= 10
# over >= 2 prior seasons and >= 250 PA). Sibling of pedigree: the thin current line
# continues a proven skill the point-estimate model is blind to, so the haircut softens.
_CAREER_VALIDATED = {
    "current_season": 2026,
    "rows": [
        {"season": 2025, "plate_appearances": 300, "k_pct": 13.0, "bb_pct": 11.0, "role": "hitter"},
        {"season": 2024, "plate_appearances": 300, "k_pct": 12.0, "bb_pct": 12.0, "role": "hitter"},
    ],
}
# Ronny Hernandez's REAL prior A-ball lines: elite walks but contact regressed (21.1% K
# in 2025), so PA-weighted prior K% is 17.4 -- above the 15% gate. The current 7.4% K on
# 94 PA is a spike above his own career rate, exactly what we should stay skeptical of.
_CAREER_UNVALIDATED = {
    "current_season": 2026,
    "rows": [
        {"season": 2025, "plate_appearances": 355, "k_pct": 21.1, "bb_pct": 12.7, "role": "hitter"},
        {"season": 2024, "plate_appearances": 413, "k_pct": 14.3, "bb_pct": 15.0, "role": "hitter"},
    ],
}


def test_moderate_thin_hits_no_pedigree_thin_line():
    """INV-THIN-2. A no-pedigree thin scored line (rel below the floor, not
    flagged thin_current_sample) takes the haircut -- the value can't ride a thin
    gaudy sample at face value into the top tier."""
    assert _moderate_thin_penalty(reliability=32.0) > 0.0


def test_moderate_thin_spares_pedigreed_thin_prospect():
    """INV-THIN-2. A pedigreed thin prospect (1-1 pick) is spared: its value has
    independent support, so we don't dock a Willits-type consensus darling."""
    assert _moderate_thin_penalty(reliability=32.0, pedigree=True) == 0.0


def test_moderate_thin_zero_at_floor():
    """INV-THIN-2. Reliability at/above the floor (a full-sample lean) is untouched
    -- the haircut is zero-anchored at the floor, so leans never move."""
    assert _moderate_thin_penalty(reliability=55.0) == 0.0


def test_moderate_thin_career_validated_softens_haircut():
    """INV-THIN-3. A thin line that continues a proven multi-year contact/discipline
    skill (K% <= 15, BB% >= 10 over >= 2 prior seasons) keeps a SOFTENED haircut --
    the career is real evidence the point estimate is blind to, so the thin sample is
    more trustworthy than its size alone implies."""
    base = _moderate_thin_penalty(reliability=32.0)
    softened = _moderate_thin_penalty(reliability=32.0, career_entry=_CAREER_VALIDATED)
    assert 0.0 < softened < base
    assert softened == pytest.approx(round(base * MODERATE_THIN_CAREER_SOFTENER, 2))


def test_moderate_thin_unvalidated_career_keeps_full_haircut():
    """INV-THIN-3. The Hernandez case: elite career walks but contact regressed
    (PA-weighted prior K% 17.4 > 15 gate), so the career does NOT validate the current
    thin contact spike -- the full haircut stands and we don't over-credit the line."""
    base = _moderate_thin_penalty(reliability=32.0)
    unsoftened = _moderate_thin_penalty(reliability=32.0, career_entry=_CAREER_UNVALIDATED)
    assert unsoftened == base


def test_pedigree_spare_full_when_fresh():
    """INV-THIN-4. A FRESH draft pedigree (1 yr post-draft) still fully spares the
    haircut -- the pro sample is naturally thin, so the draft slot is the independent
    support the value rests on (the Willits-type consensus darling we don't dock)."""
    assert (
        _moderate_thin_penalty(
            reliability=32.0, pedigree=True, draft_year=2025, current_season=2026
        )
        == 0.0
    )


def test_pedigree_spare_decays_to_full_haircut_when_stale():
    """INV-THIN-4. A STALE pedigree (>= 5 yrs post-draft) gets NO spare -- the pro
    record is now the evidence, so the draft slot is no longer independent support and
    the full haircut applies, same as a no-pedigree thin line."""
    base = _moderate_thin_penalty(reliability=32.0)
    stale = _moderate_thin_penalty(
        reliability=32.0, pedigree=True, draft_year=2020, current_season=2026
    )
    assert stale == base


def test_pedigree_spare_partial_when_midstale():
    """INV-THIN-4. The Hughes case: a 4-yr-stale top-10 pick gets a PARTIAL spare --
    pedigree decayed to ~1/3, so ~2/3 of the haircut applies. Nudges him down without
    fully erasing the pedigree credit a fresh pick would keep."""
    base = _moderate_thin_penalty(reliability=32.0)
    mid = _moderate_thin_penalty(
        reliability=32.0, pedigree=True, draft_year=2022, current_season=2026
    )
    assert 0.0 < mid < base
    assert mid == pytest.approx(round(base * (2.0 / 3.0), 2))
