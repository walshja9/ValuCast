"""Reader tests for the fail-soft AAA-Statcast store."""
import json

from web.aaa_statcast_store import AaaStatcastStore


def _write_artifact(tmp_path, *, pitchers=None, hitters=None, as_of="2026-07-14"):
    payload = {
        "artifact": "valucast_aaa_statcast_features",
        "schema_version": 1,
        "generated_at": "2026-07-14T00:00:00+00:00",
        "as_of": as_of,
        "source": "baseball_savant_statcast_minors_aaa",
        "pitchers": pitchers or {},
        "hitters": hitters or {},
    }
    path = tmp_path / "aaa.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _pitcher():
    return {
        "n_pitches": 900,
        "overall": {
            "whiff_pct": 28.0, "csw_pct": 30.5, "chase_pct": 31.2,
            "zone_pct": 48.0, "gb_pct": 44.0,
        },
        "pitch_types": {
            "FF": {"n": 400, "usage_pct": 44.4, "velo": 95.2, "ivb": 16.9,
                   "hb": 8.1, "spin": 2320, "ext": 6.4},
            "SL": {"n": 300, "usage_pct": 33.3, "velo": 86.1, "ivb": 1.2,
                   "hb": -4.0, "spin": 2600, "ext": 6.3},
        },
    }


def _hitter():
    return {
        "n_pitches": 700, "n_bip": 120,
        "avg_ev": 90.4, "max_ev": 112.3, "hardhit_pct": 47.5, "avg_la": 12.1,
        "whiff_pct": 24.0, "chase_pct": 27.0, "gb_pct": 43.0,
    }


def test_fail_soft_missing_artifact(tmp_path):
    store = AaaStatcastStore(path=tmp_path / "nope.json")
    assert store.pitch_shape_for("803349") == {}
    assert store.contact_quality_for("699024") == {}
    assert store.as_of is None


def test_fail_soft_malformed_artifact(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    store = AaaStatcastStore(path=path)
    assert store.pitch_shape_for("1") == {}
    assert store.contact_quality_for("1") == {}


def test_fail_soft_top_level_list(tmp_path):
    path = tmp_path / "list.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    store = AaaStatcastStore(path=path)
    assert store.pitch_shape_for("1") == {}
    assert store.as_of is None


def test_fail_soft_tables_as_string(tmp_path):
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps({
        "pitchers": "not-a-dict", "hitters": "also-not", "as_of": "2026-07-14",
    }), encoding="utf-8")
    store = AaaStatcastStore(path=path)
    assert store.pitch_shape_for("1") == {}
    assert store.contact_quality_for("1") == {}


def test_empty_id_returns_empty(tmp_path):
    path = _write_artifact(tmp_path, pitchers={"1": _pitcher()})
    store = AaaStatcastStore(path=path)
    assert store.pitch_shape_for(None) == {}
    assert store.pitch_shape_for("") == {}
    assert store.contact_quality_for(None) == {}


def test_pitch_shape_section(tmp_path):
    path = _write_artifact(tmp_path, pitchers={"803349": _pitcher()})
    store = AaaStatcastStore(path=path)
    section = store.pitch_shape_for(803349)  # int id resolves via str()
    assert section["as_of"] == "2026-07-14"
    assert section["n_pitches"] == 900
    labels = [pt["label"] for pt in section["pitch_types"]]
    # FF sorts before SL by the display order.
    assert labels == ["4-Seam", "Slider"]
    ff = section["pitch_types"][0]
    assert ff["usage"] == "44.4%"
    ff_rows = {r["label"]: r["value"] for r in ff["rows"]}
    assert ff_rows["Velo"] == "95.2 mph"
    assert ff_rows["IVB"] == "+16.9 in"
    assert ff_rows["Spin"] == "2320 rpm"
    outcomes = {o["label"]: o["value"] for o in section["outcomes"]}
    assert outcomes["Whiff%"] == "28.0%"
    assert outcomes["CSW%"] == "30.5%"


def test_pitch_shape_no_est_tag_anywhere(tmp_path):
    # MEASURED source: no 'estimated' key/marker on any row (unlike pitch_discipline).
    path = _write_artifact(tmp_path, pitchers={"1": _pitcher()})
    store = AaaStatcastStore(path=path)
    section = store.pitch_shape_for("1")
    assert "estimated" not in json.dumps(section).lower()
    for pt in section["pitch_types"]:
        for row in pt["rows"]:
            assert "estimated" not in row
    for o in section["outcomes"]:
        assert "estimated" not in o


def test_contact_quality_section(tmp_path):
    path = _write_artifact(tmp_path, hitters={"699024": _hitter()})
    store = AaaStatcastStore(path=path)
    section = store.contact_quality_for("699024")
    assert section["n_bip"] == 120
    rows = {r["label"]: r["value"] for r in section["rows"]}
    assert rows["Avg Exit Velo"] == "90.4 mph"
    assert rows["Max Exit Velo"] == "112.3 mph"
    assert rows["Hard-Hit%"] == "47.5%"
    assert rows["Launch Angle"] == "12.1°"
    assert rows["Whiff%"] == "24.0%"


def test_unknown_player_returns_empty(tmp_path):
    path = _write_artifact(tmp_path, pitchers={"1": _pitcher()})
    store = AaaStatcastStore(path=path)
    assert store.pitch_shape_for("999") == {}
    assert store.contact_quality_for("1") == {}   # a pitcher id is not a hitter


def test_pitcher_outcomes_only_no_pitch_types(tmp_path):
    # A pitcher whose pitch types all fell below the type gate still shows outcomes.
    rec = {"n_pitches": 500, "overall": {"whiff_pct": 26.0, "csw_pct": 29.0}}
    path = _write_artifact(tmp_path, pitchers={"1": rec})
    store = AaaStatcastStore(path=path)
    section = store.pitch_shape_for("1")
    assert section["pitch_types"] == []
    assert {o["label"] for o in section["outcomes"]} == {"Whiff%", "CSW%"}


def test_empty_record_yields_no_section(tmp_path):
    # A pitcher record with neither pitch types nor outcomes -> no section.
    path = _write_artifact(tmp_path, pitchers={"1": {"n_pitches": 300}})
    store = AaaStatcastStore(path=path)
    assert store.pitch_shape_for("1") == {}
