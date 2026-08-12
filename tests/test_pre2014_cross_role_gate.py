import json
import multiprocessing
from copy import deepcopy

import pytest

from prospects.pre2014_cross_role_gate import (
    BOOTSTRAP_SEED,
    DIRECT_METRIC,
    assess_promotion_gates,
    derive_outer_folds,
    evaluate_pre2014_cross_role_gate,
    finalize_reserved_result,
    hierarchical_bootstrap_improvement,
    hierarchical_bootstrap_cross_role_concordance,
    reserve_and_load_outer_outcomes,
    reserve_result_path,
)


def _hold_result_byte_lock(path, ready, release):
    import os

    descriptor = os.open(path, os.O_RDWR)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ready.set()
        if not release.wait(10):
            raise TimeoutError("test did not release the reservation lock")
    finally:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _hold_run_lease_until_crash(path, token, ready, crash):
    import os

    from prospects.pre2014_cross_role_gate import sealed_result_run_lease

    with sealed_result_run_lease(path, token):
        ready.set()
        if not crash.wait(10):
            os._exit(18)
        os._exit(17)


def _passing_metrics():
    return {
        "direct_mae": {
            "incumbent": 0.100,
            "candidate": 0.090,
            "paired_improvement": 0.010,
            "relative_improvement": 0.10,
            "bootstrap_95_lower": 0.001,
        },
        "fold_relative_regressions": {2013: -0.10, 2014: 0.04},
        "role_direct_mae_relative_regressions": {
            "hitter": 0.005,
            "pitcher": -0.02,
        },
        "role_concordance_relative_regressions": {
            "hitter": -0.01,
            "pitcher": 0.005,
        },
        "top25_direct_regret": {"incumbent": 0.20, "candidate": 0.20},
        "top25_ordinal_regret": {"incumbent": 0.25, "candidate": 0.24},
        "cross_role_concordance": {
            "incumbent": 0.60,
            "candidate": 0.62,
            "relative_improvement": 0.02 / 0.40,
            "bootstrap_95_lower": 0.001,
        },
    }


def _fold_outputs():
    folds = []
    for cohort_year in (2017, 2018, 2019, 2021):
        players = []
        for role, target in (("hitter", 0.40), ("pitcher", 0.60)):
            for index in range(63):
                outcome_tier = (index % 3) / 2
                players.append(
                    {
                        "player_id": f"{cohort_year}-{role}-{index}",
                        "role": role,
                        "target_percentile_rank": target,
                        "incumbent_percentile_rank": target + 0.10,
                        "candidate_percentile_rank": target + 0.05,
                        "outcome_tier": outcome_tier,
                        "incumbent_score": 1.0 - outcome_tier,
                        "candidate_score": outcome_tier,
                    }
                )
        folds.append(
            {
                "cohort_year": cohort_year,
                "metric": DIRECT_METRIC,
                "players": players,
                "coverage_by_role": {
                    "hitter": {
                        "eligible_identity_count": 63,
                        "scored_outcome_count": 63,
                        "rate": 1.0,
                    },
                    "pitcher": {
                        "eligible_identity_count": 63,
                        "scored_outcome_count": 63,
                        "rate": 1.0,
                    },
                },
                "top25_direct_regret": {"incumbent": 0.20, "candidate": 0.19},
                "top25_ordinal_regret": {"incumbent": 0.25, "candidate": 0.24},
                "cross_role_concordance": {"incumbent": 0.0, "candidate": 1.0},
                "role_concordance": {
                    "hitter": {"incumbent": 0.0, "candidate": 1.0},
                    "pitcher": {"incumbent": 0.0, "candidate": 1.0},
                },
            }
        )
    return folds


def test_outer_folds_start_after_four_prior_years_stop_at_complete_outcomes_and_omit_declared():
    assert derive_outer_folds(
        range(2009, 2024),
        declared_omissions={2020},
        outcome_complete_through=2025,
    ) == (2017, 2018, 2019, 2021)


