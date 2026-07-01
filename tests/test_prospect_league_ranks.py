import importlib
import importlib.util

import pytest


def _module():
    spec = importlib.util.find_spec("web.prospect_league_ranks")
    assert spec is not None
    return importlib.import_module("web.prospect_league_ranks")


def test_loader_returns_format_ranks_for_covered_prospect():
    # ops_7x7 (split SV/HLD) ships in the committed adapters artifact as of 7/1;
    # dd_7x7 stays in the artifact but is deliberately no longer surfaced.
    ranks = _module().format_ranks_for("806956", "hitter")

    assert ranks == [
        {"label": "7x7 OPS", "rank": 2, "total": 1333, "total_label": "1,333"},
        {"label": "5x5", "rank": 2, "total": 1333, "total_label": "1,333"},
    ]


def test_loader_returns_empty_list_for_unknown_player():
    assert _module().format_ranks_for("999999999", "hitter") == []


def test_loader_skips_entries_lacking_adapter_rank():
    # Pitchers have no surfaced roto_5x5 rank (coverage refusal: no W), so only the
    # 7x7 OPS row resolves — the missing-preset entry is skipped, which is the point.
    ranks = _module().format_ranks_for("671936", "pitcher")

    assert ranks == [
        {"label": "7x7 OPS", "rank": 317, "total": 1464, "total_label": "1,464"},
    ]


def _row_by_mlbam(app_module, mlbam_id):
    return next(
        (
            row for row in app_module.dd_store.get_all()
            if str(getattr(row, "mlbam_id", "")) == str(mlbam_id)
        ),
        None,
    )


def test_player_detail_renders_format_ranks_for_covered_prospects():
    # As of the 7/1 adapters rebuild every board prospect resolves format ranks, so
    # the old uncovered-player negative case has no real fixture left — the loader's
    # empty-result path stays covered by test_loader_returns_empty_list_for_unknown_player
    # and the template guard is a plain {% if format_ranks %}.
    _module()
    valucast_app = importlib.import_module("app")
    if not valucast_app.dd_store.is_available:
        pytest.skip("DD store not available")

    covered = _row_by_mlbam(valucast_app, "806956")
    if covered is None:
        pytest.skip("expected prospect row not available")

    valucast_app.app.config["TESTING"] = True
    client = valucast_app.app.test_client()

    response = client.get(
        f"/player/{covered.id}?mode=prospects",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "format-ranks" in response.get_data(as_text=True)
