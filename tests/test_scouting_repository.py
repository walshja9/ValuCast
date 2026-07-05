import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scouting import repository
from scouting.voice import validate_report_text
from scouting.repository import build_scouting_repository
from scripts.validate_scouting_repository import validate_scouting_repository
from web.public_snapshot_store import PublicSnapshotStore


def _write_snapshot(tmp_path):
    payload = {
        "schema_version": "1.1",
        "artifact": "valucast_public_dynasty_snapshot",
        "generated_at": "2026-06-16T00:00:00+00:00",
        "generated_by": "valucast",
        "source_policy": {
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used_for_score": False,
            "market_values_used_for_score": False,
        },
        "validation": {
            "ready_for_live_consumers": False,
            "duplicate_identity_count": 0,
            "required_fields_complete": True,
        },
        "players": [
            {
                "id": "vc_prospect_1_hitter",
                "player_type": "prospect",
                "name": "Model Strong",
                "mlbam_id": 1,
                "role": "hitter",
                "bats": "L",
                "throws": "R",
                "positions": ["SS"],
                "team": "BOS",
                "mlb_team": "BOS",
                "age": 20,
                "rank": 1,
                "value": 55.5,
                "value_scale": "0_100_valucast_dynasty_score",
                "value_source": "prospect_model_v0_6",
                "confidence": "medium",
                "updated_at": "2026-06-16T00:00:00+00:00",
                "status": "candidate_ready",
                "prospect_rank": 1,
                "level": "AA",
                "eta": 2027,
                "score_source": "prospect_model_v0_6",
                "stat_line": {
                    "pa": 224,
                    "ops": 0.976,
                    "iso": 0.261,
                    "k_pct": 12.9,
                    "bb_pct": 9.8,
                    "avg": 0.318,
                    "obp": 0.397,
                    "slg": 0.579,
                },
                "combined_season_stat_line": {
                    "role": "hitter",
                    "season": 2026,
                    "level": "AA",
                    "levels": ["AA"],
                    "level_label": "AA",
                    "sample": 224,
                    "sample_unit": "PA",
                    "pa": 224,
                    "ops": 0.976,
                    "iso": 0.261,
                    "k_pct": 12.9,
                    "bb_pct": 9.8,
                    "avg": 0.318,
                    "obp": 0.397,
                    "slg": 0.579,
                    "babip": 0.340,
                },
                "context": {
                    "stat_line_source": "valucast_input_contract",
                    "stat_line_source_kind": "current_season",
                    "stat_line_sample": 224,
                    "stat_line_sample_unit": "PA",
                    "stat_line_sample_season": 2026,
                },
            },
            {
                "id": "vc_prospect_2_pitcher",
                "player_type": "prospect",
                "name": "Starter Arm",
                "mlbam_id": 2,
                "role": "pitcher",
                "bats": "L",
                "throws": "L",
                "positions": ["SP"],
                "team": "SEA",
                "mlb_team": "SEA",
                "age": 21,
                "rank": 2,
                "value": 50.0,
                "value_scale": "0_100_valucast_dynasty_score",
                "value_source": "prospect_model_v0_6",
                "confidence": "medium",
                "updated_at": "2026-06-16T00:00:00+00:00",
                "status": "candidate_ready",
                "prospect_rank": 2,
                "level": "AA",
                "eta": 2027,
                "score_source": "prospect_model_v0_6",
                "stat_line": {
                    "ip": 55.7,
                    "k_per_9": 13.3,
                    "bb_per_9": 1.1,
                    "k_bb_pct": 37.7,
                    "era": 1.13,
                    "whip": 0.66,
                },
                "combined_season_stat_line": {
                    "role": "pitcher",
                    "season": 2026,
                    "level": "AA",
                    "levels": ["AA"],
                    "level_label": "AA",
                    "sample": 55.7,
                    "sample_unit": "IP",
                    "ip": 55.7,
                    "k_per_9": 13.3,
                    "bb_per_9": 1.1,
                    "k_bb_pct": 37.7,
                    "era": 1.13,
                    "whip": 0.66,
                },
                "context": {
                    "stat_line_source": "valucast_input_contract",
                    "stat_line_source_kind": "current_season",
                    "stat_line_sample": 55.7,
                    "stat_line_sample_unit": "IP",
                    "stat_line_sample_season": 2026,
                },
            },
        ],
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _add_mlb_rows(snapshot_path):
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    data["players"].extend(
        [
            {
                "id": "vc_mlb_10_hitter",
                "player_type": "mlb",
                "name": "Established Bat",
                "mlbam_id": 10,
                "role": "hitter",
                "positions": ["OF"],
                "team": "LAD",
                "mlb_team": "LAD",
                "age": 27,
                "rank": 4,
                "value": 62.0,
                "value_scale": "0_100_valucast_dynasty_score",
                "value_source": "valucast_mlb_dynasty_layer",
                "confidence": "high",
                "updated_at": "2026-06-16T00:00:00+00:00",
                "status": "candidate_ready",
                "stat_line": {
                    "source": "valucast_current_projection",
                    "stats": {
                        "AVG": 0.287,
                        "OBP": 0.374,
                        "OPS": 0.841,
                        "HR": 31.4,
                        "SB": 12.0,
                        "PA": 640.0,
                        "R": 94.2,
                        "RBI": 101.3,
                    },
                },
            },
            {
                "id": "vc_mlb_20_pitcher",
                "player_type": "mlb",
                "name": "Established Arm",
                "mlbam_id": 20,
                "role": "pitcher",
                "positions": ["SP"],
                "team": "SEA",
                "mlb_team": "SEA",
                "age": 28,
                "rank": 5,
                "value": 58.0,
                "value_scale": "0_100_valucast_dynasty_score",
                "value_source": "valucast_mlb_dynasty_layer",
                "confidence": "high",
                "updated_at": "2026-06-16T00:00:00+00:00",
                "status": "candidate_ready",
                "stat_line": {
                    "source": "valucast_current_projection",
                    "stats": {
                        "ERA": 2.88,
                        "WHIP": 1.0,
                        "IP": 183.7,
                        "K": 224.4,
                        "W": 12.7,
                        "QS": 18.4,
                        "SV": 0.0,
                    },
                },
            },
            {
                "id": "vc_mlb_999_hitter",
                "player_type": "mlb",
                "name": "Outside Mlb Cap",
                "mlbam_id": 999,
                "role": "hitter",
                "positions": ["1B"],
                "team": "TEX",
                "mlb_team": "TEX",
                "age": 31,
                "rank": 999,
                "value": 1.0,
                "value_scale": "0_100_valucast_dynasty_score",
                "value_source": "valucast_mlb_dynasty_layer",
                "confidence": "low",
                "updated_at": "2026-06-16T00:00:00+00:00",
                "status": "candidate_ready",
                "stat_line": {
                    "source": "valucast_current_projection",
                    "stats": {"AVG": 0.230, "OBP": 0.300, "HR": 9.0, "PA": 420.0},
                },
            },
        ]
    )
    snapshot_path.write_text(json.dumps(data), encoding="utf-8")


class _FakeStatcastStore:
    def __init__(self):
        self.groups_by_id = {
            "10": [
                {
                    "label": "Batting",
                    "metrics": [
                        {
                            "label": "Barrel %",
                            "pct": 88,
                            "raw": 17.2,
                            "display": "17.2%",
                        },
                        {
                            "label": "Whiff %",
                            "pct": 32,
                            "raw": 29.5,
                            "display": "29.5%",
                        },
                    ],
                }
            ]
        }

    def display_groups(self, mlbam_id, prefer_pitching=False):
        return self.groups_by_id.get(str(mlbam_id), [])


def _row_by_name(snapshot_path, name):
    store = PublicSnapshotStore(snapshot_path)
    return next(row for row in store.get_all() if row.name == name)


def _write_artifact(tmp_path, payload):
    artifact_path = tmp_path / "reports.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    return artifact_path


def test_scouting_repository_builds_stat_grounded_reports(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)

    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )

    assert payload["artifact"] == "valucast_scouting_report_repository"
    assert payload["source_policy"]["llm_generated"] is False
    assert payload["source_policy"]["external_rankings_used_for_report"] is False
    assert payload["validation"]["ready_for_repository"] is True
    assert payload["summary"]["report_count"] == 2
    assert payload["reports"][0]["report"]
    assert payload["reports"][0]["usage"] == "scouting_repository_context_not_live_rank_or_value"


