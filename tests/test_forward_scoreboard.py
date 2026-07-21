"""Tests for the forward-ledger scoreboard roll-up + validator (plan 030, S2).

The fixture ledger + mini-archive exercise EVERY pool branch defined in plan 030
A4, with the sign of each contribution verified per claim side. The direction
convention is the frozen ledger's (`gaps_claim_ledger._resolve_claim`): a SMALLER
consensus rank is a better board position, so —

  higher side (we rank him ABOVE the field): the field moving AWAY means it faded
    him FURTHER -> consensus grew (end > start).
  lower side (we FADE him vs the field): the field moving AWAY means it caught up
    to him -> consensus shrank (end < start).

Adverse movement fires at exactly ADVERSE_MOVE_FLOOR_SPOTS (10), inclusive, matching
the ledger's `>=` floor convention.
"""
from __future__ import annotations

import json

import numpy as np

import scripts.validate_forward_scoreboard as validate
from prospects.forward_scoreboard import (
    ADVERSE_MOVE_FLOOR_SPOTS,
    INDEPENDENCE_ATTESTATION,
    RESAMPLE_SEED,
    VERDICT_BASIS,
    _binomial_tail_ge,
    _bootstrap_ci,
    _headline,
    _sign_test,
    build_scoreboard,
)

GENERATED_AT = "2026-07-16T00:00:00+00:00"


def _claim(identity_key, side, outcome, claim_date, resolved_date=None, **extra):
    claim = {
        "identity_key": identity_key,
        "side": side,
        "outcome": outcome,
        "claim_date": claim_date,
        "name": extra.get("name", "Fixture Player"),
        "mlbam_id": identity_key.split("_")[0],
        "role": extra.get("role", "hitter"),
        "team": "BOS",
    }
    if resolved_date is not None:
        claim["resolved_date"] = resolved_date
    return claim


def _board_row(mlbam_id, role, consensus_pair):
    """A board row whose two external boards yield `consensus_pair` as the rounded
    median (pass the same value twice for an exact median)."""
    lo, hi = consensus_pair
    return {
        "mlbam_id": mlbam_id,
        "role": role,
        "name": "Fixture Player",
        "rank": lo,
        "mlb_team": "BOS",
        "context_only": {"source_ranks": {"hkb": lo, "pl": hi}},
    }


def _archive_with(identity_ranks):
    """Build a mini-archive: {date: {identity_key: consensus_median}} -> board rows.
    `identity_ranks` = {date: {identity_key: median}} where each median is emitted as
    a symmetric two-board pair so the reconstructed consensus equals it exactly."""
    archive: dict[str, list[dict]] = {}
    for date, by_key in identity_ranks.items():
        rows = []
        for identity_key, median in by_key.items():
            mlbam_id, role = identity_key.split("_")
            rows.append(_board_row(mlbam_id, role, (median, median)))
        archive[date] = rows
    return archive


def _scoreboard(claims, archive=None, registry=None):
    ledger = {"claims": claims, "signal_version": "0.1.0", "generated_at": GENERATED_AT}
    return build_scoreboard(
        ledger=ledger,
        archive=archive or {},
        registry=registry,
        generated_at=GENERATED_AT,
    )


def _buckets(scoreboard):
    return scoreboard["funnel"]["buckets"]


# --- Win branches -------------------------------------------------------------

def test_higher_callup_is_a_positive_win():
    sb = _scoreboard([
        _claim("1_hitter", "higher", "resolved_by_callup", "2026-06-24", "2026-06-30"),
    ])
    assert _buckets(sb)["callup_win"] == 1
    assert sb["funnel"]["wins"] == 1
    # +6 days lead -> positive median.
    assert sb["anticipation_score"]["median_lead_days"] == 6.0


def test_consensus_move_win_both_sides_are_positive():
    # A consensus move is recorded by the ledger only TOWARD our rank, so it is a win
    # on EITHER side and contributes +days regardless.
    sb = _scoreboard([
        _claim("1_hitter", "higher", "resolved_by_consensus_move", "2026-06-24", "2026-07-06"),
        _claim("2_hitter", "lower", "resolved_by_consensus_move", "2026-06-24", "2026-07-14"),
    ])
    assert _buckets(sb)["consensus_move_win"] == 2
    assert sb["funnel"]["by_side"]["higher"]["consensus_move_win"] == 1
    assert sb["funnel"]["by_side"]["lower"]["consensus_move_win"] == 1
    # Both positive: median of {12, 20} = 16.
    assert sb["anticipation_score"]["median_lead_days"] == 16.0


