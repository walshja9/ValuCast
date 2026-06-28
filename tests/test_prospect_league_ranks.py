import importlib
import importlib.util

import pytest


def _module():
    spec = importlib.util.find_spec("web.prospect_league_ranks")
    assert spec is not None
    return importlib.import_module("web.prospect_league_ranks")


def test_loader_returns_format_ranks_for_covered_prospect():
    ranks = _module().format_ranks_for("806956", "hitter")

    assert ranks == [
        {"label": "7x7", "rank": 1, "total": 1235, "total_label": "1,235"},
        {"label": "5x5", "rank": 1, "total": 1235, "total_label": "1,235"},
    ]


def test_loader_returns_empty_list_for_unknown_player():
    assert _module().format_ranks_for("999999999", "hitter") == []


def test_loader_skips_entries_lacking_adapter_rank():
    ranks = _module().format_ranks_for("671936", "pitcher")

    assert ranks == [
        {"label": "7x7", "rank": 229, "total": 1251, "total_label": "1,251"},
    ]


def _row_by_mlbam(app_module, mlbam_id):
    return next(
        (
            row for row in app_module.dd_store.get_all()
            if str(getattr(row, "mlbam_id", "")) == str(mlbam_id)
        ),
        None,
    )


def test_player_detail_renders_format_ranks_only_for_covered_prospects():
    _module()
    valucast_app = importlib.import_module("app")
    if not valucast_app.dd_store.is_available:
        pytest.skip("DD store not available")

    covered = _row_by_mlbam(valucast_app, "806956")
    uncovered = _row_by_mlbam(valucast_app, "809100")
    if covered is None or uncovered is None:
        pytest.skip("expected prospect rows not available")

    valucast_app.app.config["TESTING"] = True
    client = valucast_app.app.test_client()

    response = client.get(
        f"/player/{covered.id}?mode=prospects",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "format-ranks" in response.get_data(as_text=True)

    response = client.get(
        f"/player/{uncovered.id}?mode=prospects",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "format-ranks" not in response.get_data(as_text=True)
