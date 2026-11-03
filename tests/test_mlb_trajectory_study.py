"""Registered trajectory machinery checks; every row here is synthetic."""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
import warnings

import numpy as np
import pytest

from league_values.engine import ValuationEngine
from league_values.models import CategorySpec, LeagueConfig, PlayerPool, PlayerProjection
from league_values.post_processors import AgeCurve, VolumeMultiplier, _apply_multiplier
from projections.backtest import mlb_trajectory_study as study
from projections.constants import PEAK_AGE
from projections.export.marcel_run import build_marcel_projections
from projections.models.marcel_params import MarcelParams
from scripts import run_mlb_trajectory_study as runner


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tmp_path():
    # Python 3.14's mode=0o700 directory creation drops the Windows sandbox SID.
    temp_root = Path(tempfile.gettempdir()).resolve()
    path = temp_root / ("mlb-trajectory-" + uuid.uuid4().hex)
    path.mkdir()
    yield path
    resolved = path.resolve()
    assert resolved.parent == temp_root and resolved.name.startswith("mlb-trajectory-")
    shutil.rmtree(resolved)


def _h(i=1, **changes):
    row = {"mlbam_id": str(i), "PA": 330 + 20 * i, "AB": 280 + 17 * i,
           "H": 65 + 7 * i, "R": 30 + 3 * i, "HR": 8 + i * i,
           "RBI": 29 + 5 * i, "SB": 2 + i * i, "BB": 30 + i,
           "SO": 45 + i, "HBP": 3, "SF": 4, "CS": i,
           "1B": 42 + 4 * i, "2B": 12 + i, "3B": 3}
    return {**row, **changes}


def _p(i=1, **changes):
    row = {"mlbam_id": str(i + 10), "IP": 20 + 11 * i, "BF": 90 + 45 * i,
           "W": i, "SV": i * i, "K": 15 + 13 * i, "ER": 9 + i * i,
           "H_ALLOWED": 19 + 9 * i, "BB": 6 + 3 * i, "G": 20,
           "GS": 12 if i % 2 else 1, "HR": i + 2, "HBP": 1,
           "HLD": i, "QS": i}
    return {**row, **changes}


def _seasons(end=2012):
    return {year: {"hitter": [_h(i, H=60 + 7 * i + year % 3) for i in range(1, 5)],
                   "pitcher": [_p(i, ER=7 + i * i + year % 3) for i in range(1, 5)]}
            for year in range(2010, end + 1)}


def _categories(family, reference):
    if family == "hitter":
        specs = [CategorySpec(k, k, "hitter", stat=k) for k in ("R", "HR", "RBI", "SB")]
        specs.append(CategorySpec("AVG", "AVG", "hitter", numerator_stats=("H",),
                                  denominator_stats=("AB",), min_denominator=30,
                                  baseline=reference.baselines[family]["AVG"]))
    else:
        specs = [CategorySpec(k, k, "pitcher", stat=k) for k in ("W", "SV", "K")]
        specs.extend([
            CategorySpec("ERA", "ERA", "pitcher", numerator_stats=("ER",),
                         denominator_stats=("IP",), min_denominator=10,
                         ratio_multiplier=9, direction="lower",
                         baseline=reference.baselines[family]["ERA"]),
            CategorySpec("WHIP", "WHIP", "pitcher", numerator_stats=("BB", "H_ALLOWED"),
                         denominator_stats=("IP",), min_denominator=10, direction="lower",
                         baseline=reference.baselines[family]["WHIP"]),
        ])
    return specs


def test_reference_and_utility_match_source_engine_in_fixed_units():
    seasons = _seasons()
    ref = study.build_reference(2012, seasons)
    engine = ValuationEngine()
    for family in ("hitter", "pitcher"):
        stats = [r for year in (2010, 2011, 2012) for r in seasons[year][family]]
        players = [PlayerProjection(str(i), "synthetic", family, r) for i, r in enumerate(stats)]
        categories = _categories(family, ref)
        moments = {}
        for category in categories:
            impacts = [engine._category_impact(p, category, players) for p in players]
            assert ref.scales[family][category.id] == pytest.approx(np.std(impacts, ddof=0))
            moments[category.id] = (float(np.mean(impacts)), float(np.std(impacts)))
        league = LeagueConfig("synthetic", "categories", categories=tuple(categories), league_baselines=moments)
        zero = {key: 0 for key in stats[0] if key != "mlbam_id"}
        probe = {key: value for key, value in stats[-1].items() if key != "mlbam_id"}
        values = {v.player.id: v.total_value for v in engine.value_players([
            PlayerProjection("probe", "synthetic", family, probe),
            PlayerProjection("zero", "synthetic", family, zero)], league)}
        assert study.utility(probe, family, ref) == pytest.approx(values["probe"] - values["zero"])
        assert study.utility(zero, family, ref) == pytest.approx(0)
    all_h = [r for s in seasons.values() for r in s["hitter"]]
    all_p = [r for s in seasons.values() for r in s["pitcher"]]
    assert ref.baselines["hitter"]["AVG"] == pytest.approx(sum(r["H"] for r in all_h) / sum(r["AB"] for r in all_h))
    assert ref.baselines["pitcher"]["ERA"] == pytest.approx(9 * sum(r["ER"] for r in all_p) / sum(r["IP"] for r in all_p))


def test_raw_validation_precedes_ratio_zero_rules_and_fold_scales():
    ref = study.build_reference(2012, _seasons())
    for family, stats, ratio_keys in (("hitter", _h(AB=30, H=10), ("AVG",)),
                                      ("pitcher", _p(IP=10), ("ERA", "WHIP"))):
        impacts = study.category_impacts(stats, family, ref)
        assert all(impacts[k] == 0 for k in ratio_keys)
        for key in (("H", "AB") if family == "hitter" else ("ER", "IP", "H_ALLOWED", "BB")):
            broken = dict(stats)
            del broken[key]
            with pytest.raises(study.StudyError):
                study.category_impacts(broken, family, ref)
            with pytest.raises(study.StudyError):
                study.category_impacts({**stats, key: float("nan")}, family, ref)
    broken = _seasons()
    for season in broken.values():
        for row in season["hitter"]:
            row["SB"] = 0
    with pytest.raises(study.StudyError):
        study.build_reference(2012, broken)
    with pytest.raises(study.StudyError):
        study.build_reference(2012, {2011: _seasons()[2011], 2012: _seasons()[2012]})


def _literal_assignments(path):
    values = {}
    for node in ast.parse(path.read_text(encoding="utf-8-sig")).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
    return values


def test_frozen_constants_match_safe_source_literals_and_hand_chain():
    source = _literal_assignments(ROOT / "mlb/dynasty.py")
    assert dict(study.HITTER_KNOTS) == source["HITTER_AGE_CURVE"]
    assert dict(study.PITCHER_KNOTS) == source["PITCHER_AGE_CURVE"]
    assert study.HORIZON_WEIGHTS == tuple(v for _, v in source["HORIZON_YEAR_WEIGHTS"])
    assert PEAK_AGE == 29
    assert study.age_feature(PEAK_AGE) == 0
    nodes = [node for node in ast.parse((ROOT / "mlb/dynasty.py").read_text(encoding="utf-8-sig")).body
             if isinstance(node, ast.FunctionDef) and node.name in ("_volume", "_playing_time_reliability")]
    namespace = {"PlayerProjection": PlayerProjection, "PlayerPool": PlayerPool}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "source-reliability-only", "exec"), namespace)
    volume = VolumeMultiplier()
    for role, base, reg in (("hitter", volume.hitter_pa, 150), ("SP", volume.sp_ip, 45), ("RP", volume.rp_ip, 20)):
        curve = source["HITTER_AGE_CURVE" if role == "hitter" else "PITCHER_AGE_CURVE"]
        source_curve = AgeCurve(curve, curve)
        for age in (19, 24, 36, 41):
            for vol in (0, base / 3, base * 1.2):
                rho = max(source["FUTURE_RELIABILITY_FLOOR"], min(1, round(100 * vol / (vol + reg), 2) / 100))
                assert study.reliability(role, vol) == rho
                pool = {"hitter": "hitter", "SP": "starter", "RP": "reliever"}[role]
                player = PlayerProjection("1", "synthetic", pool, {"PA": vol, "IP": vol}, positions=(role,))
                production_rho = max(source["FUTURE_RELIABILITY_FLOOR"], namespace["_playing_time_reliability"](player) / 100)
                assert study.reliability(role, vol) == production_rho
                assert study.volume_multiplier(role, vol) == pytest.approx(volume._compute(vol, base))
                c0, c1, c2 = [source_curve._interpolate(curve, age + i) for i in range(3)]
                assert study.age_multiplier(role, age) == pytest.approx(c0)
                v, baseline = 3.0, -4.0
                v = _apply_multiplier(v, c0, baseline)
                v = _apply_multiplier(v, volume._compute(vol, base), baseline)
                v = _apply_multiplier(v, (1 + .72 * c1 / c0 * rho + .48 * c2 / c0 * rho) / 2.2, baseline)
                expected = (v - baseline) / (3.0 - baseline)
                assert study.hand_set_multiplier(role, age, vol) == pytest.approx(expected)


