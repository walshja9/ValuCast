"""Reader tests for the fail-soft plate-discipline store."""
import json

from web.pitch_discipline_store import PitchDisciplineStore


def _write_artifact(tmp_path, players, *, zone_shipped=True):
    payload = {
        "artifact": "valucast_pitch_discipline",
        "generated_at": "2026-07-10T00:00:00+00:00",
        "as_of": "2026-07-10",
        "metric_labels": {
            "swing_pct": "Swing%", "whiff_pct": "Whiff%", "swstr_pct": "SwStr%",
            "chase_pct": "Chase%", "z_swing_pct": "Z-Swing%",
            "z_contact_pct": "Z-Contact%", "zone_pct": "Zone%",
        },
        "cohorts": {"min_pitches": 300, "zone_metrics_shipped": zone_shipped},
        "players": players,
    }
    path = tmp_path / "disc.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _bucket(pitches, *, qualifies, zone_estimated=True, percentiles=None):
    return {
        "pitches": pitches,
        "qualifies": qualifies,
        "zone_estimated": zone_estimated,
        "rates": {
            "swing_pct": 37.4, "whiff_pct": 24.8, "swstr_pct": 9.2,
            "chase_pct": 15.8, "z_swing_pct": 64.3, "z_contact_pct": 80.6,
            "zone_pct": 44.5,
        },
        "percentiles": percentiles or {},
    }


def test_fail_soft_missing_artifact(tmp_path):
    store = PitchDisciplineStore(path=tmp_path / "does_not_exist.json")
    assert store.groups_for("701527") == []
    assert store.as_of is None


def test_fail_soft_malformed_artifact(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    store = PitchDisciplineStore(path=path)
    assert store.groups_for("701527") == []


def test_fail_soft_top_level_list_artifact(tmp_path):
    # Valid JSON, wrong schema: a top-level list must degrade to empty, not raise.
    path = tmp_path / "list.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    store = PitchDisciplineStore(path=path)
    assert store.groups_for("701527") == []
    assert store.as_of is None


def test_fail_soft_rates_as_string(tmp_path):
    # Valid JSON, per-bucket wrong schema: rates/percentiles as strings must not
    # raise; the empty-metrics group is filtered out.
    path = _write_artifact(tmp_path, {
        "1": {"AA": {
            "pitches": 400, "qualifies": True, "zone_estimated": True,
            "rates": "not-a-dict", "percentiles": "also-not-a-dict",
        }},
    })
    store = PitchDisciplineStore(path=path)
    assert store.groups_for("1") == []


def test_empty_id_returns_empty(tmp_path):
    path = _write_artifact(tmp_path, {"1": {"AA": _bucket(400, qualifies=True)}})
    store = PitchDisciplineStore(path=path)
    assert store.groups_for(None) == []
    assert store.groups_for("") == []


def test_estimated_flag_split(tmp_path):
    path = _write_artifact(tmp_path, {
        "701527": {"AA": _bucket(811, qualifies=True, zone_estimated=True,
                                 percentiles={"whiff_pct": 75, "chase_pct": 60})},
    })
    store = PitchDisciplineStore(path=path)
    groups = store.groups_for("701527")
    assert len(groups) == 1
    metrics = {m["key"]: m for m in groups[0]["metrics"]}
    # Exact metrics measured (estimated False):
    assert metrics["swing_pct"]["estimated"] is False
    assert metrics["whiff_pct"]["estimated"] is False
    assert metrics["swstr_pct"]["estimated"] is False
    # Zone metrics estimated True (level was pixel-calibrated):
    assert metrics["chase_pct"]["estimated"] is True
    assert metrics["zone_pct"]["estimated"] is True
    assert groups[0]["estimated"] is True


def test_aaa_real_coords_not_estimated(tmp_path):
    path = _write_artifact(tmp_path, {
        "1": {"AAA": _bucket(500, qualifies=True, zone_estimated=False,
                             percentiles={"whiff_pct": 60})},
    })
    store = PitchDisciplineStore(path=path)
    groups = store.groups_for("1")
    metrics = {m["key"]: m for m in groups[0]["metrics"]}
    # AAA carries real pX/pZ -> zone metrics are measured, not estimated.
    assert metrics["chase_pct"]["estimated"] is False
    assert groups[0]["estimated"] is False


def test_min_sample_gate_no_group_below_floor(tmp_path):
    path = _write_artifact(tmp_path, {
        "1": {"AA": _bucket(150, qualifies=False, percentiles={})},
    })
    store = PitchDisciplineStore(path=path)
    # A non-qualifying bucket yields no group at all.
    assert store.groups_for("1") == []


def test_per_level_never_blended(tmp_path):
    path = _write_artifact(tmp_path, {
        "1": {
            "AA": _bucket(400, qualifies=True, zone_estimated=True,
                          percentiles={"whiff_pct": 70}),
            "AAA": _bucket(500, qualifies=True, zone_estimated=False,
                           percentiles={"whiff_pct": 55}),
        },
    })
    store = PitchDisciplineStore(path=path)
    groups = store.groups_for("1")
    levels = [g["level"] for g in groups]
    assert levels == ["AAA", "AA"]   # highest level first, two separate groups


def test_contextual_metric_has_no_pct(tmp_path):
    # swing_pct is contextual: raw value present, pct None (no fill judgment).
    path = _write_artifact(tmp_path, {
        "1": {"AA": _bucket(400, qualifies=True, percentiles={"whiff_pct": 70})},
    })
    store = PitchDisciplineStore(path=path)
    metrics = {m["key"]: m for m in store.groups_for("1")[0]["metrics"]}
    assert metrics["swing_pct"]["pct"] is None
    assert metrics["swing_pct"]["display"] == "37.4%"
    assert metrics["whiff_pct"]["pct"] == 70


def test_zone_group_cut_no_zone_metrics(tmp_path):
    # If the zone group is cut (calibration failed), buckets carry only exact rates.
    exact_only = {
        "pitches": 400, "qualifies": True, "zone_estimated": True,
        "rates": {"swing_pct": 37.4, "whiff_pct": 24.8, "swstr_pct": 9.2},
        "percentiles": {"whiff_pct": 70, "swstr_pct": 72},
    }
    path = _write_artifact(tmp_path, {"1": {"AA": exact_only}}, zone_shipped=False)
    store = PitchDisciplineStore(path=path)
    groups = store.groups_for("1")
    keys = {m["key"] for m in groups[0]["metrics"]}
    assert keys == {"swing_pct", "whiff_pct", "swstr_pct"}
    assert groups[0]["estimated"] is False