# --- Loss branches ------------------------------------------------------------

def test_lower_callup_is_a_negative_loss():
    # A fade (lower side) whose player got called up: the field was right, we missed.
    sb = _scoreboard([
        _claim("1_hitter", "lower", "resolved_by_callup", "2026-06-24", "2026-06-30"),
    ])
    assert _buckets(sb)["callup_loss"] == 1
    assert sb["funnel"]["losses"] == 1
    assert sb["anticipation_score"]["median_lead_days"] == -6.0


def test_adverse_at_expiry_higher_side_is_a_loss():
    # Higher side: the field faded him FURTHER over the claim window (consensus grew
    # 100 -> 111, +11 >= floor) -> loss of -(days to expiry).
    archive = _archive_with({
        "2026-06-24": {"1_hitter": 100},
        "2026-08-23": {"1_hitter": 111},
    })
    sb = _scoreboard(
        [_claim("1_hitter", "higher", "expired_unresolved", "2026-06-24", "2026-08-23")],
        archive=archive,
    )
    assert _buckets(sb)["adverse_at_expiry"] == 1
    assert _buckets(sb)["benign_expiry"] == 0
    assert sb["anticipation_score"]["median_lead_days"] == -60.0  # 24 Jun -> 23 Aug


def test_benign_expiry_is_excluded_from_pool():
    # Higher side: the field did NOT move away (consensus fell 100 -> 95, i.e. TOWARD
    # us) -> benign expiry, excluded from the median but funnel-counted.
    archive = _archive_with({
        "2026-06-24": {"1_hitter": 100},
        "2026-08-23": {"1_hitter": 95},
    })
    sb = _scoreboard(
        [_claim("1_hitter", "higher", "expired_unresolved", "2026-06-24", "2026-08-23")],
        archive=archive,
    )
    assert _buckets(sb)["benign_expiry"] == 1
    assert _buckets(sb)["adverse_at_expiry"] == 0
    assert sb["funnel"]["pool_size"] == 0
    assert sb["anticipation_score"]["median_lead_days"] is None


def test_adverse_before_retraction_lower_side_is_a_loss():
    # Lower side: the field caught up to a player we faded (consensus fell 200 -> 190,
    # a 10-spot move AWAY from a fade) BEFORE we retracted -> loss, not clean.
    archive = _archive_with({
        "2026-06-24": {"1_hitter": 200},
        "2026-07-14": {"1_hitter": 190},
    })
    sb = _scoreboard(
        [_claim("1_hitter", "lower", "retracted_by_model_move", "2026-06-24", "2026-07-14")],
        archive=archive,
    )
    assert _buckets(sb)["adverse_before_retraction"] == 1
    assert _buckets(sb)["clean_retraction"] == 0
    assert sb["anticipation_score"]["median_lead_days"] == -20.0  # 24 Jun -> 14 Jul


def test_clean_retraction_is_excluded_from_pool():
    # Higher side retraction with NO adverse field move (consensus fell 100 -> 96,
    # toward us) -> clean self-correction, excluded from the median.
    archive = _archive_with({
        "2026-06-24": {"1_hitter": 100},
        "2026-07-14": {"1_hitter": 96},
    })
    sb = _scoreboard(
        [_claim("1_hitter", "higher", "retracted_by_model_move", "2026-06-24", "2026-07-14")],
        archive=archive,
    )
    assert _buckets(sb)["clean_retraction"] == 1
    assert _buckets(sb)["adverse_before_retraction"] == 0
    assert sb["funnel"]["pool_size"] == 0


def test_open_claim_is_excluded_from_pool():
    sb = _scoreboard([_claim("1_hitter", "higher", "open", "2026-07-14")])
    assert _buckets(sb)["open"] == 1
    assert sb["funnel"]["pool_size"] == 0
    assert sb["funnel"]["excluded_from_pool"] == 1