def test_centering_uses_each_family_and_one_pooled_full_universe_minimum():
    rows = [{"mlbam_id": 1, "role": "hitter", "F1": 2},
            {"mlbam_id": 2, "role": "hitter", "F1": 8},
            {"mlbam_id": 3, "role": "SP", "F1": 1},
            {"mlbam_id": 4, "role": "RP", "F1": 3}]
    centered = study.center_forecasts(rows)
    assert [r["C_fam"] for r in centered] == [5, 5, 2, 2]
    assert [r["V"] for r in centered] == [-3, 3, -1, 1]
    assert {r["B"] for r in centered} == {-3}
    for row in centered:
        fit = {"role": row["role"], "coefficients": [1, 0, 0, 0], "scales": [1] * 4, "n": 3}
        predictions = study.predict({**row, "age": 28, "rho": .8, "volume": 100}, fit)
        assert predictions["flat"] == row["F1"]
        assert predictions["candidate"] == pytest.approx(row["F1"])


def test_ridge_matches_augmented_least_squares_in_origin_specific_units():
    rows = [
        {"role": "hitter", "origin": 2012 + i % 2, "V": 2.0 + i,
         "B": -2.0 - i % 2, "C_fam": 0.5 * (i % 2),
         "age": 20 + 3 * i, "rho": 0.55 + 0.05 * i, "H3": 1.0 + i * i}
        for i in range(7)
    ]
    design = []
    target = []
    for row in rows:
        a = min(37, max(22, row["age"])) - 29
        v = row["V"] - row["B"]
        design.append([v, v * a, v * a * a, v * row["rho"]])
        target.append(row["H3"] - row["C_fam"] - row["B"])
    design = np.asarray(design)
    scales = np.std(design, axis=0, ddof=0)
    scales[scales == 0] = 1
    augmented_x = np.vstack([design / scales, np.sqrt(10.0) * np.eye(4)])
    augmented_y = np.r_[target, np.zeros(4)]
    expected = np.linalg.lstsq(augmented_x, augmented_y, rcond=None)[0] / scales
    fit = study.fit_ridge(rows, "hitter")
    assert fit["coefficients"] == pytest.approx(expected)
    assert fit["scales"] == pytest.approx(scales)
    assert fit["n"] == len(rows)


def test_average_rank_spearman_and_lower_numeric_id_tiebreak():
    assert study.spearman([1, 1, 3, 4], [1, 2, 2, 4]) == pytest.approx(5 / 6)
    assert study.spearman([1, 1], [2, 3]) is None
    rows = [{"mlbam_id": 12, "F1": 3}, {"mlbam_id": 2, "F1": 3},
            {"mlbam_id": 1, "F1": 2}]
    assert list(study.top_ids(rows, n=2)) == [2, 12]


@pytest.mark.parametrize("hitter,pitcher,expected", [
    (_h(), None, ("hitter", False)),
    (None, _p(G=10, GS=5), ("SP", False)),
    (None, _p(G=10, GS=4), ("RP", False)),
    (_h(PA=200), _p(BF=200), ("hitter", True)),
    (_h(PA=199), _p(BF=200), ("SP", True)),
])
def test_origin_routing_has_fixed_component_and_starter_ties(hitter, pitcher, expected):
    assert study.route_asset(hitter, pitcher) == expected


@pytest.mark.parametrize("changes", [{"G": 0}, {"GS": 21}, {"GS": -1},
                                     {"G": float("inf")}, {"GS": None}])
def test_routing_blocks_invalid_positive_pitching_counts(changes):
    with pytest.raises(study.StudyError):
        study.route_asset(None, _p(**changes))
    missing_bf = _p()
    del missing_bf["BF"]
    with pytest.raises(study.StudyError):
        study.route_asset(_h(), missing_bf)


def test_team_stints_are_aggregated_once_without_tot_double_counting():
    a = _h(1, team="A", PA=100, AB=90, H=20)
    b = _h(1, team="B", PA=200, AB=180, H=50)
    total = {key: a[key] + b[key] for key in a if key not in ("mlbam_id", "team")}
    total.update(mlbam_id="1", team="TOT")
    result = study.reconcile_stints([a, total, b], "hitter")
    row = result["1"]
    assert (row["PA"], row["AB"], row["H"]) == (300, 270, 70)
    with pytest.raises(study.StudyError):
        study.reconcile_stints([a, a], "hitter")


def test_origin_data_refuses_future_and_unverified_absence():
    seasons = _seasons()
    identities = {str(i): {"birth_date": "1988-04-02"} for i in range(1, 20)}
    data = study.OriginData(2012, seasons, identities)
    with pytest.raises(study.StudyError):
        data.season(2013)
    with pytest.raises(study.StudyError):
        study.OriginData(2012, {**seasons, 2013: seasons[2012]}, identities)
    zero = data.actual("19", 2012, "hitter")
    assert all(value == 0 for value in zero.values())
    with pytest.raises(study.StudyError):
        data.actual("999", 2012, "hitter")
    with pytest.raises(study.StudyError):
        study.OriginData(2012, seasons, identities, complete=False)


def test_population_freezes_routing_history_flags_and_missing_forecasts():
    seasons = _seasons()
    seasons[2012]["hitter"] = [r for r in seasons[2012]["hitter"] if r["mlbam_id"] != "4"]
    seasons[2012]["hitter"].append(_h(5, mlbam_id="20"))
    seasons[2012]["pitcher"].append(_p(1, mlbam_id="1"))
    identities = {str(i): {"birth_date": "1980-04-02"} for i in range(1, 21)}
    identities["3"] = {}

    def forecast(data):
        with pytest.raises(study.StudyError):
            data.season(2013)
        return {"hitter": {str(i): _h(i) for i in (1, 3, 4)} | {"20": _h(5)},
                "pitcher": {str(i + 10): _p(i) for i in range(1, 5)}}

    frozen = study.build_origin(study.OriginData(2012, seasons, identities), forecast)
    rows = {r["mlbam_id"]: r for r in frozen["rows"]}
    assert set(rows) == {"1", "2", "3", "4", "11", "12", "13", "14", "20"}
    assert rows["1"]["role"] == "hitter" and rows["1"]["both_component"] is True
    assert rows["1"]["cold_start"] is False and rows["1"]["graduate"] is False
    assert rows["1"]["age"] == 32 and rows["1"]["age_33_plus"] is False
    assert rows["4"]["role"] == "hitter" and rows["4"]["cold_start"] is True
    assert rows["4"]["graduate"] is False
    assert rows["20"]["graduate"] is True and rows["20"]["cold_start"] is True
    assert rows["20"]["graduate_left_censored_2010"] is True
    assert rows["2"]["F1"] is None and rows["2"]["complete"] is False
    assert rows["3"]["F1"] is not None and rows["3"]["complete"] is False
    assert "2" not in {str(pid) for pid in frozen["top300"]}
    assert any(item["reasons"] for item in frozen["ledger"] if item["mlbam_id"] == "3")