def test_hierarchical_bootstrap_is_deterministic_and_seeded():
    paired = {
        2013: [(0.08, 0.05), (0.09, 0.08), (0.07, 0.08), (0.10, 0.08)],
        2014: [(0.10, 0.08), (0.11, 0.07), (0.08, 0.07)],
        2015: [
            (0.09, 0.08),
            (0.10, 0.09),
            (0.11, 0.08),
            (0.12, 0.07),
            (0.07, 0.09),
        ],
        2016: [(0.10, 0.07), (0.09, 0.07), (0.11, 0.07)],
    }
    first = hierarchical_bootstrap_improvement(
        paired, seed=BOOTSTRAP_SEED, n_resamples=50
    )
    second = hierarchical_bootstrap_improvement(
        paired, seed=BOOTSTRAP_SEED, n_resamples=50
    )
    other_seed = hierarchical_bootstrap_improvement(
        paired, seed=BOOTSTRAP_SEED + 1, n_resamples=50
    )

    assert first == second
    assert first["draws"] != other_seed["draws"]
    assert first["seed"] == 35011
    assert first["resample_unit"] == "player_within_cohort_hierarchical"
    assert first["point_statistic"] == "relative_mae_improvement"
    incumbent = sum(pair[0] for rows in paired.values() for pair in rows)
    candidate = sum(pair[1] for rows in paired.values() for pair in rows)
    assert first["point"] == pytest.approx((incumbent - candidate) / incumbent)


def test_cross_role_bootstrap_recomputes_the_declared_concordance_statistic():
    folds = _fold_outputs()

    first = hierarchical_bootstrap_cross_role_concordance(
        folds, seed=BOOTSTRAP_SEED, n_resamples=40
    )
    second = hierarchical_bootstrap_cross_role_concordance(
        folds, seed=BOOTSTRAP_SEED, n_resamples=40
    )

    assert first == second
    assert first["point"] == pytest.approx(1.0)
    assert first["declared_point"] == pytest.approx(1.0)
    assert first["ci_lower"] > 0
    assert first["resample_unit"] == "cohort_then_identity_within_role"
    assert first["point_statistic"] == "incumbent_discordance_reduction"


@pytest.mark.parametrize(
    ("mutation", "failed_gate"),
    [
        (
            lambda metrics: metrics["direct_mae"].update(
                relative_improvement=0.019
            ),
            "direct_mae_relative_improvement",
        ),
        (
            lambda metrics: metrics["direct_mae"].update(bootstrap_95_lower=0.0),
            "paired_bootstrap_lower_bound",
        ),
        (
            lambda metrics: metrics["fold_relative_regressions"].update({2014: 0.051}),
            "outer_fold_regression",
        ),
        (
            lambda metrics: metrics["role_concordance_relative_regressions"].update(
                {"pitcher": 0.011}
            ),
            "role_concordance_regression",
        ),
        (
            lambda metrics: metrics["top25_direct_regret"].update(candidate=0.201),
            "top25_direct_regret",
        ),
        (
            lambda metrics: metrics["cross_role_concordance"].update(
                relative_improvement=0.019
            ),
            "cross_role_concordance",
        ),
        (
            lambda metrics: metrics["cross_role_concordance"].update(
                bootstrap_95_lower=0.0
            ),
            "cross_role_bootstrap_lower_bound",
        ),
        (
            lambda metrics: metrics["top25_ordinal_regret"].update(candidate=0.251),
            "top25_ordinal_regret",
        ),
    ],
)
def test_each_frozen_metric_gate_fails_closed(mutation, failed_gate):
    metrics = _passing_metrics()
    mutation(metrics)

    result = assess_promotion_gates(
        metrics, current_role_shape_governor_passed=True
    )

    assert result["production_review_authorized"] is False
    assert result["decision"] == "production_review_not_authorized"
    assert result["claim_authorized"] is False
    assert result["gates"][failed_gate]["passed"] is False
    assert failed_gate in result["blockers"]


def test_gate_authorizes_only_production_review_when_every_requirement_passes():
    result = assess_promotion_gates(
        _passing_metrics(), current_role_shape_governor_passed=True
    )

    assert result["decision"] == "production_review_authorized"
    assert result["production_review_authorized"] is True
    assert result["claim_authorized"] is False
    assert all(gate["passed"] for gate in result["gates"].values())


def test_current_role_shape_governor_is_required_before_production_review():
    result = assess_promotion_gates(
        _passing_metrics(), current_role_shape_governor_passed=False
    )

    assert result["production_review_authorized"] is False
    gate = result["gates"]["current_role_shape_governor"]
    assert gate["passed"] is False
    assert gate["threshold"]["check_id"] == "prospect_top_board_role_shape"
    assert gate["threshold"]["full_governor_required_at"] == (
        "post_look_pre_publication"
    )


