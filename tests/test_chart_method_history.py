"""Synthetic archive, row, and isolated app wiring tests for chart history."""

import ast
import json
from collections import Counter
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import build_public_dynasty_snapshot as snapshot
from web.public_snapshot_models import PublicSnapshotRow
from web.value_spark import build_spark, chart_value_history


FULL_HISTORY = (("2026-12-01", 80.0), ("2026-12-03", 60.0), ("2026-12-05", 70.0))
CHART_HISTORY = FULL_HISTORY[1:]


def _write_archive(directory, day, method_id, players):
    path = directory / f"{day}.json"
    path.write_text(
        json.dumps({"method_id": method_id, "players": players}),
        encoding="utf-8",
    )
    return path


def test_full_history_keeps_all_methods_and_chart_keeps_latest_compatible_run(tmp_path, monkeypatch):
    paths = [
        _write_archive(tmp_path, "2026-12-01", "a", [{"mlbam_id": 99, "value": 40}]),
        _write_archive(tmp_path, "2026-12-02", "b", [
            {"mlbam_id": 99, "value": 75},
            {"mlbam_id": 7, "value": 30},
        ]),
        _write_archive(tmp_path, "2026-12-03", "a", [
            {"mlbam_id": 99, "value": 50},
            {"mlbam_id": 99, "value": 20},
        ]),
    ]
    read_counts = Counter()
    load_json = snapshot._load_json

    def count_read(path):
        read_counts[path] += 1
        return load_json(path)

    monkeypatch.setattr(snapshot, "_load_json", count_read)

    full, chart, policy = snapshot._mlb_value_histories_from_archives(tmp_path, "a")

    assert read_counts == Counter(paths)
    assert full == {
        "99": [("2026-12-01", 40.0), ("2026-12-02", 75.0), ("2026-12-03", 63.0)],
        "7": [("2026-12-02", 30.0)],
    }
    assert chart == {"99": [("2026-12-03", 63.0)]}
    assert chart is not full
    assert chart["99"] is not full["99"]
    assert policy == {"dates": ["2026-12-01", "2026-12-02", "2026-12-03"], "latest_incompatible_date": "2026-12-02"}


def test_empty_mismatching_archive_clears_only_chart(tmp_path):
    _write_archive(tmp_path, "2026-12-01", "a", [{"mlbam_id": 99, "value": 40}])
    _write_archive(tmp_path, "2026-12-02", "b", [
        {"mlbam_id": 99, "value": "NaN"},
        {"value": 90},
    ])

    full, chart, policy = snapshot._mlb_value_histories_from_archives(tmp_path, "a")

    assert full == {"99": [("2026-12-01", 40.0)]}
    assert chart == {}
    assert policy["latest_incompatible_date"] == "2026-12-02"


def test_missing_current_method_id_keeps_independent_complete_histories(tmp_path):
    _write_archive(tmp_path, "2026-12-01", "a", [{"mlbam_id": 99, "value": 40}])
    _write_archive(tmp_path, "2026-12-02", "b", [{"mlbam_id": 99, "value": 75}])

    full, chart, policy = snapshot._mlb_value_histories_from_archives(tmp_path)

    assert full == chart == {"99": [("2026-12-01", 40.0), ("2026-12-02", 75.0)]}
    assert chart is not full
    assert chart["99"] is not full["99"]
    assert policy["latest_incompatible_date"] is None


@pytest.mark.parametrize("chart_has_today", [False, True])
def test_attaching_history_replaces_or_appends_todays_point_without_changing_value_or_rank(chart_has_today):
    past = [(f"2026-12-{day:02}", float(day)) for day in range(1, 31)]
    today = "2026-12-31"
    full = {"99": past + [(today, 15.0)]}
    chart_points = past[-2:] + ([(today, 15.0)] if chart_has_today else [])
    chart = {"99": chart_points.copy()}
    row = {"mlbam_id": 99, "value": 70.0, "rank": 4, "context": {"other": "kept"}}

    snapshot._attach_mlb_value_history([row], full, today)
    snapshot._attach_mlb_value_history([row], chart, today, context_key="chart_value_history")

    assert row == {
        "mlbam_id": 99,
        "value": 70.0,
        "rank": 4,
        "context": {
            "other": "kept",
            "value_history": past[1:] + [(today, 70.0)],
            "chart_value_history": past[-2:] + [(today, 70.0)],
        },
    }
    assert full["99"][-1] == (today, 15.0)
    assert chart["99"] == chart_points


def _row_from_snapshot(context):
    return PublicSnapshotRow.from_snapshot({
        "id": "example",
        "name": "Example Player",
        "player_type": "mlb",
        "rank": 4,
        "value": 70.0,
        "value_scale": "test",
        "value_source": "test",
        "updated_at": "2026-12-05",
        "context": context,
    })


def test_old_snapshot_and_stub_rows_fall_back_to_full_history():
    row = _row_from_snapshot({"value_history": FULL_HISTORY})
    assert row.chart_value_history == row.value_history == FULL_HISTORY
    assert chart_value_history(row) == FULL_HISTORY
    assert chart_value_history(SimpleNamespace(value_history=FULL_HISTORY)) == FULL_HISTORY
    assert chart_value_history(SimpleNamespace(value_history=FULL_HISTORY, chart_value_history=None)) == FULL_HISTORY


def test_explicit_empty_chart_history_never_uses_the_full_history():
    row = _row_from_snapshot({"value_history": FULL_HISTORY, "chart_value_history": []})
    assert chart_value_history(row) == ()
    assert chart_value_history(SimpleNamespace(value_history=FULL_HISTORY, chart_value_history=[])) == []