def test_scouting_repository_default_covers_deeper_prospect_cards(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    deep_card = json.loads(json.dumps(data["players"][0]))
    deep_card.update(
        {
            "id": "vc_prospect_384_hitter",
            "name": "Deep Card",
            "mlbam_id": 384,
            "rank": 384,
            "prospect_rank": 384,
            "value": 27.2,
        }
    )
    outside_coverage = json.loads(json.dumps(data["players"][0]))
    outside_coverage.update(
        {
            "id": "vc_prospect_501_hitter",
            "name": "Outside Coverage",
            "mlbam_id": 501,
            "rank": 501,
            "prospect_rank": 501,
            "value": 18.0,
        }
    )
    data["players"].extend([deep_card, outside_coverage])
    snapshot_path.write_text(json.dumps(data), encoding="utf-8")

    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )

    names = {report["name"] for report in payload["reports"]}
    assert payload["summary"]["max_prospect_rank"] == 500
    assert "Deep Card" in names
    assert "Outside Coverage" not in names


def test_scouting_repository_builds_guarded_mlb_reports(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    _add_mlb_rows(snapshot_path)

    with patch("scouting.repository.StatcastStore", return_value=_FakeStatcastStore()):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
            max_dynasty_rank=50,
        )

    reports = {report["name"]: report for report in payload["reports"]}
    hitter = reports["Established Bat"]
    hitter_row = _row_by_name(snapshot_path, "Established Bat")
    grounding = repository._llm_grounding(
        hitter_row,
        {},
        None,
        statcast_groups=hitter["statcast_groups"],
    )

    assert hitter["player_type"] == "mlb"
    assert hitter["published_report_source"] == "deterministic"
    assert "bats" not in hitter
    assert "throws" not in hitter
    assert "dynasty_value" not in hitter
    assert "Outside Mlb Cap" not in reports
    assert hitter["report"] == (
        "The Statcast card is carried by plus Barrel % at the 88th percentile (17.2%), "
        "with well below-average Whiff % at the 32nd percentile (29.5%) as the drag. "
        "A power-first line projects to .287 AVG, .374 OBP, .841 OPS, 31 HR, 12 SB over 640 PA."
    )
    assert validate_report_text(hitter["report"], grounding)["ok"]
    assert validate_report_text(hitter["published_report"], grounding)["unsupported_numbers"] == []
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["source_policy"]["external_rankings_used_for_report"] is False
    assert payload["source_policy"]["feeds_live_rank"] is False
    assert payload["source_policy"]["feeds_live_value"] is False

    _, problems = validate_scouting_repository(_write_artifact(tmp_path, payload))
    assert problems == []