def test_fold_evaluation_computes_primary_metric_and_passes_complete_fixture():
    result = evaluate_pre2014_cross_role_gate(
        _fold_outputs(),
        cohort_years=range(2009, 2022),
        declared_omissions={2020},
        current_role_shape_governor_passed=True,
        bootstrap_resamples=50,
    )

    assert result["readiness"]["passed"] is True
    assert result["readiness"]["outer_folds"] == [2017, 2018, 2019, 2021]
    assert result["readiness"]["unique_players_by_role"] == {
        "hitter": 252,
        "pitcher": 252,
    }
    assert result["metrics"]["direct_mae"]["incumbent"] == pytest.approx(0.10)
    assert result["metrics"]["direct_mae"]["candidate"] == pytest.approx(0.05)
    assert result["production_review_authorized"] is True
    assert result["claim_authorized"] is False


def test_readiness_stops_before_metrics_when_fold_set_or_role_sample_is_incomplete():
    folds = _fold_outputs()[:-1]
    for fold in folds:
        fold["players"] = [
            player for player in fold["players"] if player["role"] == "hitter"
        ]

    result = evaluate_pre2014_cross_role_gate(
        folds,
        cohort_years=range(2009, 2022),
        declared_omissions={2020},
        current_role_shape_governor_passed=True,
        bootstrap_resamples=10,
    )

    assert result["readiness"]["passed"] is False
    assert result["metrics"] is None
    assert result["production_review_authorized"] is False
    assert result["claim_authorized"] is False
    assert "outer_fold_set_mismatch" in result["readiness"]["blockers"]
    assert "minimum_unique_pitcher_players" in result["readiness"]["blockers"]


def test_readiness_fails_closed_below_fold_role_coverage_floor():
    folds = _fold_outputs()
    folds[0]["coverage_by_role"]["pitcher"] = {
        "eligible_identity_count": 70,
        "scored_outcome_count": 63,
        "rate": 0.9,
    }
    folds[1]["coverage_by_role"]["hitter"] = {
        "eligible_identity_count": 71,
        "scored_outcome_count": 63,
        "rate": 63 / 71,
    }

    result = evaluate_pre2014_cross_role_gate(
        folds,
        cohort_years=range(2009, 2022),
        declared_omissions={2020},
        current_role_shape_governor_passed=True,
        bootstrap_resamples=10,
    )

    assert result["readiness"]["passed"] is False
    assert "minimum_fold_role_coverage" in result["readiness"]["blockers"]
    assert result["metrics"] is None


def test_readiness_rejects_coverage_counts_that_do_not_match_scored_players():
    folds = _fold_outputs()
    folds[0]["coverage_by_role"]["hitter"]["scored_outcome_count"] = 62

    result = evaluate_pre2014_cross_role_gate(
        folds,
        cohort_years=range(2009, 2022),
        declared_omissions={2020},
        current_role_shape_governor_passed=True,
        bootstrap_resamples=10,
    )

    assert result["readiness"]["passed"] is False
    assert "invalid_fold_role_coverage" in result["readiness"]["blockers"]


def test_reservation_is_exclusive_and_final_result_cannot_be_overwritten(tmp_path):
    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")

    marker = json.loads(result_path.read_text(encoding="utf-8"))
    assert marker == {
        "reservation_id": "fixed-token",
        "status": "reserved_before_outer_outcomes",
    }
    with pytest.raises(FileExistsError):
        reserve_result_path(result_path, reservation_id="second-token")

    finalize_reserved_result(
        result_path,
        token,
        {"decision": "production_review_not_authorized", "claim_authorized": False},
    )
    committed = result_path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        finalize_reserved_result(
            result_path,
            token,
            {"decision": "production_review_authorized"},
        )
    assert result_path.read_text(encoding="utf-8") == committed


def test_reservation_write_failure_never_leaves_a_partial_result_marker(
    tmp_path, monkeypatch
):
    import prospects.pre2014_cross_role_gate as gate

    result_path = tmp_path / "sealed-result.json"

    def fail_serialization(*_args, **_kwargs):
        raise RuntimeError("injected reservation serialization failure")

    monkeypatch.setattr(gate.json, "dump", fail_serialization)

    with pytest.raises(RuntimeError, match="injected reservation"):
        reserve_result_path(result_path, reservation_id="fixed-token")

    assert not result_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_reservation_rejects_unsafe_token_before_creating_files(tmp_path):
    result_path = tmp_path / "sealed-result.json"

    with pytest.raises(ValueError, match="reservation_id"):
        reserve_result_path(result_path, reservation_id="../other-result")

    assert list(tmp_path.iterdir()) == []