def test_training_labels_use_each_training_origins_frozen_units():
    seasons = _seasons(2015)
    identities = {str(i): {"birth_date": "1988-01-01"} for i in range(1, 20)}
    forecast = lambda data: {"hitter": {str(i): _h(i) for i in range(1, 5)},
                             "pitcher": {str(i + 10): _p(i) for i in range(1, 5)}}
    old = study.build_origin(study.OriginData(2012, {y: s for y, s in seasons.items() if y <= 2012}, identities), forecast)
    current_data = study.OriginData(2015, seasons, identities)
    current = study.build_origin(current_data, forecast)
    record = study.fit_origin(study.Fold("synthetic", 2015, (2012,)), current, {2012: old}, current_data)
    reference = study.Reference(**old["reference"])
    old_rows = {row["mlbam_id"]: row for row in old["rows"]}
    for row in record["training_rows"]:
        family = "hitter" if row["role"] == "hitter" else "pitcher"
        annual = [study.utility(current_data.actual(row["mlbam_id"], year, family), family, reference)
                  for year in (2013, 2014, 2015)]
        assert row["H3"] == pytest.approx(sum(w * u for w, u in zip((1, .72, .48), annual)) / 2.2)
        assert row["B"] == old_rows[row["mlbam_id"]]["B"]
        assert row["C_fam"] == old_rows[row["mlbam_id"]]["C_fam"]
    with pytest.raises(study.StudyError):
        study.fit_origin(study.Fold("illegal", 2015, (2013,)), current, {2012: old}, current_data)


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="ascii")


def test_origin_file_view_excludes_later_and_statcast_inputs(tmp_path):
    source = tmp_path / "repo"
    for year, season in _seasons(2013).items():
        for family, folder, prefix in (("hitter", "historical", "hitting"), ("pitcher", "pitching", "pitching")):
            _json(source / "projections/data" / folder / f"{prefix}_{year}.json", season[family])
    _json(source / "projections/data/identity.json", {"1": {"birth_date": "1988-01-01"}})
    _json(source / "projections/data/statcast/hitting_2012.json", [{"forbidden": True}])
    first = runner.create_origin_view(source, 2012, tmp_path / "first")
    first_hashes = {p.relative_to(first).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in first.rglob("*") if p.is_file()}
    _json(source / "projections/data/historical/hitting_2013.json", [{"changed_later": True}])
    second = runner.create_origin_view(source, 2012, tmp_path / "second")
    second_hashes = {p.relative_to(second).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in second.rglob("*") if p.is_file()}
    assert first_hashes == second_hashes
    assert len(first_hashes) == 7
    assert not any("2013" in p or "statcast" in p for p in first_hashes)


def test_default_builder_statcast_invariance_on_only_synthetic_rows(tmp_path):
    identities = {str(i): {"birth_date": "1988-01-01"} for i in range(1, 5)}
    for year, season in _seasons().items():
        _json(tmp_path / "historical" / f"hitting_{year}.json", season["hitter"])
    params = MarcelParams()
    assert params.alpha_contact == params.alpha_power == params.gamma == 0
    before = build_marcel_projections(2013, tmp_path, params, identities)
    _json(tmp_path / "statcast/hitting_2012.json", [
        {"mlbam_id": str(i), "xba": .99, "xslg": 3.9} for i in range(1, 5)])
    after = build_marcel_projections(2013, tmp_path, params, identities)
    assert before
    key = lambda row: int(row["metadata"]["mlbam_id"])
    assert sorted(before, key=key) == sorted(after, key=key)


def test_guard_requires_ci_hash_receipt_and_unused_destination(tmp_path, monkeypatch):
    registration = tmp_path / "docs/registration-2026-11-02-mlb-trajectory.md"
    registration.parent.mkdir()
    registration.write_bytes(b"synthetic\r\nregistration\r\n")
    digest = hashlib.sha256(b"synthetic\nregistration\n").hexdigest()
    monkeypatch.setattr(runner, "PINNED_REGISTRATION_HASH", digest)
    charter = tmp_path / runner.CHARTER
    charter.parent.mkdir(parents=True, exist_ok=True)
    charter.write_bytes(b"synthetic\r\ncharter\r\n")
    charter_digest = hashlib.sha256(b"synthetic\ncharter\n").hexdigest()
    monkeypatch.setattr(runner, "PINNED_CHARTER_HASH", charter_digest)
    receipt = tmp_path / "docs/registration-2026-11-02-mlb-trajectory/EXECUTION-RECEIPT.md"
    output = tmp_path / "output"
    with pytest.raises(study.StudyError):
        runner.guard(tmp_path, output, {})
    with pytest.raises(study.StudyError):
        runner.guard(tmp_path, output, {"GITHUB_ACTIONS": "true"})
    receipt.parent.mkdir(exist_ok=True)
    receipt.write_text("synthetic " + digest, encoding="ascii")
    runner.guard(tmp_path, output, {"GITHUB_ACTIONS": "true"})
    assert not output.exists()
    receipt.write_text("wrong receipt", encoding="ascii")
    with pytest.raises(study.StudyError):
        runner.guard(tmp_path, output, {"GITHUB_ACTIONS": "true"})
    receipt.write_text(digest, encoding="ascii")
    registration.write_bytes(b"tampered\n")
    with pytest.raises(study.StudyError):
        runner.guard(tmp_path, output, {"GITHUB_ACTIONS": "true"})
    registration.write_bytes(b"synthetic\nregistration\n")
    charter.write_bytes(b"changed charter\n")
    with pytest.raises(study.StudyError):
        runner.guard(tmp_path, output, {"GITHUB_ACTIONS": "true"})
    charter.unlink()
    with pytest.raises(study.StudyError):
        runner.guard(tmp_path, output, {"GITHUB_ACTIONS": "true"})
    charter.write_bytes(b"synthetic\ncharter\n")
    output.mkdir()
    with pytest.raises(study.StudyError):
        runner.guard(tmp_path, output, {"GITHUB_ACTIONS": "true"})


def test_aggregate_rejects_player_leaks_and_freeze_is_immutable(tmp_path):
    runner.assert_aggregate_safe({"disposition": "INELIGIBLE", "counts": {"matched": 12}, "failures": []})
    for payload in ({"mlbam_id": 1}, {"name": "Synthetic Person"}, {"player_name": "Synthetic Person"},
                    {"rows": [{"candidate": 2}]}, {"nested": {"mlbam_id": 1}}):
        with pytest.raises(study.StudyError):
            runner.assert_aggregate_safe(payload)
    path = tmp_path / "freeze.json"
    runner.freeze_record(path, {"information_cutoff": "2012-11-01T00:00:00-04:00", "orderings": []})
    before = path.read_bytes()
    assert len(json.loads(before)["content_hash"]) == 64
    with pytest.raises((study.StudyError, FileExistsError)):
        runner.freeze_record(path, {"information_cutoff": "changed"})
    assert path.read_bytes() == before


def test_percentile_undefined_denominator_and_mechanical_precedence():
    values = [float(i) for i in range(95)] + [float("nan")] * 5
    available = study.percentile_bound(values, .025)
    assert available["undefined"] == 5
    assert available["replicates"] == 100
    assert available["bound"] == pytest.approx(np.percentile(np.arange(95), 2.5, method="linear"))
    unavailable = study.percentile_bound(values[:-6] + [float("nan")] * 6, .025)
    assert unavailable["bound"] is None
    assert study.mechanical_disposition() == "PASS"
    assert study.mechanical_disposition(unavailable=["bound"]) == "UNDERPOWERED"
    assert study.mechanical_disposition(ineligible=["coverage"], unavailable=["bound"]) == "INELIGIBLE"
    assert study.mechanical_disposition(failures=["gap"], ineligible=["coverage"], unavailable=["bound"]) == "FAIL"


def test_constant_ridge_features_keep_scale_one_and_negative_m_clamps():
    row = {"role": "SP", "origin": 2012, "V": 5, "B": -2, "C_fam": 2,
           "age": 29, "rho": .8, "H3": -20, "volume": 180}
    fit = study.fit_ridge([row, dict(row), dict(row)], "SP")
    assert fit["scales"] == [1] * 4
    assert study.predict(row, fit)["candidate"] == pytest.approx(row["C_fam"] + row["B"])
    with pytest.raises(study.StudyError):
        study.fit_ridge([row], "RP")
    with pytest.raises(study.StudyError):
        study.fit_ridge([{**row, "H3": float("inf")}], "SP")