def test_scouting_repository_builds_mlb_report_without_statcast(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    _add_mlb_rows(snapshot_path)

    with patch("scouting.repository.StatcastStore", return_value=_FakeStatcastStore()):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
            max_dynasty_rank=50,
        )

    pitcher = next(report for report in payload["reports"] if report["name"] == "Established Arm")
    pitcher_row = _row_by_name(snapshot_path, "Established Arm")
    grounding = repository._llm_grounding(
        pitcher_row,
        {},
        None,
        statcast_groups=[],
    )

    assert pitcher["player_type"] == "mlb"
    assert pitcher["statcast_groups"] == []
    assert pitcher["report"] == (
        "With no current percentile card, the read leans on the projection. "
        "The arm profiles for 2.88 ERA, 1.00 WHIP, 224 K, 13 W, 18 QS over 183.7 IP."
    )
    assert "Statcast" not in pitcher["report"]
    assert validate_report_text(pitcher["report"], grounding)["ok"]


def test_llm_grounding_uses_card_display_line_for_thin_current_best_single():
    current = {
        "pa": 71,
        "avg": 0.333,
        "obp": 0.420,
        "slg": 0.757,
        "ops": 1.177,
        "iso": 0.424,
        "k_pct": 28.2,
        "bb_pct": 10.0,
    }
    best = {
        "level": "AA",
        "sample": 150,
        "sample_unit": "PA",
        "avg": 0.300,
        "obp": 0.390,
        "slg": 0.596,
        "ops": 0.986,
        "iso": 0.296,
        "k_pct": 18.0,
        "bb_pct": 14.0,
    }
    combined = {
        "role": "hitter",
        "season": 2026,
        "level": "AAA",
        "levels": ["AAA", "AA"],
        "level_label": "AAA+AA",
        "sample": 221,
        "sample_unit": "PA",
        "pa": 221,
        "avg": 0.310,
        "obp": 0.400,
        "slg": 0.560,
        "ops": 0.960,
        "iso": 0.250,
        "babip": 0.330,
        "k_pct": 20.0,
        "bb_pct": 12.0,
    }
    row = SimpleNamespace(
        is_prospect=True,
        name="Sean Keys",
        role="hitter",
        bats=None,
        throws=None,
        positions=["1B"],
        team="DET",
        level="AAA",
        age=24,
        prospect_rank=42,
        stat_line=current,
        stat_line_translated={
            "role": "hitter",
            "level": "AAA",
            "sample": 71,
            "sample_unit": "PA",
            "stats": [
                {"key": "iso", "label": "ISO", "milb": 0.424, "mlb": 0.290},
                {"key": "k_pct", "label": "K%", "milb": 28.2, "mlb": 29.0},
            ],
        },
        best_single_level_stat_line=best,
        combined_season_stat_line=combined,
        context={},
        metadata={},
        availability_context={},
        has_peak_projection=False,
        peak_projection_summary=None,
    )

    grounding = repository._llm_grounding(row, {"iso": 91}, "vs test pool")
    serialized = json.dumps(grounding, sort_keys=True)

    assert grounding["card_display_line"]["iso"] == 0.250
    assert grounding["card_display_line"]["usage"] == "the line shown on the card skill bars"
    assert grounding["card_display_line"]["source_kind"] == "combined_season_line"
    assert grounding["sample_context"]["source_kind"] == "combined_season_line"
    assert "current_minor_league_line" not in grounding
    assert "best_single_level_line" not in grounding
    assert "0.424" not in serialized
    assert "0.296" not in serialized
    assert grounding["mlb_equivalent_translation"]["stats"][0]["mlb"] == 0.290
    assert "milb" not in grounding["mlb_equivalent_translation"]["stats"][0]