def test_successful_finalization_leaves_no_lock_or_temporary_residue(tmp_path):
    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")

    finalize_reserved_result(
        result_path,
        token,
        {"decision": "production_review_not_authorized"},
    )

    assert not result_path.with_name(result_path.name + ".finalizing").exists()
    assert list(tmp_path.glob(f"{result_path.name}.*.tmp")) == []


def test_finalization_recovers_exact_same_reservation_crash_residue(tmp_path):
    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")
    lock_path = result_path.with_name(result_path.name + ".finalizing")
    deterministic_temp = result_path.with_name(result_path.name + f".{token}.tmp")
    random_reservation_temp = result_path.with_name(
        f".{result_path.name}.{token}.reserve.crashed.tmp"
    )
    random_finalization_temp = result_path.with_name(
        f".{result_path.name}.{token}.finalize.crashed.tmp"
    )
    other_token_temp = result_path.with_name(
        f".{result_path.name}.other-token.finalize.crashed.tmp"
    )
    neighbor_temp = result_path.with_name(
        f".other-result.json.{token}.finalize.crashed.tmp"
    )
    lock_path.write_text(token, encoding="utf-8")
    deterministic_temp.write_text("partial", encoding="utf-8")
    random_reservation_temp.write_text("partial", encoding="utf-8")
    random_finalization_temp.write_text("partial", encoding="utf-8")
    other_token_temp.write_text("do not delete", encoding="utf-8")
    neighbor_temp.write_text("do not delete", encoding="utf-8")

    finalize_reserved_result(
        result_path,
        token,
        {"decision": "production_review_not_authorized"},
    )

    committed = json.loads(result_path.read_text(encoding="utf-8"))
    assert committed["decision"] == "production_review_not_authorized"
    assert committed["reservation_id"] == token
    assert not lock_path.exists()
    assert not deterministic_temp.exists()
    assert not random_reservation_temp.exists()
    assert not random_finalization_temp.exists()
    assert other_token_temp.read_text(encoding="utf-8") == "do not delete"
    assert neighbor_temp.read_text(encoding="utf-8") == "do not delete"


def test_finalization_does_not_delete_mismatched_or_neighbor_residue(tmp_path):
    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")
    lock_path = result_path.with_name(result_path.name + ".finalizing")
    lock_path.write_text("other-token", encoding="utf-8")
    own_temp = result_path.with_name(result_path.name + f".{token}.tmp")
    other_temp = result_path.with_name(result_path.name + ".other-token.tmp")
    neighbor_temp = result_path.with_name("other-result.json.fixed-token.tmp")
    own_temp.write_text("partial", encoding="utf-8")
    other_temp.write_text("do not delete", encoding="utf-8")
    neighbor_temp.write_text("do not delete", encoding="utf-8")

    with pytest.raises(FileExistsError):
        finalize_reserved_result(
            result_path,
            token,
            {"decision": "production_review_not_authorized"},
        )

    assert lock_path.read_text(encoding="utf-8") == "other-token"
    assert own_temp.exists()
    assert other_temp.read_text(encoding="utf-8") == "do not delete"
    assert neighbor_temp.read_text(encoding="utf-8") == "do not delete"