def test_small_slice_exemption_does_not_waive_full_or_large_slice_coverage():
    def population(rp_count):
        return [{"mlbam_id": i + 1, "origin": fold.origin,
                 "role": "RP" if i < rp_count else ("SP" if i < 100 else "hitter"),
                 "cold_start": False, "graduate": False, "complete": True,
                 "candidate": 5, "flat": 5, "hand_set": 4, "H3": 1,
                 "age": 27, "rho": .8, "F1": 5, "V": 1, "B": -2,
                 "C_fam": 4, "volume": 100}
                for fold in study.FOLDS[:4] for i in range(240)]
    frozen = population(29)
    admitted = study.gate_admission([r for r in frozen if r["mlbam_id"] > 3], frozen)
    assert admitted["ineligible"] == []
    assert admitted["coverage"]["D1"]["slices"]["RP"]["exempt"] is True
    frozen = population(30)
    blocked = study.gate_admission([r for r in frozen if r["mlbam_id"] > 4], frozen)
    assert any("RP coverage" in reason for reason in blocked["ineligible"])
    assert all("overall coverage" not in reason for reason in blocked["ineligible"])
    overall = study.gate_admission([r for r in frozen if r["mlbam_id"] > 15], frozen)
    assert any("overall coverage" in reason for reason in overall["ineligible"])
    invalid = deepcopy(frozen)
    invalid[0]["candidate"] = float("nan")
    assert study.gate_admission(invalid, frozen)["ineligible"]
    changed = deepcopy(frozen)
    changed[0]["role"] = "hitter"
    assert study.gate_admission(changed, frozen)["ineligible"]


def test_bootstrap_is_paired_clustered_deterministic_and_shared_between_gates(monkeypatch):
    rows = [{"mlbam_id": i + 1, "origin": fold.origin, "H3": i + (i % 3) / 10,
             "candidate": i, "flat": (i * 5) % 12, "hand_set": (i * 7) % 12}
            for fold in study.FOLDS[:4] for i in range(12)]
    original = study.spearman
    samples = []

    def observe(x, y):
        if len(samples) < 24:
            samples.append(tuple(x))
        return original(x, y)

    monkeypatch.setattr(study, "spearman", observe)
    first = study.bootstrap({"full": rows, "top300": deepcopy(rows)})
    second = study.bootstrap({"full": rows, "top300": deepcopy(rows)})
    assert first == second
    assert first["full"] == first["top300"]
    assert all(len(values) == 12 for values in samples)
    assert any(len(set(values)) < len(values) for values in samples)
    for period in ("development", "H"):
        assert first["full"][period]["candidate"]["replicates"] == 2000
        assert len(first["full"][period]["candidate"]["values"]) == 2000
        for comparator in ("flat", "hand_set"):
            receipt = first["full"][period]["gaps"][comparator]
            assert receipt["alpha"] == .025
            assert receipt["unadjusted"]["alpha"] == .05


def test_evaluation_labels_are_unreachable_until_all_four_predictions_frozen(tmp_path, monkeypatch):
    calls = []
    loader = lambda origin: calls.append(origin)
    frozen = [runner.freeze_record(tmp_path / f"{fold.name}.json", {
        "fold": fold.name, "origin": fold.origin, "rows": [], "top300": []})
        for fold in study.FOLDS[:4]]
    with pytest.raises(study.StudyError):
        runner.evaluate_frozen(frozen[:-1], loader, {})
    assert calls == []
    tampered = deepcopy(frozen)
    tampered[0]["origin"] = 2019
    with pytest.raises(study.StudyError):
        runner.evaluate_frozen(tampered, loader, {})
    assert calls == []
    records = []
    for fold in study.FOLDS[:4]:
        rows = [{"mlbam_id": str(i), "origin": fold.origin, "role": "hitter", "complete": True}
                for i in (1, 2)]
        records.append(runner.freeze_record(tmp_path / f"valid-{fold.name}.json", {
            "fold": fold.name, "origin": fold.origin, "rows": rows, "top300": [1]}))

    def score(record, labels, schedule):
        assert calls == [f.origin for f in study.FOLDS[:4]][:len(calls)]
        return {"rows": record["rows"]}

    def gates(matched, populations):
        assert len(matched["full"]) == len(populations["full"]) == 8
        assert len(matched["top300"]) == len(populations["top300"]) == 4
        assert {r["mlbam_id"] for r in matched["top300"]} == {"1"}
        return {"disposition": "INELIGIBLE"}

    monkeypatch.setattr(study, "score_frozen", score)
    monkeypatch.setattr(study, "score_gates", gates)
    monkeypatch.setattr(study, "describe_study", lambda *args, **kwargs: {})
    aggregate, sealed = runner.evaluate_frozen(records, loader, {})
    assert calls == [f.origin for f in study.FOLDS[:4]]
    runner.assert_aggregate_safe(aggregate)
    runner.write_json(tmp_path / "aggregate.json", aggregate)
    assert "mlbam_id" not in (tmp_path / "aggregate.json").read_text(encoding="ascii")
    assert len(sealed["evaluations"]) == 4


def test_empty_bootstrap_keeps_all_undefined_draws_in_denominator():
    result = study.bootstrap({"full": [], "top300": []})
    for gate in ("full", "top300"):
        receipt = result[gate]["H"]["candidate"]
        assert receipt["bound"] is None
        assert receipt["undefined"] == receipt["replicates"] == 2000


def test_within_family_condition_is_unavailable_when_any_origin_has_under_30():
    rows = [{"mlbam_id": i + (1 if role == "hitter" else 101),
             "origin": fold.origin, "role": role, "H3": i,
             "candidate": -i, "flat": i, "hand_set": i}
            for fold in study.FOLDS[:4] for role in ("hitter", "SP") for i in range(29)]
    _, failures, unavailable = study._within_family(rows)
    assert unavailable
    assert failures == []
    rows.extend({"mlbam_id": 30, "origin": fold.origin, "role": "hitter", "H3": 29,
                 "candidate": -29, "flat": 29, "hand_set": 29} for fold in study.FOLDS[:4])
    _, failures, unavailable = study._within_family(rows)
    assert unavailable
    assert failures and all("hitter" in reason for reason in failures)


def test_fold_table_is_literal_and_training_labels_end_before_test_origin():
    expected = [("D1", 2018, tuple(range(2012, 2016))),
                ("D2", 2019, tuple(range(2012, 2017))),
                ("D3", 2020, tuple(range(2012, 2018))),
                ("H", 2023, tuple(range(2012, 2021))),
                ("P", 2026, tuple(range(2012, 2024)))]
    assert [(f.name, f.origin, f.training) for f in study.FOLDS] == expected
    assert all(z + 3 <= f.origin for f in study.FOLDS for z in f.training)
    assert len(study.BUILDER_INPUT_MANIFEST) == 35
    assert len(set(study.BUILDER_INPUT_MANIFEST)) == 35
    assert all("statcast" not in p for p in study.BUILDER_INPUT_MANIFEST)


def test_descriptive_capture_fractional_ties_and_full_vector_sensitivity():
    rows = [{"candidate": score, "H3": target, "complete": True}
            for score, target in ((3, 10), (2, 20), (2, 40), (1, 10))]
    result = study.top_capture(rows, "candidate", n=2)
    assert result["cutoff_fraction"] == .5
    assert result["capture"] == pytest.approx((10 + .5 * (20 + 40)) / 80)
    rows[2]["complete"] = False
    assert study.top_capture(rows, "candidate", n=2)["coverage_blocked"] is True
    assert study.top_capture(rows, "candidate", n=2)["capture"] is None
    raw = _p()
    adjusted = study.per162_stats(raw, "pitcher", 60)
    assert adjusted == {key: raw[key] * 162 / 60 for key in study.RAW_FIELDS["pitcher"]}