def test_llm_grounding_rounds_card_line_rate_stats():
    # Seth Hernandez regression: the card_line the read narrates is the combined
    # season line, and its raw rate stats carry false precision (14.597 K/9). The
    # grounding must round them before handoff so a model read cannot echo the
    # spurious decimals: 1 dp for per-9/ERA/WHIP, whole number for percentages.
    combined = {
        "role": "pitcher",
        "season": 2026,
        "level": "AAA",
        "levels": ["AAA", "AA"],
        "level_label": "AAA+AA",
        "sample": 57.3,
        "sample_unit": "IP",
        "ip": 57.3,
        "era": 2.503,
        "whip": 1.004,
        "k_per_9": 14.597,
        "bb_per_9": 2.531,
        "k_bb_pct": 30.4,
    }
    current = {
        "ip": 29.3,
        "era": 2.10,
        "whip": 0.95,
        "k_per_9": 16.111,
        "bb_per_9": 2.1,
        "k_bb_pct": 35.0,
    }
    row = SimpleNamespace(
        is_prospect=True,
        name="Seth Hernandez",
        role="pitcher",
        bats=None,
        throws=None,
        positions=["SP"],
        team="LAD",
        level="A+",
        age=19,
        prospect_rank=5,
        stat_line=current,
        stat_line_translated=None,
        best_single_level_stat_line=None,
        combined_season_stat_line=combined,
        context={},
        metadata={},
        availability_context={},
        has_peak_projection=False,
        peak_projection_summary=None,
    )

    grounding = repository._llm_grounding(row, {"k_per_9": 95}, "vs test pool")
    serialized = json.dumps(grounding)
    display = grounding["card_display_line"]

    # Read narrates the SAME combined line the bars use, with rounded rates.
    assert display["source_kind"] == "combined_season_line"
    assert display["k_per_9"] == 14.6
    assert display["bb_per_9"] == 2.5
    assert display["era"] == 2.5
    assert display["whip"] == 1.0
    assert display["k_bb_pct"] == 30
    assert "14.597" not in serialized
    assert "16.111" not in serialized  # never the thin current-slice line