# --- Floor boundary (exactly 10 spots, inclusive) -----------------------------

def test_adverse_floor_is_inclusive_at_exactly_ten():
    assert ADVERSE_MOVE_FLOOR_SPOTS == 10
    # Higher side, consensus grew EXACTLY 10 (100 -> 110): adverse (>= floor).
    at_floor = _archive_with({
        "2026-06-24": {"1_hitter": 100},
        "2026-08-23": {"1_hitter": 110},
    })
    sb = _scoreboard(
        [_claim("1_hitter", "higher", "expired_unresolved", "2026-06-24", "2026-08-23")],
        archive=at_floor,
    )
    assert _buckets(sb)["adverse_at_expiry"] == 1

    # One spot under the floor (100 -> 109, +9): benign, excluded.
    under_floor = _archive_with({
        "2026-06-24": {"1_hitter": 100},
        "2026-08-23": {"1_hitter": 109},
    })
    sb2 = _scoreboard(
        [_claim("1_hitter", "higher", "expired_unresolved", "2026-06-24", "2026-08-23")],
        archive=under_floor,
    )
    assert _buckets(sb2)["benign_expiry"] == 1


# --- Missing player at an endpoint --------------------------------------------

def test_missing_endpoint_is_treated_as_not_adverse_and_counted():
    # No archive consensus at the expiry date (identity absent) -> cannot prove an
    # adverse move -> benign expiry, still funnel-counted (never silently dropped).
    archive = _archive_with({"2026-06-24": {"1_hitter": 100}})  # no 2026-08-23 entry
    sb = _scoreboard(
        [_claim("1_hitter", "higher", "expired_unresolved", "2026-06-24", "2026-08-23")],
        archive=archive,
    )
    assert _buckets(sb)["benign_expiry"] == 1
    assert sb["funnel"]["total_claims"] == 1
    assert sb["funnel"]["pool_size"] == 0


# --- Self-retraction rate + funnel reconciliation -----------------------------

def test_self_retraction_rate_and_funnel_reconcile():
    archive = _archive_with({
        "2026-06-24": {"1_hitter": 100, "2_hitter": 100},
        "2026-07-14": {"1_hitter": 96, "2_hitter": 96},
    })
    claims = [
        _claim("1_hitter", "higher", "retracted_by_model_move", "2026-06-24", "2026-07-14"),
        _claim("2_hitter", "higher", "retracted_by_model_move", "2026-06-24", "2026-07-14"),
        _claim("3_hitter", "higher", "resolved_by_callup", "2026-06-24", "2026-06-30"),
        _claim("4_hitter", "lower", "open", "2026-07-14"),
    ]
    sb = _scoreboard(claims, archive=archive)
    retraction = sb["funnel"]["self_retraction_rate"]
    assert retraction["retracted"] == 2
    assert retraction["total"] == 4
    assert retraction["rate"] == 0.5
    # Buckets sum to the ledger's total claim count (no survivorship).
    assert sum(_buckets(sb).values()) == 4
    # Per-side buckets also sum to the total (every claim carries a side).
    by_side = sb["funnel"]["by_side"]
    assert sum(v for s in by_side.values() for v in s.values()) == 4


# --- Determinism at the frozen seed -------------------------------------------

def test_ci_and_null_are_deterministic_at_seed():
    assert RESAMPLE_SEED == 29016
    claims = [
        _claim("1_hitter", "higher", "resolved_by_callup", "2026-06-24", "2026-06-30"),
        _claim("2_hitter", "higher", "resolved_by_consensus_move", "2026-06-24", "2026-07-06"),
        _claim("3_hitter", "lower", "resolved_by_consensus_move", "2026-06-24", "2026-07-14"),
    ]
    a = _scoreboard([dict(c) for c in claims])
    b = _scoreboard([dict(c) for c in claims])
    assert a["anticipation_score"] == b["anticipation_score"]
    assert a["content_sha256"] == b["content_sha256"]
    # CI is a real interval bracketing the point median.
    h = a["anticipation_score"]
    assert h["ci_low"] <= h["median_lead_days"] <= h["ci_high"]