def test_transfer_recomputes_feed_centering_with_frozen_coefficients():
    reference = study.build_reference(2012, _seasons())
    registered = {"origin": 2026, "reference": {
        "origin": 2026, "baselines": reference.baselines, "scales": reference.scales},
        "fits": {role: {"role": role, "coefficients": [1, 0, 0, 0],
                         "scales": [1] * 4, "n": 5} for role in study.ROLES}}
    feed = [{"mlbam_id": "1", "role": "hitter", "stats": _h(1)},
            {"mlbam_id": "2", "role": "hitter", "stats": _h(4)},
            {"mlbam_id": "11", "role": "SP", "stats": _p(1)},
            {"mlbam_id": "12", "role": "RP", "stats": _p(4)}]
    identities = {row["mlbam_id"]: {"birth_date": "1998-04-02"} for row in feed}
    transfer = study.build_transfer(registered, feed, identities)
    assert transfer["fits"] == registered["fits"]
    assert transfer["feed_centering_recomputed"] is True
    expected = study.center_forecasts([
        {"role": row["role"], "F1": study.utility(row["stats"], row["role"], reference)}
        for row in feed])
    for row, centered in zip(transfer["rows"], expected):
        assert row["age"] == 28
        assert (row["C_fam"], row["B"], row["V"]) == pytest.approx((centered["C_fam"], centered["B"], centered["V"]))
        assert row["flat"] == pytest.approx(row["F1"])
        assert row["candidate"] == pytest.approx(row["F1"])
        assert np.isfinite(row["hand_set"])


def test_synthetic_historical_freeze_and_evaluation_phases_integrate(tmp_path):
    seasons = _seasons(2026)
    identities = {str(i): {"birth_date": "1988-01-01"} for i in range(1, 20)}
    saved, evaluation_calls = [], []

    def origin_loader(origin):
        prefix = {year: deepcopy(rows) for year, rows in seasons.items() if year <= origin}
        return study.OriginData(origin, prefix, identities), origin

    def forecast(origin, view, crosswalk):
        assert view == origin
        assert crosswalk == identities
        assert evaluation_calls == []
        return {"hitter": {str(i): _h(i) for i in range(1, 5)},
                "pitcher": {str(i + 10): _p(i) for i in range(1, 5)}}

    def save(name, record):
        assert evaluation_calls == []
        frozen = runner.freeze_record(tmp_path / f"{name}-predictions.json", record)
        saved.append(name)
        return frozen

    frozen = runner.freeze_historical(origin_loader, forecast, save)
    assert saved == ["D1", "D2", "D3", "H"]
    assert evaluation_calls == []
    before = deepcopy(frozen)
    for record in frozen:
        assert len(record["content_hash"]) == 64
        runner.verify_record(record)
        assert set(record["fits"]) == set(study.ROLES)
        assert all(all(model in row for model in ("flat", "hand_set", "candidate"))
                   for row in record["rows"] if row["complete"])

    def evaluation_loader(origin):
        assert saved == ["D1", "D2", "D3", "H"]
        evaluation_calls.append(origin)
        labels = {year: deepcopy(seasons[year]) for year in range(origin + 1, origin + 4)}
        return study.OriginData(origin + 3, labels, identities)

    schedules = {str(year): 60 if year == 2020 else 162 for year in seasons}
    aggregate, sealed = runner.evaluate_frozen(frozen, evaluation_loader, schedules)
    assert evaluation_calls == [fold.origin for fold in study.FOLDS[:4]]
    assert frozen == before
    assert aggregate["disposition"] in ("INELIGIBLE", "FAIL", "UNDERPOWERED")
    runner.assert_aggregate_safe(aggregate)
    assert len(sealed["evaluations"]) == 4
    for gate in ("full", "top300"):
        for fold in study.FOLDS[:4]:
            contributions = aggregate["diagnostics"][gate][fold.name]["family_contributions"]
            for family in ("hitter", "pitcher"):
                assert contributions[family]["n"] == 4
                assert all(value is None for key, value in contributions[family].items() if key != "n")


def test_default_forecast_rejects_missing_raw_builder_dependency(tmp_path):
    seasons = _seasons()
    identities = {str(i): {"birth_date": "1988-01-01"} for i in range(1, 20)}
    for year, families in seasons.items():
        _json(tmp_path / "historical" / f"hitting_{year}.json", families["hitter"])
        _json(tmp_path / "pitching" / f"pitching_{year}.json", families["pitcher"])
    valid = runner.default_forecast(2012, tmp_path, identities)
    assert set(valid["hitter"]) == {str(i) for i in range(1, 5)}
    assert set(valid["pitcher"]) == {str(i + 10) for i in range(1, 5)}
    del seasons[2012]["hitter"][0]["1B"]
    _json(tmp_path / "historical/hitting_2012.json", seasons[2012]["hitter"])
    with pytest.raises(study.StudyError, match="forecast dependency 1B"):
        runner.default_forecast(2012, tmp_path, identities)


def _admission_population():
    return [{"mlbam_id": i + 1, "origin": fold.origin,
             "role": "SP" if i < 80 else ("RP" if i < 160 else "hitter"),
             "cold_start": False, "graduate": False, "both_component": False,
             "complete": True, "candidate": 5, "flat": 5, "hand_set": 4,
             "H3": 1, "age": 27, "rho": .8, "F1": 5, "V": 1,
             "B": -2, "C_fam": 4, "volume": 100}
            for fold in study.FOLDS[:4] for i in range(240)]


def test_ledgered_unresolved_rows_use_coverage_allowance_without_voiding_fold():
    frozen = _admission_population()
    for row in frozen:
        if row["mlbam_id"] == 1:
            row.update(role=None, cold_start=None, graduate=None, complete=False,
                       exclusions=["Unresolved routing and slice inputs"])
    matched = [deepcopy(row) for row in frozen if row["complete"]]
    result = study.gate_admission(matched, frozen)
    assert result["ineligible"] == []
    for fold in study.FOLDS[:4]:
        coverage = result["coverage"][fold.name]
        assert coverage["frozen"] == 240
        assert coverage["matched"] == 239
        assert coverage["coverage"] == pytest.approx(239 / 240)

    crowded = deepcopy(frozen)
    for row in crowded:
        if row["mlbam_id"] <= 13:
            row.update(role=None, cold_start=None, graduate=None, complete=False)
    blocked = study.gate_admission([row for row in crowded if row["complete"]], crowded)
    assert all(any(reason.startswith(fold.name + ": overall coverage")
                   for reason in blocked["ineligible"]) for fold in study.FOLDS[:4])
    assert all(entry["frozen"] == 240 and entry["matched"] == 227
               for entry in blocked["coverage"].values())


@pytest.mark.parametrize("field,value", [("role", None), ("cold_start", None),
                                        ("graduate", 1), ("F1", None),
                                        ("candidate", float("nan"))])
def test_matched_required_fields_remain_strict(field, value):
    frozen = _admission_population()
    matched = deepcopy(frozen)
    matched[0][field] = value
    result = study.gate_admission(matched, frozen)
    assert any("required-field provenance/completeness" in reason
               for reason in result["ineligible"])
    assert result["coverage"]["D1"]["matched"] == 239


def _transfer_registration():
    reference = study.build_reference(2012, _seasons())
    return {"origin": 2026, "reference": {
        "origin": 2026, "baselines": reference.baselines, "scales": reference.scales},
        "fits": {role: {"role": role, "coefficients": [1, 0, 0, 0],
                         "scales": [1] * 4, "n": 5} for role in study.ROLES}}


def test_transfer_ledgers_missing_dob_and_invalid_stats_without_losing_population():
    registered = _transfer_registration()
    feed = [{"mlbam_id": "1", "role": "hitter", "stats": _h(1)},
            {"mlbam_id": "2", "role": "hitter", "stats": _h(4)},
            {"mlbam_id": "3", "role": "hitter", "stats": _h(3, H=None)},
            {"mlbam_id": "11", "role": "SP", "stats": _p(1)},
            {"mlbam_id": "12", "role": "RP", "stats": _p(4)}]
    identities = {row["mlbam_id"]: {"birth_date": "1998-04-02"} for row in feed
                  if row["mlbam_id"] != "2"}
    before = deepcopy(feed)
    result = study.build_transfer(registered, feed, identities)
    assert feed == before
    assert result["coverage"] == {"frozen": 5, "matched": 3}
    assert len(result["rows"]) == 5
    assert result["fits"] == registered["fits"]
    rows = {row["mlbam_id"]: row for row in result["rows"]}
    for pid in ("2", "3"):
        assert rows[pid]["complete"] is False
        assert rows[pid]["exclusions"]
        assert all(rows[pid].get(model) is None for model in ("flat", "hand_set", "candidate"))
    assert any("DOB" in reason for reason in rows["2"]["exclusions"])
    assert rows["2"]["F1"] is not None
    assert rows["3"]["F1"] is None
    reference = study.Reference(**registered["reference"])
    expected = study.center_forecasts([
        {"role": row["role"], "F1": study.utility(row["stats"], row["role"], reference)}
        for row in feed if row["mlbam_id"] != "3"])
    for pid, centered in zip(("1", "2", "11", "12"), expected):
        assert (rows[pid]["C_fam"], rows[pid]["B"]) == pytest.approx(
            (centered["C_fam"], centered["B"]))
    assert {entry["mlbam_id"] for entry in result["ledger"]} == set(rows)
    assert all(rows[pid]["complete"] for pid in ("1", "11", "12"))