def test_scouting_repository_publishes_valid_llm_reports(tmp_path, monkeypatch):
    from scouting import report_generator, repository

    class _FakeMessages:
        def create(self, **_kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text="A model-written read with the same ValuCast facts.",
                    )
                ]
            )

    class _FakeClient:
        messages = _FakeMessages()

    snapshot_path = _write_snapshot(tmp_path)
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    with patch.object(report_generator, "default_client", return_value=_FakeClient()), patch.object(
        repository, "LLM_CACHE_PATH", Path(tmp_path) / "llm_cache.json"
    ):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
        )

    assert payload["source_policy"]["llm_generated"] is True
    assert payload["source_policy"]["llm_generated_for_report_text_only"] is True
    assert payload["source_policy"]["feeds_live_rank"] is False
    assert payload["source_policy"]["feeds_live_value"] is False
    assert payload["summary"]["llm_published_report_count"] == 2
    assert payload["reports"][0]["published_report"] == (
        "A model-written read with the same ValuCast facts."
    )
    assert payload["reports"][0]["published_report_source"] == "llm"


def test_scouting_repository_publishes_valid_llm_rows_with_row_level_fallback(
    tmp_path, monkeypatch
):
    from scouting import report_generator, repository

    class _FakeMessages:
        def __init__(self):
            self._responses = [
                "A direct scouting read on Model Strong, a left-handed AA bat.",
                "A right-hander with a direct pitching read.",
                "A right-hander with a direct pitching read.",
                "A right-hander with a direct pitching read.",
            ]

        def create(self, **_kwargs):
            text = self._responses.pop(0)
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text=text,
                    )
                ]
            )

    class _FakeClient:
        def __init__(self):
            self.messages = _FakeMessages()

    snapshot_path = _write_snapshot(tmp_path)
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    with patch.object(report_generator, "default_client", return_value=_FakeClient()), patch.object(
        repository, "LLM_CACHE_PATH", Path(tmp_path) / "llm_cache.json"
    ):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
        )

    pitcher = next(report for report in payload["reports"] if report["name"] == "Starter Arm")
    assert pitcher["throws"] == "L"
    assert pitcher["report_llm"]["valid"] is False
    assert pitcher["report_llm"]["hard_ok"] is False
    assert pitcher["report_llm"]["handedness_problems"]
    assert payload["summary"]["llm_published_report_count"] == 1
    assert payload["summary"]["deterministic_published_report_count"] == 1
    assert {report["published_report_source"] for report in payload["reports"]} == {
        "deterministic",
        "llm",
    }
    hitter = next(report for report in payload["reports"] if report["name"] == "Model Strong")
    assert hitter["published_report_source"] == "llm"
    assert hitter["published_report"] == "A direct scouting read on Model Strong, a left-handed AA bat."
    assert pitcher["published_report_source"] == "deterministic"
    assert "right-hander" not in pitcher["published_report"]


def test_scouting_repository_caps_uncached_llm_generation(tmp_path, monkeypatch):
    from scouting import report_generator, repository

    class _FakeMessages:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text="A model-written read with the same ValuCast facts.",
                    )
                ]
            )

    class _FakeClient:
        def __init__(self):
            self.messages = _FakeMessages()

    snapshot_path = _write_snapshot(tmp_path)
    client = _FakeClient()
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM_MAX_GENERATE", "1")
    with patch.object(report_generator, "default_client", return_value=client), patch.object(
        repository, "LLM_CACHE_PATH", Path(tmp_path) / "llm_cache.json"
    ):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
        )

    assert client.messages.calls == 1
    assert payload["summary"]["llm_shadow"]["generated"] == 1
    assert payload["summary"]["llm_shadow"]["skipped_due_to_budget"] == 1
    assert payload["summary"]["llm_published_report_count"] == 1
    assert payload["summary"]["deterministic_published_report_count"] == 1