def test_provisional_flag_true_before_first_expiry_window():
    # All claims young (< 60 days from generated_at) -> provisional headline.
    sb = _scoreboard([
        _claim("1_hitter", "higher", "resolved_by_callup", "2026-06-24", "2026-06-30"),
    ])
    assert sb["anticipation_score"]["provisional"] is True
    assert "provisional" in sb["anticipation_score"]["label"]


# --- Cohort section: pending when no registry ---------------------------------

def test_cohort_section_pending_without_registry():
    sb = _scoreboard([_claim("1_hitter", "higher", "open", "2026-07-14")])
    assert sb["cohorts"]["status"] == "pending"
    assert sb["cohorts"]["cohort_count"] == 0


def test_cohort_section_rolls_up_registry():
    registry = {
        "cohorts": {
            "2026-07-16": {
                "archive_date": "2026-07-15",
                "content_sha256": "abc123",
                "counts": {"eligible_total": 500, "consensus_covered": 460, "rank_only": 40},
            }
        }
    }
    sb = _scoreboard([_claim("1_hitter", "higher", "open", "2026-07-14")], registry=registry)
    assert sb["cohorts"]["status"] == "registered"
    assert sb["cohorts"]["cohort_count"] == 1
    assert sb["cohorts"]["cohorts"][0]["content_sha256"] == "abc123"


# --- No forbidden keys anywhere in the output ---------------------------------

def test_no_forbidden_keys_anywhere_in_output():
    archive = _archive_with({
        "2026-06-24": {"1_hitter": 100},
        "2026-07-14": {"1_hitter": 90},
    })
    sb = _scoreboard(
        [_claim("1_hitter", "lower", "retracted_by_model_move", "2026-06-24", "2026-07-14")],
        archive=archive,
    )
    assert validate._forbidden_key_paths(sb) == []


# --- Validator -----------------------------------------------------------------

def _write(tmp_path, payload):
    path = tmp_path / "scoreboard.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_validator_passes_on_a_clean_scoreboard(tmp_path):
    sb = _scoreboard([
        _claim("1_hitter", "higher", "resolved_by_callup", "2026-06-24", "2026-06-30"),
        _claim("2_hitter", "lower", "open", "2026-07-14"),
    ])
    payload, problems = validate.validate_forward_scoreboard(_write(tmp_path, sb))
    assert problems == [], problems
    assert payload is not None


def test_validator_rejects_a_role_field(tmp_path):
    sb = _scoreboard([_claim("1_hitter", "higher", "open", "2026-07-14")])
    # Smuggle a role field deep in the payload.
    sb["funnel"]["role"] = "hitter"
    _, problems = validate.validate_forward_scoreboard(_write(tmp_path, sb))
    assert any("forbidden key" in p and "role" in p for p in problems)


def test_validator_rejects_source_ranks(tmp_path):
    sb = _scoreboard([_claim("1_hitter", "higher", "open", "2026-07-14")])
    sb["anticipation_score"]["source_ranks"] = {"hkb": 10}
    _, problems = validate.validate_forward_scoreboard(_write(tmp_path, sb))
    assert any("forbidden key" in p and "source_ranks" in p for p in problems)


def test_validator_rejects_missing_attestation(tmp_path):
    sb = _scoreboard([_claim("1_hitter", "higher", "open", "2026-07-14")])
    sb["independence_attestation"] = "reworded"
    _, problems = validate.validate_forward_scoreboard(_write(tmp_path, sb))
    assert any("independence_attestation" in p for p in problems)


def test_validator_rejects_funnel_total_mismatch(tmp_path):
    sb = _scoreboard([_claim("1_hitter", "higher", "open", "2026-07-14")])
    sb["funnel"]["total_claims"] = 999  # no longer reconciles with the buckets
    _, problems = validate.validate_forward_scoreboard(_write(tmp_path, sb))
    assert any("total_claims" in p for p in problems)