@pytest.mark.parametrize("bad_row", [
    {"mlbam_id": "1", "role": "hitter", "stats": _h(2)},
    {"mlbam_id": "2", "role": "pitcher", "stats": _p(2)},
])
def test_transfer_still_refuses_duplicate_identity_and_unknown_role(bad_row):
    feed = [{"mlbam_id": "1", "role": "hitter", "stats": _h(1)}, bad_row]
    with pytest.raises(study.StudyError, match="reconciled routed asset"):
        study.build_transfer(_transfer_registration(), feed, {})


def test_april_age_calls_registered_identity_helper_and_rejects_missing_or_future_dob(monkeypatch):
    from projections.data import identity

    original = identity.age_for
    calls = []

    def track(dob, season):
        calls.append((dob, season))
        return original(dob, season)

    monkeypatch.setattr(identity, "age_for", track)
    assert study._april_age({"birth_date": "1990-04-02"}, 2027) == 36
    assert calls == [("1990-04-02", 2027)]
    for row in ({}, {"birth_date": "invalid"}, {"birth_date": "2027-04-02"}):
        with pytest.raises(study.StudyError):
            study._april_age(row, 2027)
    monkeypatch.setattr(identity, "age_for", lambda dob, season: None)
    with pytest.raises(study.StudyError):
        study._april_age({"birth_date": "1990-04-02"}, 2027)


def test_component_checks_membership_without_materializing_a_season(monkeypatch):
    data = study.OriginData(2012, _seasons(), {"1": {"birth_date": "1990-01-01"}})

    def forbidden(year):
        raise AssertionError("component must not rebuild the complete season lists")

    monkeypatch.setattr(data, "season", forbidden)
    assert data.component("1", 2012, "hitter")["mlbam_id"] == "1"
    assert data.component("1", 2012, "pitcher") is None
    for year in (2009, 2013):
        with pytest.raises(study.StudyError, match="Season outside admitted origin view"):
            data.component("1", year, "hitter")
    with pytest.raises(study.StudyError, match="Unresolved identity"):
        data.component("2", 2012, "hitter")


def test_reviewed_charter_pin_and_every_real_source_manifest_path_exists():
    assert runner.CHARTER == "docs/registration-2026-11-02-mlb-trajectory/EVALUATION_CHARTER.md"
    assert runner.PINNED_CHARTER_HASH == "1a426c00ddfd96b9ed45a405d72fe22da2d234285145026cb19a51fa62e2a165"
    assert all((ROOT / relative).is_file() for relative in runner.SOURCE_MANIFEST)