def test_finalization_does_not_reap_a_live_same_reservation_owner(tmp_path):
    import os

    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")
    lock_path = result_path.with_name(result_path.name + ".finalizing")
    lock_payload = {
        "artifact": "valucast_sealed_finalization_lock",
        "owner_nonce": "active-owner",
        "owner_pid": os.getpid(),
        "reservation_id": token,
        "schema_version": 1,
    }
    lock_path.write_text(
        json.dumps(lock_payload, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary = result_path.with_name(result_path.name + f".{token}.tmp")
    temporary.write_text("do not delete", encoding="utf-8")

    with pytest.raises(FileExistsError, match="active finalization"):
        finalize_reserved_result(
            result_path,
            token,
            {"decision": "production_review_not_authorized"},
        )

    assert json.loads(lock_path.read_text(encoding="utf-8")) == lock_payload
    assert temporary.read_text(encoding="utf-8") == "do not delete"


def test_finalization_reaps_a_dead_same_reservation_owner(tmp_path):
    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")
    lock_path = result_path.with_name(result_path.name + ".finalizing")
    lock_path.write_text(
        json.dumps(
            {
                "artifact": "valucast_sealed_finalization_lock",
                "owner_nonce": "dead-owner",
                "owner_pid": 2_147_483_647,
                "reservation_id": token,
                "schema_version": 1,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    finalize_reserved_result(
        result_path,
        token,
        {"decision": "production_review_not_authorized"},
    )

    assert not lock_path.exists()
    assert json.loads(result_path.read_text(encoding="utf-8"))["reservation_id"] == token


@pytest.mark.parametrize("forbidden_rewrite", ["ftruncate", "write"])
def test_recovered_lock_is_never_rewritten_in_place(
    tmp_path, monkeypatch, forbidden_rewrite
):
    import prospects.pre2014_cross_role_gate as gate

    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")
    lock_path = result_path.with_name(result_path.name + ".finalizing")
    lock_path.write_text(token, encoding="utf-8")

    def fail_rewrite(*_args, **_kwargs):
        raise RuntimeError("injected lock-record rewrite crash")

    monkeypatch.setattr(gate.os, forbidden_rewrite, fail_rewrite)

    finalize_reserved_result(
        result_path,
        token,
        {"decision": "production_review_not_authorized"},
    )

    assert not lock_path.exists()
    assert json.loads(result_path.read_text(encoding="utf-8"))["reservation_id"] == token


def test_concurrent_reservation_owner_serializes_stale_lock_recovery(tmp_path):
    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")
    lock_path = result_path.with_name(result_path.name + ".finalizing")
    lock_path.write_text(token, encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    owner = context.Process(
        target=_hold_result_byte_lock,
        args=(result_path, ready, release),
    )
    owner.start()
    assert ready.wait(10), "concurrent reservation owner did not acquire its lock"
    try:
        with pytest.raises(FileExistsError, match="active finalization"):
            finalize_reserved_result(
                result_path,
                token,
                {"decision": "production_review_not_authorized"},
            )
    finally:
        release.set()
        owner.join(10)
        if owner.is_alive():
            owner.terminate()
            owner.join(10)
    assert owner.exitcode == 0
    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "reservation_id": token,
        "status": "reserved_before_outer_outcomes",
    }
    assert lock_path.read_text(encoding="utf-8") == token

    finalize_reserved_result(
        result_path,
        token,
        {"decision": "production_review_not_authorized"},
    )
    assert not lock_path.exists()


def test_run_lease_is_invocation_exclusive_and_recovers_after_process_crash(
    tmp_path,
):
    from prospects.pre2014_cross_role_gate import sealed_result_run_lease

    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")
    lease_path = result_path.with_name(result_path.name + ".running")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    crash = context.Event()
    owner = context.Process(
        target=_hold_run_lease_until_crash,
        args=(result_path, token, ready, crash),
    )
    owner.start()
    assert ready.wait(10), "run owner did not acquire its lease"
    try:
        with pytest.raises(FileExistsError, match="active sealed run"):
            with sealed_result_run_lease(result_path, token):
                pytest.fail("a second invocation entered the sealed run")
    finally:
        crash.set()
        owner.join(10)
        if owner.is_alive():
            owner.terminate()
            owner.join(10)
    assert owner.exitcode == 17
    assert lease_path.exists()

    with sealed_result_run_lease(result_path, token) as leased_token:
        assert leased_token == token
        assert lease_path.exists()

    assert not lease_path.exists()


def test_run_lease_preserves_a_mismatched_reservation_lock(tmp_path):
    from prospects.pre2014_cross_role_gate import sealed_result_run_lease

    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")
    lease_path = result_path.with_name(result_path.name + ".running")
    lease_path.write_text("other-token", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not reservation-bound"):
        with sealed_result_run_lease(result_path, token):
            pytest.fail("mismatched lease was reaped")

    assert lease_path.read_text(encoding="utf-8") == "other-token"


def test_run_lease_releases_after_final_result_replaces_reservation(tmp_path):
    from prospects.pre2014_cross_role_gate import sealed_result_run_lease

    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")

    with sealed_result_run_lease(result_path, token):
        finalize_reserved_result(
            result_path,
            token,
            {"decision": "production_review_not_authorized"},
        )

    committed = json.loads(result_path.read_text(encoding="utf-8"))
    assert committed["reservation_id"] == token
    assert not result_path.with_name(result_path.name + ".running").exists()
    assert not result_path.with_name(result_path.name + ".finalizing").exists()


def test_post_publish_run_lease_cleanup_failure_does_not_report_run_failure(
    tmp_path, monkeypatch
):
    import prospects.pre2014_cross_role_gate as gate

    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")
    lease_path = result_path.with_name(result_path.name + ".running")
    original_unlink = gate.Path.unlink

    with gate.sealed_result_run_lease(result_path, token):

        def fail_lease_cleanup_once(path, *args, **kwargs):
            if path == lease_path:
                monkeypatch.setattr(gate.Path, "unlink", original_unlink)
                raise OSError("injected post-publish lease cleanup failure")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(gate.Path, "unlink", fail_lease_cleanup_once)
        finalize_reserved_result(
            result_path,
            token,
            {"decision": "production_review_not_authorized"},
        )

    committed = json.loads(result_path.read_text(encoding="utf-8"))
    assert committed["reservation_id"] == token
    assert lease_path.exists()
    original_unlink(lease_path)


def test_retry_after_crash_after_publish_cleans_residue_without_overwriting_result(
    tmp_path,
):
    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")
    committed = {
        "claim_authorized": False,
        "decision": "production_review_not_authorized",
        "reservation_id": token,
    }
    result_path.write_text(
        json.dumps(committed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lock_path = result_path.with_name(result_path.name + ".finalizing")
    temporary = result_path.with_name(result_path.name + f".{token}.tmp")
    lock_path.write_text(token, encoding="utf-8")
    temporary.write_text(json.dumps(committed), encoding="utf-8")

    with pytest.raises(FileExistsError, match="already spent"):
        finalize_reserved_result(
            result_path,
            token,
            {"decision": "production_review_authorized"},
        )

    assert json.loads(result_path.read_text(encoding="utf-8")) == committed
    assert not lock_path.exists()
    assert not temporary.exists()


def test_post_publish_lock_cleanup_failure_does_not_report_finalization_failure(
    tmp_path, monkeypatch
):
    import prospects.pre2014_cross_role_gate as gate

    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")
    lock_path = result_path.with_name(result_path.name + ".finalizing")
    original_unlink = gate.Path.unlink

    def fail_lock_cleanup_once(path, *args, **kwargs):
        if path == lock_path:
            monkeypatch.setattr(gate.Path, "unlink", original_unlink)
            raise OSError("injected post-publish cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(gate.Path, "unlink", fail_lock_cleanup_once)

    finalize_reserved_result(
        result_path,
        token,
        {"decision": "production_review_not_authorized"},
    )

    committed = json.loads(result_path.read_text(encoding="utf-8"))
    assert committed["decision"] == "production_review_not_authorized"
    assert committed["reservation_id"] == token
    assert lock_path.exists()
    with pytest.raises(FileExistsError, match="already spent"):
        finalize_reserved_result(
            result_path,
            token,
            {"decision": "production_review_authorized"},
        )
    assert not lock_path.exists()


@pytest.mark.parametrize("failure_point", ["serialize", "fsync", "replace"])
def test_failed_finalization_can_consume_same_reservation_as_spent_error(
    tmp_path, monkeypatch, failure_point
):
    import prospects.pre2014_cross_role_gate as gate

    result_path = tmp_path / "sealed-result.json"
    token = reserve_result_path(result_path, reservation_id="fixed-token")
    if failure_point == "serialize":
        original = gate.json.dump

        def fail_once(*args, **kwargs):
            monkeypatch.setattr(gate.json, "dump", original)
            raise RuntimeError("injected serialization failure")

        monkeypatch.setattr(gate.json, "dump", fail_once)
    elif failure_point == "fsync":
        original = gate.os.fsync

        def fail_once(*args, **kwargs):
            monkeypatch.setattr(gate.os, "fsync", original)
            raise OSError("injected fsync failure")

        monkeypatch.setattr(gate.os, "fsync", fail_once)
    else:
        original = gate.os.replace

        def fail_once(*args, **kwargs):
            monkeypatch.setattr(gate.os, "replace", original)
            raise OSError("injected replace failure")

        monkeypatch.setattr(gate.os, "replace", fail_once)

    with pytest.raises((OSError, RuntimeError), match="injected"):
        finalize_reserved_result(
            result_path,
            token,
            {"decision": "production_review_not_authorized"},
        )

    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "reservation_id": token,
        "status": "reserved_before_outer_outcomes",
    }
    assert not result_path.with_name(result_path.name + ".finalizing").exists()
    assert list(tmp_path.glob(f"{result_path.name}.*.tmp")) == []

    finalize_reserved_result(
        result_path,
        token,
        {
            "status": "spent_error",
            "decision": "production_review_not_authorized",
        },
    )
    committed = json.loads(result_path.read_text(encoding="utf-8"))
    assert committed["status"] == "spent_error"
    assert committed["reservation_id"] == token
    assert not result_path.with_name(result_path.name + ".finalizing").exists()


def test_outer_outcome_loader_runs_only_after_reservation_and_readiness(tmp_path):
    result_path = tmp_path / "sealed-result.json"
    events = []

    def load_outer_outcomes():
        marker = json.loads(result_path.read_text(encoding="utf-8"))
        events.append(marker["status"])
        return _fold_outputs()

    token, folds = reserve_and_load_outer_outcomes(
        result_path,
        load_outer_outcomes,
        readiness_blockers=(),
        reservation_id="fixed-token",
    )

    assert token == "fixed-token"
    assert len(folds) == 4
    assert events == ["reserved_before_outer_outcomes"]

    stopped_path = tmp_path / "not-ready.json"
    called = False

    def forbidden_loader():
        nonlocal called
        called = True
        return []

    with pytest.raises(ValueError, match="readiness failed"):
        reserve_and_load_outer_outcomes(
            stopped_path,
            forbidden_loader,
            readiness_blockers=("source_hash_mismatch",),
        )
    assert called is False
    assert stopped_path.exists() is False


def test_outer_outcome_exception_marks_the_reserved_path_spent(tmp_path):
    result_path = tmp_path / "sealed-result.json"

    def broken_loader():
        raise RuntimeError("synthetic outer failure")

    with pytest.raises(RuntimeError, match="synthetic outer failure"):
        reserve_and_load_outer_outcomes(
            result_path,
            broken_loader,
            readiness_blockers=(),
            reservation_id="fixed-token",
        )

    spent = json.loads(result_path.read_text(encoding="utf-8"))
    assert spent["status"] == "spent_error"
    assert spent["claim_authorized"] is False
    with pytest.raises(FileExistsError):
        reserve_result_path(result_path)


def test_gate_evaluation_rejects_noncanonical_or_nonfinite_scorer_outputs():
    wrong_metric = deepcopy(_fold_outputs())
    wrong_metric[0]["metric"] = "some_other_metric"
    wrong_metric[1]["players"][0]["candidate_percentile_rank"] = float("nan")

    result = evaluate_pre2014_cross_role_gate(
        wrong_metric,
        cohort_years=range(2009, 2022),
        declared_omissions={2020},
        current_role_shape_governor_passed=True,
        bootstrap_resamples=10,
    )

    assert result["readiness"]["passed"] is False
    assert "noncanonical_direct_metric" in result["readiness"]["blockers"]
    assert "invalid_player_observation" in result["readiness"]["blockers"]
    assert result["production_review_authorized"] is False


def test_gate_rejects_declared_cross_role_concordance_that_does_not_recompute():
    folds = _fold_outputs()
    folds[0]["cross_role_concordance"]["candidate"] = 0.99

    result = evaluate_pre2014_cross_role_gate(
        folds,
        cohort_years=range(2009, 2022),
        declared_omissions={2020},
        current_role_shape_governor_passed=True,
        bootstrap_resamples=10,
    )

    assert result["readiness"]["passed"] is False
    assert "cross_role_concordance_mismatch" in result["readiness"]["blockers"]


def test_zero_incumbent_error_fails_closed_with_json_safe_metrics():
    folds = _fold_outputs()
    for fold in folds:
        for player in fold["players"]:
            player["incumbent_percentile_rank"] = player["target_percentile_rank"]

    result = evaluate_pre2014_cross_role_gate(
        folds,
        cohort_years=range(2009, 2022),
        declared_omissions={2020},
        current_role_shape_governor_passed=True,
        bootstrap_resamples=10,
    )

    assert result["production_review_authorized"] is False
    assert result["metrics"]["direct_mae"]["relative_improvement"] is None
    json.dumps(result, allow_nan=False)