def test_validator_rejects_an_inconsistent_sign_test_block(tmp_path):
    sb = _scoreboard([
        _claim("1_hitter", "higher", "resolved_by_callup", "2026-06-24", "2026-06-30"),
    ])
    sb["anticipation_score"]["verdict_basis"] = "wrong"
    sb["anticipation_score"]["sign_test"] = {
        "basis": "wrong",
        "positives": 999,
        "negatives": 0,
        "zeros_excluded": 0,
        "n_nonzero": 1,
        "p_value": -7.0,
        "direction": "leading",
        "significant": True,
    }

    _, problems = validate.validate_forward_scoreboard(_write(tmp_path, sb))

    assert any("verdict_basis" in problem for problem in problems)
    assert any("sign_test" in problem for problem in problems)


# --- FIX 4: unscored/unclassified derived view + partition reconciliation ------

def test_resolved_claim_missing_resolved_date_lands_in_unscored_view(tmp_path):
    # A resolved_by_callup claim with NO resolved_date cannot be dated, so it lands in
    # callup_unscored — a bucket that belongs to no win/loss/excluded view. The fourth
    # derived view `unscored_or_unclassified` must catch it, and the four views must
    # still partition the total (validator-asserted).
    sb = _scoreboard([
        _claim("1_hitter", "higher", "resolved_by_callup", "2026-06-24"),  # no resolved_date
        _claim("2_hitter", "higher", "open", "2026-07-14"),
    ])
    assert _buckets(sb)["callup_unscored"] == 1
    assert sb["funnel"]["unscored_or_unclassified"] == 1
    funnel = sb["funnel"]
    assert (
        funnel["wins"] + funnel["losses"]
        + funnel["excluded_from_pool"] + funnel["unscored_or_unclassified"]
        == funnel["total_claims"]
    )
    # The validator accepts it (the view keeps the partition whole).
    payload, problems = validate.validate_forward_scoreboard(_write(tmp_path, sb))
    assert problems == [], problems
    assert payload is not None


def test_validator_rejects_broken_partition_when_view_dropped(tmp_path):
    # Drop the unscored view on an artifact that needs it -> the partition no longer
    # sums to the total -> hard validator failure.
    sb = _scoreboard([
        _claim("1_hitter", "higher", "resolved_by_callup", "2026-06-24"),  # -> callup_unscored
    ])
    sb["funnel"]["unscored_or_unclassified"] = 0  # falsely zero out the view
    _, problems = validate.validate_forward_scoreboard(_write(tmp_path, sb))
    assert any("derived views" in p for p in problems)


# --- FIX 5: unknown-side tolerance --------------------------------------------

def test_unknown_side_lands_in_other_and_validation_passes(tmp_path):
    # A claim with side=None is not higher/lower; it must fall into by_side["other"]
    # so the per-side buckets still sum to the total (no spurious validator failure).
    sb = _scoreboard([_claim("1_hitter", None, "open", "2026-07-14")])
    by_side = sb["funnel"]["by_side"]
    assert "other" in by_side
    assert by_side["other"]["open"] == 1
    assert sum(v for s in by_side.values() for v in s.values()) == sb["funnel"]["total_claims"]
    payload, problems = validate.validate_forward_scoreboard(_write(tmp_path, sb))
    assert problems == [], problems
    assert payload is not None


# --- FIX 6: validator forbids known public source-name keys --------------------

def test_validator_rejects_a_leaked_public_source_key(tmp_path):
    # A per-source rank smuggled under a public source NAME (not source_ranks) is a
    # leak even if the container is renamed -> the key name itself is forbidden.
    sb = _scoreboard([_claim("1_hitter", "higher", "open", "2026-07-14")])
    sb["anticipation_score"]["pl"] = 98  # {"pl": 98} nested in the artifact
    _, problems = validate.validate_forward_scoreboard(_write(tmp_path, sb))
    assert any("forbidden key" in p and ".pl" in p for p in problems)


def test_attestation_string_is_the_frozen_text():
    assert INDEPENDENCE_ATTESTATION.startswith("ValuCast scores are computed without")
    assert "validator-enforced" in INDEPENDENCE_ATTESTATION