def test_scouting_repository_counts_api_failures_against_budget(tmp_path, monkeypatch):
    """A run of API errors must stop at generation_limit calls, not retry every
    eligible row — errored attempts consume budget the same as successful ones."""
    from scouting import report_generator, repository

    class _FailingMessages:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            raise RuntimeError("simulated API failure")

    class _FakeClient:
        def __init__(self):
            self.messages = _FailingMessages()

    snapshot_path = _write_snapshot(tmp_path)
    client = _FakeClient()
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM_MAX_GENERATE", "1")
    with patch.object(report_generator, "default_client", return_value=client), patch.object(
        repository, "LLM_CACHE_PATH", Path(tmp_path) / "llm_cache.json"
    ):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
        )

    # Only ONE call attempted (the budget), not one per eligible row.
    assert client.messages.calls == 1
    assert payload["summary"]["llm_shadow"]["errored"] == 1
    assert payload["summary"]["llm_shadow"]["generated"] == 0
    assert payload["summary"]["llm_shadow"]["skipped_due_to_budget"] == 1


def test_scouting_repository_reuses_cached_llm_when_generation_budget_is_zero(
    tmp_path, monkeypatch
):
    from scouting import report_generator, repository

    class _FailMessages:
        def create(self, **_kwargs):
            raise AssertionError("generation budget should prevent API calls")

    class _FakeClient:
        messages = _FailMessages()

    snapshot_path = _write_snapshot(tmp_path)
    cache_path = Path(tmp_path) / "llm_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "artifact": "valucast_scouting_llm_cache",
                "entries": {
                    "1_hitter": {
                        "hash": "same",
                        "text": "A cached LLM read on Model Strong, a left-handed AA bat.",
                        "model": "test",
                        "prompt": report_generator.PROMPT_FINGERPRINT,
                        "valid": True,
                        "hard_ok": True,
                        "problems": {"ok": True, "hard_ok": True},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM_MAX_GENERATE", "0")
    with (
        patch.object(report_generator, "default_client", return_value=_FakeClient()),
        patch.object(report_generator, "grounding_hash", return_value="same"),
        patch.object(report_generator, "DEFAULT_MODEL", "test"),
        patch.object(repository, "LLM_CACHE_PATH", cache_path),
    ):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
        )

    assert payload["summary"]["llm_shadow"]["generated"] == 0
    assert payload["summary"]["llm_shadow"]["reused"] == 1
    assert payload["summary"]["llm_shadow"]["skipped_due_to_budget"] == 1
    hitter = next(report for report in payload["reports"] if report["name"] == "Model Strong")
    pitcher = next(report for report in payload["reports"] if report["name"] == "Starter Arm")
    assert hitter["published_report_source"] == "llm"
    assert pitcher["published_report_source"] == "deterministic"


def test_scouting_repository_reuses_stale_cache_only_when_it_still_validates(
    tmp_path, monkeypatch
):
    from scouting import report_generator, repository

    class _FailMessages:
        def create(self, **_kwargs):
            raise AssertionError("generation budget should prevent API calls")

    class _FakeClient:
        messages = _FailMessages()

    snapshot_path = _write_snapshot(tmp_path)
    cache_path = Path(tmp_path) / "llm_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "artifact": "valucast_scouting_llm_cache",
                "entries": {
                    "1_hitter": {
                        "hash": "old",
                        "text": (
                            "A left-handed AA hitter running a .976 OPS "
                            "over 224 PA."
                        ),
                        "model": "test",
                        "prompt": report_generator.PROMPT_FINGERPRINT,
                        "valid": True,
                        "hard_ok": True,
                        "problems": {"ok": True, "hard_ok": True},
                    },
                    "2_pitcher": {
                        "hash": "old",
                        "text": (
                            "A left-handed pitcher with a made-up "
                            "99.9 K/9."
                        ),
                        "model": "test",
                        "prompt": report_generator.PROMPT_FINGERPRINT,
                        "valid": True,
                        "hard_ok": True,
                        "problems": {"ok": True, "hard_ok": True},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM_MAX_GENERATE", "0")
    with (
        patch.object(report_generator, "default_client", return_value=_FakeClient()),
        patch.object(report_generator, "grounding_hash", return_value="new"),
        patch.object(report_generator, "DEFAULT_MODEL", "test"),
        patch.object(repository, "LLM_CACHE_PATH", cache_path),
    ):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
        )

    assert payload["summary"]["llm_shadow"]["generated"] == 0
    assert payload["summary"]["llm_shadow"]["reused"] == 0
    assert payload["summary"]["llm_shadow"]["reused_stale"] == 1
    assert payload["summary"]["llm_shadow"]["skipped_due_to_budget"] == 1
    hitter = next(report for report in payload["reports"] if report["name"] == "Model Strong")
    pitcher = next(report for report in payload["reports"] if report["name"] == "Starter Arm")
    assert hitter["published_report_source"] == "llm"
    assert pitcher["published_report_source"] == "deterministic"


def test_scouting_repository_rejects_stale_reuse_when_sample_size_changed(tmp_path, monkeypatch):
    """7/1: a real production bug -- Nolan Perry's report was reused after his sample
    grew from a single-level line into a combined multi-level line. None of the old
    text's numbers looked "unsupported" (they still individually appear in the new
    grounding's per-level breakdown), so the guard let it through even though the
    text now silently describes an outdated, narrower slice of the season as the
    whole thing. This must force a regen (or fallback) instead of reusing."""
    from scouting import report_generator, repository

    class _FailMessages:
        def create(self, **_kwargs):
            raise AssertionError("generation budget should prevent API calls")

    class _FakeClient:
        messages = _FailMessages()

    snapshot_path = _write_snapshot(tmp_path)
    cache_path = Path(tmp_path) / "llm_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "artifact": "valucast_scouting_llm_cache",
                "entries": {
                    "1_hitter": {
                        "hash": "old",
                        "text": (
                            # Current combined_season_stat_line.sample is 224 PA --
                            # this stale text describes an earlier, smaller sample.
                            "A left-handed AA hitter running a .976 OPS "
                            "over 142 PA."
                        ),
                        "model": "test",
                        "prompt": report_generator.PROMPT_FINGERPRINT,
                        "valid": True,
                        "hard_ok": True,
                        "problems": {"ok": True, "hard_ok": True},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM_MAX_GENERATE", "0")
    with (
        patch.object(report_generator, "default_client", return_value=_FakeClient()),
        patch.object(report_generator, "grounding_hash", return_value="new"),
        patch.object(report_generator, "DEFAULT_MODEL", "test"),
        patch.object(repository, "LLM_CACHE_PATH", cache_path),
    ):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
        )

    # Starter Arm has no cache entry at all, so it also skips on the zero budget --
    # what matters here is Model Strong specifically didn't reuse the stale text.
    assert payload["summary"]["llm_shadow"]["reused_stale"] == 0
    assert payload["summary"]["llm_shadow"]["skipped_due_to_budget"] == 2
    hitter = next(report for report in payload["reports"] if report["name"] == "Model Strong")
    assert hitter["published_report_source"] == "deterministic"


def test_scouting_repository_publish_rechecks_stale_llm_handedness():
    from scouting import repository

    report = {
        "name": "Starter Arm",
        "role": "pitcher",
        "throws": "L",
        "report": "The deterministic lefty-safe report.",
        "report_llm": {
            "text": "Starter Arm is a right-hander with a direct pitching read.",
            "valid": True,
            "hard_ok": True,
            "model": "test",
        },
    }

    repository._publish_report_fields([report])

    assert report["published_report_source"] == "deterministic"
    assert report["published_report"] == "The deterministic lefty-safe report."


def test_scouting_repository_validator_blocks_robotic_copy(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )
    payload["reports"][0]["report"] = "This display-only artifact is useful."
    artifact_path = tmp_path / "reports.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_scouting_repository(artifact_path)

    assert any("display-only" in problem for problem in problems)


def test_scouting_repository_validator_allows_guarded_row_level_fallback(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )
    llm_text = "Model Strong is a left-handed AA bat with a guarded LLM read."
    payload["reports"][0]["report_llm"] = {
        "text": llm_text,
        "valid": True,
        "hard_ok": True,
        "model": "test",
    }
    payload["reports"][0]["published_report_source"] = "llm"
    payload["reports"][0]["published_report"] = llm_text
    artifact_path = tmp_path / "reports.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_scouting_repository(artifact_path)

    assert problems == []


def test_scouting_repository_validator_blocks_llm_source_without_valid_guard(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )
    for report in payload["reports"]:
        report["published_report_source"] = "llm"
        report["published_report"] = "LLM report text."
        report["report_llm"] = {
            "text": "LLM report text.",
            "valid": True,
            "hard_ok": True,
            "model": "test",
        }
    payload["reports"][0]["report_llm"]["valid"] = False
    artifact_path = tmp_path / "reports.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_scouting_repository(artifact_path)

    assert any("published as llm without valid report_llm" in problem for problem in problems)


def test_scouting_repository_validator_checks_reports_beyond_old_top_300(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )
    base_report = payload["reports"][0]
    payload["reports"] = []
    for index in range(301):
        report = json.loads(json.dumps(base_report))
        report.update(
            {
                "mlbam_id": 1000 + index,
                "name": f"Report {index + 1}",
                "prospect_rank": index + 1,
            }
        )
        payload["reports"].append(report)
    payload["reports"][-1]["published_report_source"] = "llm"
    payload["reports"][-1]["published_report"] = "Bad unguarded LLM text."
    payload["reports"][-1]["report_llm"] = {
        "text": "Bad unguarded LLM text.",
        "valid": False,
        "hard_ok": False,
        "model": "test",
    }
    payload["summary"]["report_count"] = len(payload["reports"])
    payload["validation"]["report_count"] = len(payload["reports"])
    artifact_path = tmp_path / "reports.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_scouting_repository(artifact_path)

    assert any("report 301 published as llm without valid report_llm" in problem for problem in problems)


def test_scouting_repository_validator_blocks_wrong_pitcher_handedness(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )
    payload["reports"][1]["published_report"] = (
        "Starter Arm is a right-hander with a direct pitching read."
    )
    artifact_path = tmp_path / "reports.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_scouting_repository(artifact_path)

    assert any("handedness" in problem for problem in problems)


def test_scouting_repository_prompt_change_busts_llm_cache(tmp_path, monkeypatch):
    """A cache entry written under an older VOICE_PROMPT (missing or mismatched
    fingerprint) must not be reused even when grounding hash and model still match."""
    from scouting import report_generator, repository

    class _FailMessages:
        def create(self, **_kwargs):
            raise AssertionError("generation budget should prevent API calls")

    class _FakeClient:
        messages = _FailMessages()

    snapshot_path = _write_snapshot(tmp_path)
    cache_path = Path(tmp_path) / "llm_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "artifact": "valucast_scouting_llm_cache",
                "entries": {
                    "1_hitter": {
                        "hash": "same",
                        "text": "A cached LLM read on Model Strong, a left-handed AA bat.",
                        "model": "test",
                        "prompt": "stale-prompt-fingerprint",
                        "valid": True,
                        "hard_ok": True,
                        "problems": {"ok": True, "hard_ok": True},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM_MAX_GENERATE", "0")
    with (
        patch.object(report_generator, "default_client", return_value=_FakeClient()),
        patch.object(report_generator, "grounding_hash", return_value="same"),
        patch.object(report_generator, "DEFAULT_MODEL", "test"),
        patch.object(repository, "LLM_CACHE_PATH", cache_path),
    ):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
        )

    assert payload["summary"]["llm_shadow"]["reused"] == 0
    assert payload["summary"]["llm_shadow"]["reused_stale"] == 0
    assert payload["summary"]["llm_shadow"]["skipped_due_to_budget"] == 2
    hitter = next(report for report in payload["reports"] if report["name"] == "Model Strong")
    assert hitter["published_report_source"] == "deterministic"