def _synthetic_execution_repo(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-repo"
    root.mkdir()
    seasons = _seasons(2026)
    ids = set()
    for year, families in seasons.items():
        for family, folder, prefix in (("hitter", "historical", "hitting"),
                                        ("pitcher", "pitching", "pitching")):
            for row in families[family]:
                row["mlbam_id"] = str(970000000 + int(row["mlbam_id"]))
                ids.add(row["mlbam_id"])
            _json(root / "projections/data" / folder / f"{prefix}_{year}.json", families[family])
    identities = {pid: {"birth_date": "1988-01-01"} for pid in ids}
    _json(root / "projections/data/identity.json", identities)
    assert len(study.BUILDER_INPUT_MANIFEST) == 35
    assert all((root / path).is_file() for path in study.BUILDER_INPUT_MANIFEST)
    registration = root / runner.REGISTRATION
    registration.parent.mkdir(parents=True)
    registration.write_bytes(b"synthetic signed registration\r\n")
    registration_hash = hashlib.sha256(b"synthetic signed registration\n").hexdigest()
    charter = root / "docs/registration-2026-11-02-mlb-trajectory/EVALUATION_CHARTER.md"
    charter.parent.mkdir()
    charter.write_bytes(b"synthetic reviewed charter\r\n")
    monkeypatch.setattr(runner, "PINNED_REGISTRATION_HASH", registration_hash)
    monkeypatch.setattr(runner, "PINNED_CHARTER_HASH",
                        hashlib.sha256(b"synthetic reviewed charter\n").hexdigest())
    (root / runner.RECEIPT).write_text("synthetic authority " + registration_hash, encoding="ascii")
    source = "synthetic-source.py"
    (root / source).write_text("# synthetic source only\n", encoding="ascii")
    monkeypatch.setattr(runner, "SOURCE_MANIFEST", (source,))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    git_stubbed = False
    try:
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True,
                       capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        # Some sandboxes cannot create even synthetic .git metadata.
        git_stubbed = True
        detail = getattr(exc, "stderr", "") or str(exc)
        warnings.warn("Synthetic git init unavailable; only git diff is stubbed: " + detail.strip(),
                      RuntimeWarning)

        def git_diff(args, **kwargs):
            assert args[:3] == ["git", "diff", "--no-ext-diff"]
            assert kwargs["cwd"] == root
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        monkeypatch.setattr(runner.subprocess, "run", git_diff)
    admission = {key: True for key in ("cross_study_adjudicated", "final_2026_admitted", "lawful_use",
        "finality_departure_accepted", "identity_coverage_verified")}
    admission.update(revision_policy="synthetic immutable versions", source_use_decisions="synthetic only",
        files={path: {"acquired_at": "2026-11-01T00:00:00-04:00", "version": "synthetic-1", "final": True}
               for path in study.BUILDER_INPUT_MANIFEST},
        schedule_lengths={str(year): 60 if year == 2020 else 162 for year in range(2010, 2027)})
    _json(root / "admission.json", admission)
    authority = {"prospective_freeze_authorized": True, "before_first_2027_game_attested": True,
        "transfer_acquired_at": "2026-11-02T00:00:00-05:00", "first_full_season_2027_feed": True,
        "transfer_system": "Steamer", "transfer_season": 2027,
        "transfer_eligibility_and_role_provenance": "synthetic explicit routed roles"}
    feed = [{"mlbam_id": str(970000000 + i), "role": "hitter", "stats": _h(i)} for i in (1, 2)]
    feed.extend({"mlbam_id": str(970000010 + i), "role": "SP" if i % 2 else "RP", "stats": _p(i)}
                for i in (1, 2))
    feed_path = root / "synthetic-transfer.json"
    _json(feed_path, feed)
    authority.update(transfer_feed_path=feed_path.resolve().as_posix(),
                     transfer_feed_lf_sha256=runner.lf_hash(feed_path))
    _json(root / "authority.json", authority)
    return {"root": root, "admission": admission, "authority": authority, "feed": feed,
            "ids": ids, "git_stubbed": git_stubbed}


def _observe_phase_writes(monkeypatch, output):
    phases = []
    original = runner.write_json

    def observe(path, payload):
        if path.is_relative_to(output):
            phases.append(path.relative_to(output).as_posix())
        return original(path, payload)

    monkeypatch.setattr(runner, "write_json", observe)
    return phases


def _contains_key(value, key):
    if isinstance(value, dict):
        return key in value or any(_contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False


def test_historical_command_end_to_end_uses_real_default_forecasts_and_seals_players(tmp_path, monkeypatch, capsys):
    fixture = _synthetic_execution_repo(tmp_path, monkeypatch)
    root, output = fixture["root"], tmp_path / "historical-output"
    phases = _observe_phase_writes(monkeypatch, output)
    status = runner.main(["historical", "--root", root.as_posix(), "--output", output.as_posix(),
                          "--admission", (root / "admission.json").as_posix()])
    assert status == 0
    public_log = capsys.readouterr().out
    public = json.loads(public_log)
    aggregate_text = (output / "aggregate.json").read_text(encoding="ascii")
    aggregate = json.loads(aggregate_text)
    runner.assert_aggregate_safe(aggregate)
    # Independent numerical failures retain precedence over admission limits.
    assert aggregate["disposition"] == "FAIL"
    assert aggregate["failures"]
    assert aggregate["confirmation"] == "INELIGIBLE"
    assert all(gate["ineligible"] for gate in aggregate["gates"].values())
    assert public["disposition"] == aggregate["disposition"]
    assert not _contains_key(public, "values")
    assert len(aggregate["gates"]["full"]["intervals"]["H"]["candidate"]["values"]) == 2000
    assert all(pid not in public_log and pid not in aggregate_text for pid in fixture["ids"])
    expected = ["sealed/access-ledger.json", "sealed/custody.json", "sealed/counts.json",
                "sealed/counts-passed.json", "sealed/D1-predictions.json", "sealed/D2-predictions.json",
                "sealed/D3-predictions.json", "sealed/H-predictions.json", "sealed/all-predictions-frozen.json",
                "sealed/evaluation-access.json", "sealed/evaluations.json", "aggregate.json"]
    assert phases == expected
    assert all((output / path).is_file() for path in expected)
    for fold in study.FOLDS[:4]:
        record = json.loads((output / "sealed" / (fold.name + "-predictions.json")).read_text(encoding="ascii"))
        runner.verify_record(record)
        pitchers = [row for row in record["rows"] if row["role"] in ("SP", "RP")]
        assert pitchers and all(row["F1"] is not None for row in pitchers)
        assert all(all(row.get(model) is not None for model in ("flat", "hand_set", "candidate"))
                   for row in pitchers)
    with pytest.raises(study.StudyError, match="Output already exists"):
        runner.run(root, output, fixture["admission"])


def test_prospective_command_end_to_end_uses_real_default_forecasts_and_freezes_before_feed(tmp_path, monkeypatch, capsys):
    fixture = _synthetic_execution_repo(tmp_path, monkeypatch)
    root, output = fixture["root"], tmp_path / "prospective-output"
    phases = _observe_phase_writes(monkeypatch, output)
    original_transfer = study.build_transfer

    def observe_transfer(record, feed, identities):
        assert phases == ["sealed/authority-before-access.json", "sealed/custody.json",
                          "sealed/counts.json", "sealed/P-Marcel.json"]
        assert (output / "sealed/P-Marcel.json").is_file()
        return original_transfer(record, feed, identities)

    monkeypatch.setattr(study, "build_transfer", observe_transfer)
    status = runner.main(["prospective", "--root", root.as_posix(), "--output", output.as_posix(),
        "--admission", (root / "admission.json").as_posix(),
        "--authority", (root / "authority.json").as_posix(),
        "--transfer-feed", (root / "synthetic-transfer.json").as_posix()])
    assert status == 0
    public_log = capsys.readouterr().out
    aggregate_text = (output / "aggregate.json").read_text(encoding="ascii")
    aggregate = json.loads(aggregate_text)
    runner.assert_aggregate_safe(aggregate)
    assert aggregate["status"] == json.loads(public_log)["status"] == "FROZEN"
    assert aggregate["records"] == 2
    assert all(pid not in public_log and pid not in aggregate_text for pid in fixture["ids"])
    expected = ["sealed/authority-before-access.json", "sealed/custody.json", "sealed/counts.json",
                "sealed/P-Marcel.json", "sealed/P-Steamer-transfer.json", "aggregate.json"]
    assert phases == expected
    assert all((output / path).is_file() for path in expected)
    for name in ("P-Marcel.json", "P-Steamer-transfer.json"):
        record = json.loads((output / "sealed" / name).read_text(encoding="ascii"))
        runner.verify_record(record)
        pitchers = [row for row in record["rows"] if row["role"] in ("SP", "RP")]
        assert pitchers and all(row["F1"] is not None for row in pitchers)
        assert all(all(row.get(model) is not None for model in ("flat", "hand_set", "candidate"))
                   for row in record["rows"] if row["complete"])
        if name == "P-Marcel.json":
            assert record["training_origins"] == list(study.FOLDS[-1].training)
            assert all(fit["n"] > 0 for fit in record["fits"].values())
    with pytest.raises(study.StudyError, match="Output already exists"):
        runner.prospective_freeze(root, output, fixture["admission"], fixture["authority"],
                                  lambda: fixture["feed"])


@pytest.mark.parametrize("command", ["historical", "prospective"])
def test_both_commands_refuse_changed_charter_before_output_or_rows(tmp_path, monkeypatch, command):
    fixture = _synthetic_execution_repo(tmp_path, monkeypatch)
    root, output = fixture["root"], tmp_path / "blocked-output"
    (root / runner.CHARTER).write_text("changed synthetic charter\n", encoding="ascii")

    def forbidden(*args):
        raise AssertionError("row access before charter admission")

    monkeypatch.setattr(runner, "counts_only", forbidden)
    with pytest.raises(study.StudyError):
        if command == "historical":
            runner.run(root, output, fixture["admission"])
        else:
            runner.prospective_freeze(root, output, fixture["admission"], fixture["authority"], forbidden)
    assert not output.exists()


def test_prospective_views_reject_input_changed_after_custody(tmp_path, monkeypatch):
    fixture = _synthetic_execution_repo(tmp_path, monkeypatch)
    root, output = fixture["root"], tmp_path / "changed-input-output"
    original_counts = runner.counts_only

    def counts_then_change(repo):
        counts = original_counts(repo)
        path = repo / "projections/data/historical/hitting_2010.json"
        path.write_bytes(path.read_bytes() + b"\n")
        return counts

    monkeypatch.setattr(runner, "counts_only", counts_then_change)
    with pytest.raises(study.StudyError, match="frozen input hash"):
        runner.prospective_freeze(root, output, fixture["admission"], fixture["authority"],
                                  lambda: fixture["feed"])
    assert (output / "sealed/custody.json").is_file()
    assert not (output / "sealed/P-Marcel.json").exists()


def test_direct_script_help_imports_without_pythonpath_or_repository_cwd(tmp_path):
    environ = dict(os.environ)
    environ.pop("PYTHONPATH", None)
    result = subprocess.run([sys.executable, (ROOT / "scripts/run_mlb_trajectory_study.py").as_posix(), "--help"],
                            cwd=tmp_path, env=environ, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "historical" in result.stdout and "prospective" in result.stdout


def test_main_drops_every_values_key_without_mutating_saved_aggregate(tmp_path, monkeypatch, capsys):
    admission = tmp_path / "admission.json"
    _json(admission, {})
    payload = {"disposition": "INELIGIBLE", "values": [1, 2],
               "nested": [{"values": [3], "kept": {"values": [4], "count": 5}}]}
    before = deepcopy(payload)
    monkeypatch.setattr(runner, "guard", lambda *args: None)
    monkeypatch.setattr(runner, "run", lambda *args: payload)
    assert runner.main(["historical", "--root", tmp_path.as_posix(),
                        "--output", (tmp_path / "unused").as_posix(),
                        "--admission", admission.as_posix()]) == 0
    public = json.loads(capsys.readouterr().out)
    assert public == {"disposition": "INELIGIBLE", "nested": [{"kept": {"count": 5}}]}
    assert payload == before


@pytest.mark.parametrize("slice_name", ["hitter", "SP", "RP", "cold_start", "graduate"])
def test_unresolved_slice_membership_counts_against_applicable_coverage(slice_name):
    frozen = _admission_population()
    field = "role" if slice_name in study.ROLES else slice_name
    for row in frozen:
        if field == "role":
            row["role"] = slice_name if row["mlbam_id"] <= 26 else (
                "SP" if slice_name != "SP" else "hitter")
        else:
            row[field] = row["mlbam_id"] <= 26
        if 27 <= row["mlbam_id"] <= 30:
            row.update({field: None, "complete": False})
    matched = [deepcopy(row) for row in frozen if row["complete"]]
    result = study.gate_admission(matched, frozen)
    for fold in study.FOLDS[:4]:
        coverage = result["coverage"][fold.name]
        assert coverage["coverage"] == pytest.approx(236 / 240)
        assert coverage["slices"][slice_name] == {
            "frozen": 30, "matched": 26, "coverage": 26 / 30, "exempt": False}
        assert f"{fold.name}: {slice_name} coverage below 90 percent" in result["ineligible"]
    assert not any("overall coverage" in reason for reason in result["ineligible"])


def test_bootstrap_preserves_each_assets_multiplicity_across_origins(monkeypatch):
    rows = [{"mlbam_id": i + 1, "origin": fold.origin, "H3": i,
             "candidate": i, "flat": i, "hand_set": -i}
            for fold in study.FOLDS[:4] for i in range(12)
            if i != 11 or fold.name != "D2"]
    captured = []
    original = study._origin_metrics

    def observe(sample):
        if not captured:
            captured.append(list(sample))
        return original(sample)

    monkeypatch.setattr(study, "_origin_metrics", observe)
    monkeypatch.setattr(study, "BOOTSTRAP_REPLICATES", 1)
    study.bootstrap({"full": rows, "top300": deepcopy(rows)})
    assert len(captured) == 1 and captured[0]
    counts = {}
    for row in captured[0]:
        key = (row["mlbam_id"], row["origin"])
        counts[key] = counts.get(key, 0) + 1
    assert max(counts.values()) > 1
    for pid in {row["mlbam_id"] for row in rows}:
        origins = {row["origin"] for row in rows if row["mlbam_id"] == pid}
        assert len({counts.get((pid, origin), 0) for origin in origins}) == 1


def _diagnostic_row(pid, origin, role="RP"):
    family = "hitter" if role == "hitter" else "pitcher"
    annual = [12345.6789 + pid + offset * 100 for offset in range(3)]
    return {"mlbam_id": str(pid), "origin": origin, "role": role, "complete": True,
            "cold_start": False, "graduate": False, "both_component": False,
            "age": 27, "age_33_plus": False, "rho": .8, "volume": 100,
            "F1": pid, "C_fam": 2, "V": pid - 2, "B": -10,
            "candidate": pid, "flat": pid, "hand_set": pid,
            "candidate_multiplier": 1, "H3": study.weighted_h3(annual),
            "H3_unweighted": study.unweighted_h3(annual), "H3_per162": study.weighted_h3(annual),
            "annual_U": annual, "verified_zero_production": False,
            "annual_categories": [{category: 90000.12345 + pid * 100 + offset * 10 + index
                for index, category in enumerate(study.CATEGORIES[family])} for offset in range(3)],
            "forecast_categories": {category: 60000.12345 + pid * 100 + index
                for index, category in enumerate(study.CATEGORIES[family])}}


@pytest.mark.parametrize("hitter_n,pitcher_n", [(0, 0), (0, 1), (28, 1), (29, 1), (30, 1), (30, 30)])
def test_public_diagnostics_suppress_small_populations_and_exact_pitcher_outcomes(tmp_path, hitter_n, pitcher_n):
    rows = [_diagnostic_row(i + 1, 2018, "hitter" if i < hitter_n else "RP")
            for i in range(hitter_n + pitcher_n)]
    diagnostic = study.describe_study([{"fold": "D1", "rows": rows}], [])
    runner.write_json(tmp_path / "aggregate.json", {"diagnostics": diagnostic})
    public = (tmp_path / "aggregate.json").read_text(encoding="ascii")
    result = json.loads(public)["diagnostics"]["D1"]
    n = len(rows)
    assert result["coverage"] == {"frozen": n, "matched": n}
    assert result["outcome_distribution"]["n"] == n
    quantiles = result["outcome_distribution"]["quantiles"]
    if n < 30:
        assert quantiles is None
    else:
        assert quantiles == pytest.approx(np.percentile([row["H3"] for row in rows],
                                                        [5, 25, 50, 75, 95], method="linear"))
    for family, count in (("hitter", hitter_n), ("pitcher", pitcher_n)):
        summary = result["family_contributions"][family]
        assert summary["n"] == count
        assert all((value is None) == (count < 30) for key, value in summary.items() if key != "n")
    for summary in (result["multiplier_and_baseline"], *result["component_movement"].values(),
                    result["zero_production_fraction"]):
        assert summary["n"] == n
        assert all((value is None) == (n < 30) for key, value in summary.items()
                   if key not in ("n", "predicted_n"))
    if pitcher_n == 1:
        pitcher = rows[-1]
        exact = pitcher["annual_U"] + [value for annual in pitcher["annual_categories"]
                                       for value in annual.values()]
        assert all(str(value) not in public for value in exact)


def test_top300_role_diagnostics_preserve_failure_hidden_in_full_gate(tmp_path, monkeypatch):
    frozen = []
    for fold in study.FOLDS[:4]:
        rows = []
        for i in range(390):
            row = _diagnostic_row(i + 1, fold.origin, "RP" if i < 120 else "hitter")
            row.update(H3=i, candidate=29 - i if i < 30 else i, flat=i, hand_set=i,
                       F1=1000 - i if i < 30 else (-1000 - i if i < 120 else 500 - i))
            rows.append(row)
        frozen.append(runner.freeze_record(tmp_path / f"{fold.name}.json", {
            "fold": fold.name, "origin": fold.origin, "rows": rows,
            "top300": study.top_ids(rows), "fits": {}}))
    before = deepcopy(frozen)
    monkeypatch.setattr(study, "score_frozen", lambda record, *args: {
        "fold": record["fold"], "origin": record["origin"], "rows": deepcopy(record["rows"])})
    monkeypatch.setattr(study, "score_gates", lambda *args: {"release": "SEPARATE_OWNER_DECISION"})
    aggregate, sealed = runner.evaluate_frozen(frozen, lambda origin: None, {})
    assert frozen == before
    assert len(sealed["evaluations"]) == 4
    assert set(aggregate["diagnostics"]) == {"full", "top300"}
    for fold in study.FOLDS[:4]:
        full = aggregate["diagnostics"]["full"][fold.name]
        top = aggregate["diagnostics"]["top300"][fold.name]
        assert full["coverage"] == {"frozen": 390, "matched": 390}
        assert top["coverage"] == {"frozen": 300, "matched": 300}
        assert full["slices"]["RP"]["n"] == 120
        assert top["slices"]["RP"]["n"] == 30
        assert full["slices"]["RP"]["metrics"]["gaps"]["hand_set"] > -.05
        assert full["slices"]["RP"]["role_claim_failures"] == []
        assert top["slices"]["RP"]["metrics"]["gaps"]["hand_set"] < -.05
        assert top["slices"]["RP"]["role_claim_failures"] == ["flat", "hand_set"]
        assert "top50" in full and "top50" not in top


@pytest.mark.parametrize("failure,exit_code", [(RuntimeError, None), (KeyboardInterrupt, None),
                                              (SystemExit, None), (SystemExit, 0), (SystemExit, 7)])
def test_main_swallows_failure_log_write_errors_without_public_row_values(
        tmp_path, monkeypatch, capsys, failure, exit_code):
    admission = tmp_path / "admission.json"
    _json(admission, {})
    output = tmp_path / "failed-output"
    (output / "sealed").mkdir(parents=True)
    sentinel = "SYNTHETIC_PRIVATE_ROW_SENTINEL"
    original = Path.open

    def fail_run(*args):
        raise failure(sentinel if exit_code is None else exit_code)

    def fail_log(path, *args, **kwargs):
        if path.name == "native-failure.txt":
            raise OSError(sentinel)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(runner, "guard", lambda *args: None)
    monkeypatch.setattr(runner, "run", fail_run)
    monkeypatch.setattr(Path, "open", fail_log)
    status = runner.main(["historical", "--root", tmp_path.as_posix(),
                          "--output", output.as_posix(), "--admission", admission.as_posix()])
    assert status == (130 if failure is KeyboardInterrupt else (exit_code or 1))
    public = capsys.readouterr()
    assert public.out == '{"status":"STOPPED","native_failure":"sealed"}\n'
    assert public.err == ""
    assert sentinel not in public.out + public.err