def test_null_is_a_context_interval_with_no_pvalue():
    claims = [
        _claim("1_hitter", "higher", "resolved_by_callup", "2026-06-24", "2026-06-30"),
        _claim("2_hitter", "higher", "resolved_by_consensus_move", "2026-06-24", "2026-07-06"),
    ]
    sb = _scoreboard(claims)
    null = sb["anticipation_score"]["null"]
    # null_median (0.0 by construction) + the null CI interval are published as
    # context; the degenerate p-value was removed before freeze.
    assert null["null_median"] == 0.0
    assert np.isfinite(null["null_ci_low"])
    assert np.isfinite(null["null_ci_high"])
    assert "p_value" not in null


def _iter_keys(obj):
    """Yield every dict key anywhere in a nested JSON-like structure."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _iter_keys(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_keys(value)


def test_permutation_null_block_never_carries_a_pvalue():
    # Defense in depth: no `p_value` key survives anywhere INSIDE the permutation
    # null block (the sign-permutation p-value is degenerate and was removed
    # pre-freeze). The verdict-gating sign test carries its OWN p_value, published
    # under anticipation_score.sign_test — that one is exact and load-bearing, so the
    # prohibition is scoped to the null block, not the whole artifact.
    sb = _scoreboard([
        _claim("1_hitter", "higher", "resolved_by_callup", "2026-06-24", "2026-06-30"),
        _claim("2_hitter", "lower", "resolved_by_consensus_move", "2026-06-24", "2026-07-14"),
    ])
    null = sb["anticipation_score"]["null"]
    assert "p_value" not in set(_iter_keys(null))
    # The exact binomial sign test DOES carry a p_value (the gate).
    assert "p_value" in sb["anticipation_score"]["sign_test"]


# --- Exact binomial sign-test gate --------------------------------------------

def test_binomial_tail_matches_hand_computed_values():
    # P(X >= 9 | 10, 0.5) = (C(10,9) + C(10,10)) / 1024 = (10 + 1) / 1024 = 11/1024.
    assert _binomial_tail_ge(9, 10) == 11 / 1024
    # P(X >= 7 | 10, 0.5) = (120 + 45 + 10 + 1) / 1024 = 176/1024.
    assert _binomial_tail_ge(7, 10) == 176 / 1024
    # Degenerate guards: n<=0 or k<=0 -> the whole mass, p = 1.0.
    assert _binomial_tail_ge(0, 10) == 1.0
    assert _binomial_tail_ge(5, 0) == 1.0


def test_sign_test_9_of_10_positive_is_significant():
    # 9 leading, 1 behind -> p = 11/1024 ~ 0.0107 < 0.025 in the LEADING direction.
    pool = np.array([1.0] * 9 + [-1.0], dtype=float)
    st = _sign_test(pool)
    assert st["positives"] == 9
    assert st["negatives"] == 1
    assert st["zeros_excluded"] == 0
    assert st["p_value"] == 11 / 1024
    assert st["direction"] == "leading"
    assert st["significant"] is True
    assert st["basis"] == VERDICT_BASIS


def test_sign_test_7_of_10_positive_is_not_significant():
    # 7 leading, 3 behind -> p = 176/1024 ~ 0.172, NOT < 0.025.
    pool = np.array([1.0] * 7 + [-1.0] * 3, dtype=float)
    st = _sign_test(pool)
    assert st["positives"] == 7
    assert st["negatives"] == 3
    assert st["p_value"] == 176 / 1024
    assert st["direction"] == "leading"
    assert st["significant"] is False


def test_sign_test_9_of_10_negative_is_not_a_win():
    # A significant BEHIND majority (9 losses, 1 win) is NOT a win: same tail p, but
    # significant=False (only LEADING majorities clear the gate) and direction=behind.
    pool = np.array([-1.0] * 9 + [1.0], dtype=float)
    st = _sign_test(pool)
    assert st["p_value"] == 11 / 1024
    assert st["direction"] == "behind"
    assert st["significant"] is False


def test_headline_9_of_10_negative_reads_as_a_loss_not_a_win():
    # The honest label for a significant behind-majority: "behind, significant".
    pool_days = [-1.0] * 9 + [1.0]
    headline = _headline(pool_days, provisional=False)
    assert headline["label"] == "behind, significant"
    assert "leading" not in headline["label"]
    assert headline["sign_test"]["direction"] == "behind"


def test_headline_9_of_10_positive_is_significant():
    headline = _headline([1.0] * 9 + [-1.0], provisional=False)
    assert headline["label"] == "significant"
    assert headline["sign_test"]["significant"] is True
    assert headline["verdict_basis"] == VERDICT_BASIS


def test_headline_even_pool_is_not_labeled_leading():
    headline = _headline([1.0, -1.0], provisional=False)

    assert headline["sign_test"]["direction"] == "even"
    assert headline["label"] == "even, not yet significant"


def test_zero_dominated_pool_cannot_claim_a_significant_lead():
    headline = _headline([1.0] * 9 + [-1.0] + [0.0] * 100, provisional=False)

    assert headline["median_lead_days"] == 0.0
    assert headline["sign_test"]["significant"] is False
    assert headline["label"] == "leading, not yet significant"


def test_sign_test_excludes_and_discloses_zeros():
    # Exact-zero lead times (same-day timing) carry no sign: excluded from the test
    # counts, disclosed via zeros_excluded, and NOT counted toward n_nonzero.
    pool = np.array([1.0, 1.0, 1.0, 0.0, 0.0, -1.0], dtype=float)
    st = _sign_test(pool)
    assert st["positives"] == 3
    assert st["negatives"] == 1
    assert st["zeros_excluded"] == 2
    assert st["n_nonzero"] == 4
    # p = P(X >= 3 | 4, 0.5) = (C(4,3)+C(4,4))/16 = 5/16, not significant.
    assert st["p_value"] == 5 / 16
    assert st["significant"] is False


def test_bootstrap_ci_would_claim_significance_but_sign_test_does_not():
    # THE motivating case: a small, sign-imbalanced pool whose bootstrap CI sits
    # entirely ABOVE zero (old rule -> "significant"), yet the exact sign test does
    # NOT clear the 0.025 leading bar (new, more-conservative rule -> not yet).
    # 7 positives / 1 negative: every value positive-heavy enough that the bootstrap
    # median CI clears zero, but P(X>=7 | 8, 0.5) = 37/256 ~ 0.145 >> 0.025.
    pool_days = [5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, -1.0]
    pool = np.asarray(pool_days, dtype=float)
    ci_low, ci_high = _bootstrap_ci(pool)
    # Old gate: bootstrap CI clear of zero -> would have claimed significance.
    assert ci_low > 0, (ci_low, ci_high)
    # New gate: exact sign test does NOT reach significance.
    st = _sign_test(pool)
    assert st["positives"] == 7
    assert st["negatives"] == 1
    assert st["p_value"] == _binomial_tail_ge(7, 8)
    assert st["p_value"] > 0.025
    assert st["significant"] is False
    # And the published headline honestly reads "leading, not yet significant".
    headline = _headline(pool_days, provisional=False)
    assert headline["label"] == "leading, not yet significant"
    assert headline["ci_low"] > 0  # effect-size band still shown, just not gating


def test_headline_publishes_verdict_basis_and_sign_counts():
    headline = _headline([1.0, 2.0, -3.0], provisional=False)
    assert headline["verdict_basis"] == VERDICT_BASIS
    st = headline["sign_test"]
    assert set(st) >= {
        "basis", "positives", "negatives", "zeros_excluded",
        "n_nonzero", "p_value", "direction", "significant",
    }


def test_empty_pool_headline_carries_verdict_basis_and_null_sign_test():
    headline = _headline([], provisional=False)
    assert headline["sign_test"] is None
    assert headline["verdict_basis"] == VERDICT_BASIS


def test_behind_pool_inconclusive_label_is_direction_honest():
    # A pool with a NEGATIVE majority that does not clear the sign test must not
    # read as "leading": 4 wins / 6 losses -> p(X>=6|10,.5)=0.377, direction behind.
    from prospects.forward_scoreboard import _headline
    pool = [3.0, 2.0, 1.0, 4.0, -1.0, -2.0, -3.0, -4.0, -5.0, -6.0]
    headline = _headline(pool, provisional=False)
    assert headline["sign_test"]["direction"] == "behind"
    assert headline["sign_test"]["significant"] is False
    assert headline["label"] == "behind, not yet significant"
