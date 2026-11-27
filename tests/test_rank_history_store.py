"""Reader tests for the fail-soft prospect rank-history store."""
import json

from web.rank_history_store import RankHistoryStore


def _write_artifact(tmp_path, players, generated_at="2026-07-14T00:00:00+00:00"):
    payload = {
        "artifact": "valucast_prospect_rank_history",
        "schema_version": 1,
        "generated_at": generated_at,
        "players": players,
    }
    path = tmp_path / "rank_history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _player(series, best=None, best_date=None, latest=None, latest_date=None, name="P"):
    best_date = best_date or min(series, key=lambda dr: (dr[1], dr[0]))[0]
    best = best if best is not None else min(r for _, r in series)
    latest_date = latest_date or series[-1][0]
    latest = latest if latest is not None else series[-1][1]
    return {
        "name": name,
        "series": series,
        "best_rank": best,
        "best_rank_date": best_date,
        "latest_rank": latest,
        "latest_date": latest_date,
    }


def test_trend_caption_exact_form(tmp_path):
    path = _write_artifact(
        tmp_path,
        {"1": _player([["2026-06-18", 1], ["2026-07-14", 7]], name="Franklin Arias")},
    )
    trend = RankHistoryStore(path).trend_for(1)
    # Caption is exactly "Best #<best> (<Mon D>) - now #<latest>".
    assert trend["caption"] == "Best #1 (Jun 18) - now #7"
    assert trend["best_rank"] == 1 and trend["best_date"] == "Jun 18"
    assert trend["latest_rank"] == 7 and trend["latest_date"] == "Jul 14"


def test_axis_is_inverted_best_rank_at_top(tmp_path):
    # Rank 1 (best) must map to the SMALLEST y (top of the SVG); a worse rank maps
    # lower. This is the whole point of the surface -- a non-inverted axis would put
    # #1 at the bottom and misrepresent the receipt.
    path = _write_artifact(tmp_path, {"1": _player([["2026-06-18", 1], ["2026-06-19", 50]])})
    trend = RankHistoryStore(path).trend_for(1)
    coords = [tuple(map(float, pt.split(","))) for pt in trend["points"].split()]
    y_best, y_worst = coords[0][1], coords[1][1]
    assert y_best < y_worst  # rank 1 sits ABOVE rank 50


def test_x_spreads_across_width(tmp_path):
    path = _write_artifact(
        tmp_path, {"1": _player([["2026-06-18", 1], ["2026-06-19", 3], ["2026-06-20", 2]])}
    )
    trend = RankHistoryStore(path).trend_for(1)
    coords = [tuple(map(float, pt.split(","))) for pt in trend["points"].split()]
    xs = [x for x, _ in coords]
    assert xs[0] == 0.0
    assert xs[-1] == trend["view_w"]
    assert xs[0] < xs[1] < xs[2]  # ascending by index


def test_dot_sits_on_latest_point(tmp_path):
    path = _write_artifact(tmp_path, {"1": _player([["2026-06-18", 1], ["2026-06-19", 4]])})
    trend = RankHistoryStore(path).trend_for(1)
    coords = [tuple(map(float, pt.split(","))) for pt in trend["points"].split()]
    assert (trend["dot_x"], trend["dot_y"]) == (round(coords[-1][0], 1), round(coords[-1][1], 1))


def test_single_point_series_is_not_a_trend(tmp_path):
    path = _write_artifact(tmp_path, {"1": _player([["2026-06-18", 5]])})
    assert RankHistoryStore(path).trend_for(1) == {}


def test_unknown_player_returns_empty(tmp_path):
    path = _write_artifact(tmp_path, {"1": _player([["2026-06-18", 1], ["2026-06-19", 2]])})
    store = RankHistoryStore(path)
    assert store.trend_for(999) == {}
    assert store.trend_for(None) == {}
    assert store.trend_for("") == {}


def test_missing_artifact_is_fail_soft(tmp_path):
    store = RankHistoryStore(tmp_path / "nope.json")
    assert store.trend_for(1) == {}  # no exception


def test_malformed_artifact_is_fail_soft(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    assert RankHistoryStore(path).trend_for(1) == {}


def test_top_level_list_degrades_to_empty(tmp_path):
    path = tmp_path / "list.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert RankHistoryStore(path).trend_for(1) == {}


def test_key_is_str_mlbam(tmp_path):
    # int and str mlbam both resolve to the same str-keyed record.
    path = _write_artifact(tmp_path, {"808265": _player([["2026-06-18", 1], ["2026-06-19", 2]])})
    store = RankHistoryStore(path)
    assert store.trend_for(808265)["caption"] == store.trend_for("808265")["caption"]


def test_graphic_rank_trend_text_uses_store_caption():
    # The share graphic must carry the same dated receipt as the card page, from
    # the same store caption, so the two surfaces can never disagree.
    import app as app_module

    assert (
        app_module._graphic_rank_trend_text({"caption": "Best #1 (Jun 18) - now #7"})
        == "Best #1 (Jun 18) - now #7"
    )
    assert app_module._graphic_rank_trend_text({}) is None
    assert app_module._graphic_rank_trend_text(None) is None
    assert app_module._graphic_rank_trend_text({"caption": "   "}) is None


def test_prospect_player_card_png_renders_with_rank_trend_chip():
    # End-to-end: the PNG route exercises the new chip-drawing branch for a
    # player with rank history (Arias) without crashing the renderer.
    from app import app as flask_app

    r = flask_app.test_client().get("/prospects/player-card/vc_prospect_808265_hitter.png")
    assert r.status_code == 200
    assert r.data[:8] == b"\x89PNG\r\n\x1a\n"