def test_chart_history_coerces_pairs_and_a_single_valid_point_produces_no_line():
    row = _row_from_snapshot({
        "value_history": FULL_HISTORY,
        "chart_value_history": [["2026-12-05", "70.0"], [None, 80], [], ["", 70], ["bad", "bad"]],
    })
    assert chart_value_history(row) == (("2026-12-05", 70.0),)
    assert build_spark(chart_value_history(row)) is None
    assert row.value_history == FULL_HISTORY


@pytest.fixture
def app_functions():
    """Parse exact definitions with no module, route, or image execution."""
    path = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _run_functions(*nodes, **namespace):
    code = ast.Module(body=list(nodes), type_ignores=[])
    exec(compile(code, "<isolated app function>", "exec"), namespace)
    return namespace


def _evaluate(node, **namespace):
    return eval(compile(ast.Expression(node), "<isolated app expression>", "eval"), namespace)


def _dict_value(function, key):
    return next(
        value for node in ast.walk(function) if isinstance(node, ast.Dict)
        for item, value in zip(node.keys, node.values)
        if isinstance(item, ast.Constant) and item.value == key
    )


def _call(function, name):
    return next(
        node for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    )


def test_watchlist_delta_uses_full_history_and_dynasty_png_chip_uses_chart_history(app_functions):
    functions = _run_functions(
        app_functions["_buy_spark_label"],
        app_functions["_value_momentum_label"],
        app_functions["_card_value_fields"],
        build_spark=build_spark,
        chart_value_history=chart_value_history,
        date=date,
        dd_store=SimpleNamespace(generated_at=None),
        _editorial_date=lambda _: None,
        _dynasty_confidence_lines=lambda _: [],
        _dynasty_value_preset_items=lambda _: [],
        _dynasty_card_read=lambda *_: "",
    )
    row = _row_from_snapshot({"value_history": FULL_HISTORY, "chart_value_history": CHART_HISTORY})
    movement = _dict_value(app_functions["_my_players_context"], "movement_label")

    assert _evaluate(movement, row=row, **functions) == "DOWN -10.0 OVER 4D"
    assert functions["_card_value_fields"]("dynasty", row, {})["momentum_label"] == "UP +10.0 OVER 2D"


def test_full_movement_suppresses_only_explicitly_noncomparable_history(app_functions):
    functions = _run_functions(
        app_functions["_buy_spark_label"], app_functions["_value_momentum_label"],
        build_spark=build_spark, chart_value_history=chart_value_history, date=date,
    )
    full = tuple((f"2026-12-{day:02}", float(day)) for day in range(1, 31))
    row = SimpleNamespace(value_history=full, chart_value_history=full[-3:],
                          context={"value_history_basis": {"movement_comparable": False}})
    assert functions["_value_momentum_label"](row) == "NOT COMPARABLE"
    assert functions["_value_momentum_label"](row, for_chart=True) == "UP +2.0 OVER 2D"
    for context in (None, [], {"value_history_basis": None}, {"value_history_basis": {"movement_comparable": True}}):
        row.context = context
        assert functions["_value_momentum_label"](row) == "UP +29.0 OVER 29D"
    assert row.value_history == full


def test_detail_spark_uses_chart_history(app_functions):
    spark = _dict_value(app_functions["_build_dynasty_player_detail_context"], "spark")
    row = SimpleNamespace(value_history=FULL_HISTORY, chart_value_history=CHART_HISTORY)

    result = _evaluate(spark, dd_row=row, build_spark=build_spark, chart_value_history=chart_value_history)

    assert result["delta"] == 10.0
    assert result["first_date"] == "2026-12-03"


def test_player_png_header_uses_chart_series_in_dynasty_mode_and_full_series_in_redraft(app_functions):
    header_call = _call(app_functions["_player_value_card_png"], "_graphic_header")
    series = next(keyword.value for keyword in header_call.keywords if keyword.arg == "value_history")
    row = SimpleNamespace(value_history=FULL_HISTORY, chart_value_history=CHART_HISTORY)

    assert _evaluate(series, mode="dynasty", row=row, chart_value_history=chart_value_history) == CHART_HISTORY
    assert _evaluate(series, mode="redraft", row=row, chart_value_history=chart_value_history) == FULL_HISTORY

    header = app_functions["_graphic_header"]
    line_input = next(keyword.value for keyword in _call(header, "_graphic_brand_curve").keywords
                      if keyword.arg == "value_history")
    caption_input, = _call(header, "build_spark").args
    assert ast.unparse(line_input) == ast.unparse(caption_input) == "value_history"


def test_compact_dynasty_png_uses_chart_series_without_switching_other_boards(app_functions):
    dynasty_route = _call(app_functions["dynasty_share_card_png"], "_prospect_graphic_png")
    assert any(keyword.arg == "use_chart_history" and keyword.value.value is True
               for keyword in dynasty_route.keywords)
    for name in ("prospects_share_card_png", "redraft_share_card_png"):
        call = _call(app_functions[name], "_prospect_graphic_png")
        assert all(keyword.arg != "use_chart_history" for keyword in call.keywords)

    spark_points = next(node for node in app_functions["_prospect_graphic_png"].body
                        if isinstance(node, ast.FunctionDef) and node.name == "spark_points")
    row = SimpleNamespace(value_history=FULL_HISTORY, chart_value_history=CHART_HISTORY)
    for use_chart_history, expected in ((True, "up"), (False, "down")):
        isolated = _run_functions(
            spark_points,
            build_spark=build_spark,
            chart_value_history=chart_value_history,
            use_chart_history=use_chart_history,
        )
        assert isolated["spark_points"](row, 0, 0, 120, 30)[1] == expected
