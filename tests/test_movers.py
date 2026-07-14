"""Tests for the ValuCast Prospect Movers board."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from prospects.movers import EPOCH_DATE

# Epoch-relative fixture dates: the movers board floors every window at the
# scoring epoch, so fixtures must live on/after it or they get clamped away.
# Deriving from EPOCH_DATE keeps these tests correct across future epoch bumps.
_EPOCH = date.fromisoformat(EPOCH_DATE)


def _d(offset):
    return (_EPOCH + timedelta(days=offset)).isoformat()


def test_clean_score_tail_stops_at_epoch_step():
    from prospects.movers import clean_score_tail

    tail = clean_score_tail(
        [
            ("2026-06-18", 40.0),
            ("2026-06-19", 41.0),
            ("2026-06-20", 42.0),
            ("2026-06-23", 60.0),
            ("2026-06-24", 61.0),
        ]
    )

    assert tail == [("2026-06-23", 60.0), ("2026-06-24", 61.0)]
    assert tail[-1][1] - tail[0][1] == 1.0


def test_clean_score_tail_keeps_clean_five_day_climb():
    from prospects.movers import clean_score_tail

    tail = clean_score_tail(
        [
            ("2026-06-24", 44.0),
            ("2026-06-25", 45.0),
            ("2026-06-26", 46.5),
            ("2026-06-27", 47.5),
            ("2026-06-28", 49.0),
            ("2026-06-29", 50.0),
        ]
    )

    assert tail[0] == ("2026-06-24", 44.0)
    assert tail[-1] == ("2026-06-29", 50.0)
    assert tail[-1][1] - tail[0][1] == 6.0


def test_build_movers_board_uses_rank_v1_score_and_native_policy():
    from prospects.movers import build_movers_board

    current = {
        "generated_at": f"{_d(9)}T12:00:00+00:00",
        "rank_version": "rank-v1-test",
        "board": [
            _rank_row(1, "Clean Riser", 10, 50.0),
            _rank_row(2, "Epoch Jump", 11, 61.0),
            _rank_row(3, "Clean Faller", 12, 42.0),
        ],
    }
    history = [
        {"date": _d(0), "board": [_rank_row(2, "Epoch Jump", 12, 42.0)]},
        {
            "date": _d(6),
            "board": [
                _rank_row(1, "Clean Riser", 18, 45.0),
                _rank_row(2, "Epoch Jump", 13, 60.0),
                _rank_row(3, "Clean Faller", 8, 48.0),
            ],
        },
    ]

    payload = build_movers_board(current, history_payloads=history)

    assert payload["source_policy"]["feeds_model_score"] is False
    assert payload["source_policy"]["feeds_public_rank"] is False
    assert payload["source_policy"]["feeds_buy_score"] is False
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["source_policy"]["dd_ranks_used"] is False
    assert [row["name"] for row in payload["rising"]] == ["Clean Riser"]
    assert [row["name"] for row in payload["cooling"]] == ["Clean Faller"]
    assert payload["rising"][0]["score_delta"] == 5.0
    assert payload["rising"][0]["rank_delta"] == 8
    assert payload["cooling"][0]["score_delta"] == -6.0
    assert payload["cooling"][0]["rank_delta"] == -4
    assert payload["summary"]["excluded_step_guard_count"] >= 1


def test_movers_wired_into_daily_public_build_and_publish_workflow():
    from scripts import run_daily_public_build
    from scripts import validate_public_data_freshness as freshness

    workflow = Path(".github/workflows/daily-public-data.yml").read_text(encoding="utf-8")
    build_steps = [" ".join(step) for step in run_daily_public_build.BUILD_STEPS]
    validate_steps = [" ".join(step) for step in run_daily_public_build.VALIDATE_STEPS]

    assert build_steps.index("scripts/build_valucast_movers.py") > build_steps.index(
        "scripts/build_prospect_rank_v1.py"
    )
    assert "scripts/validate_valucast_movers.py" in validate_steps
    assert "data/models/valucast_prospect_movers.json" in workflow
    assert "data/prediction_archive/valucast_prospect_movers" in workflow
    assert hasattr(freshness, "VALUCAST_MOVERS")


def test_movers_routes_render_html_and_png():
    import app as app_module

    client = app_module.app.test_client()

    response = client.get("/movers")
    assert response.status_code == 200
    assert b"PROSPECT MOVERS" in response.data
    assert b"/movers/share-card.png" in response.data
    assert b"movers-window-pills" in response.data

    png = client.get("/movers/share-card.png")
    assert png.status_code == 200
    assert png.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert "image/png" in png.content_type

    # Windowed export renders (and differs from the default when the boards
    # differ); junk windows fall back to the default graphic.
    windowed = client.get("/movers/share-card.png?window=7")
    assert windowed.status_code == 200
    assert windowed.data[:8] == b"\x89PNG\r\n\x1a\n"
    junk = client.get("/movers/share-card.png?window=999")
    assert junk.data == png.data

    preview = client.get("/movers/share-card?window=7")
    assert preview.status_code == 200
    assert b"share-card.png?window=7" in preview.data


def test_build_movers_board_window_variants_floor_the_start():
    from prospects.movers import build_movers_board

    # Early climb then a late slide, sampled every 2 days (inside the 3-day
    # gap guard). The full view nets out to -1.0, under the +/-2.0 threshold;
    # only the 7d window isolates the slide from the day-4 peak (_d(4)).
    current = {
        "generated_at": f"{_d(10)}T12:00:00+00:00",
        "board": [_rank_row(1, "Late Slider", 40, 50.0)],
    }
    history = [
        {"date": _d(0), "board": [_rank_row(1, "Late Slider", 30, 51.0)]},
        {"date": _d(2), "board": [_rank_row(1, "Late Slider", 27, 53.0)]},
        {"date": _d(4), "board": [_rank_row(1, "Late Slider", 25, 55.0)]},
        {"date": _d(6), "board": [_rank_row(1, "Late Slider", 28, 54.0)]},
        {"date": _d(8), "board": [_rank_row(1, "Late Slider", 33, 52.0)]},
    ]
    payload = build_movers_board(current, history_payloads=history)

    assert set(payload["windows"]) == {"7d", "14d", "21d", "30d"}
    # Full view: 51.0 -> 50.0 nets -1.0, under the threshold -> no mover.
    assert payload["rising"] == [] and payload["cooling"] == []
    seven = payload["windows"]["7d"]
    assert [row["name"] for row in seven["cooling"]] == ["Late Slider"]
    assert seven["cooling"][0]["score_delta"] == -5.0
    assert seven["cooling"][0]["window_days"] <= 7


def test_movers_window_param_serves_variant_and_falls_back(monkeypatch):
    import app as app_module

    client = app_module.app.test_client()

    fourteen_riser = {
        "id": "vc_mover_9_hitter", "player_id": "vc_prospect_9_hitter",
        "mlbam_id": 9, "name": "Fourteen Flag", "team": "BOS", "role": "hitter",
        "positions": ["SS"], "pos": "SS", "level": "AA", "age": 20, "eta": 2027,
        "current_rank": 5, "current_score": 55.0, "score_delta": 4.0,
        "rank_delta": 6, "window_days": 14,
        "movement_label": "UP +4.0 over 14d", "why": "AA 120 PA, .912 OPS",
        "history_tail": [
            {"date": "2026-06-20", "score": 51.0, "rank": 11},
            {"date": "2026-07-04", "score": 55.0, "rank": 5},
        ],
    }
    payload = {
        "generated_at": "2026-07-04T12:00:00+00:00",
        "summary": {}, "validation": {},
        "rising": [], "cooling": [],
        "windows": {
            "7d": {"rising": [], "cooling": []},
            "14d": {"rising": [fourteen_riser], "cooling": []},
        },
    }
    monkeypatch.setattr(app_module, "_load_movers_payload", lambda: payload)
    assert client.get("/movers?window=7").status_code == 200
    # No param serves the DEFAULT window (14d) — there is no "All" view.
    default = client.get("/movers")
    assert default.status_code == 200
    assert b"Fourteen Flag" in default.data
    # Unknown/junk windows fall back to the default window too.
    junk = client.get("/movers?window=999")
    assert junk.status_code == 200
    assert b"Fourteen Flag" in junk.data
    # A variant missing from an older artifact falls back to the top-level
    # board, never a 500.
    assert client.get("/movers?window=21").status_code == 200


def test_movers_empty_state_distinguishes_epoch_drought_from_genuine_sparse(monkeypatch):
    """Right after a re-baseline every prospect is history-limited, so an empty
    board is a countdown ("history refills"), NOT "nothing cleared the filters".
    A day where some prospects have history but none cleared the +/-2.0 filter is
    the genuine-sparse case and keeps the original copy."""
    import app as app_module

    client = app_module.app.test_client()

    # Drought: mover_count == 0 AND every ranked prospect is history-limited.
    drought = {
        "generated_at": f"{EPOCH_DATE}T00:00:00+00:00",
        "rising": [], "cooling": [],
        "summary": {"current_ranked_count": 2833},
        "validation": {"history_limited_count": 2833},
        "windows": {f"{w}d": {"rising": [], "cooling": []} for w in (7, 14, 21, 30)},
    }
    monkeypatch.setattr(app_module, "_load_movers_payload", lambda: drought)
    html = client.get("/movers").data.decode("utf-8")
    assert "Score history restarted July 14" in html
    assert "history refills" in html
    # The countdown quotes the served window and a build estimate (epoch == today
    # here, so the 14d default view needs ~14 more builds).
    assert "14d view needs about 14 more nightly builds" in html
    # Genuine-sparse copy must NOT appear when it's actually a drought.
    assert "no risers cleared" not in html
    assert "no fallers cleared" not in html

    # Genuine sparse: history exists (limited < ranked), still nothing qualified.
    sparse = {
        "generated_at": f"{EPOCH_DATE}T00:00:00+00:00",
        "rising": [], "cooling": [],
        "summary": {"current_ranked_count": 2833},
        "validation": {"history_limited_count": 40},
        "windows": {f"{w}d": {"rising": [], "cooling": []} for w in (7, 14, 21, 30)},
    }
    monkeypatch.setattr(app_module, "_load_movers_payload", lambda: sparse)
    html = client.get("/movers").data.decode("utf-8")
    assert "no risers cleared" in html
    assert "no fallers cleared" in html
    assert "Score history restarted" not in html


def _rank_row(mlbam_id, name, rank, score, role="hitter"):
    return {
        "mlbam_id": mlbam_id,
        "name": name,
        "role": role,
        "positions": ["SS"] if role == "hitter" else ["SP"],
        "mlb_team": "BOS",
        "age": 20,
        "eta": 2027,
        "level": "AA",
        "rank": rank,
        "score": score,
        "drivers": ["{'feature': 'ops_x_youth', 'contribution': 0.2}"],
        "context_only": {
            "breakout_label": "rising",
            "combined_season_stat_line": {
                "role": role,
                "level_label": "AA",
                "sample": 120,
                "sample_unit": "PA" if role == "hitter" else "IP",
                "ops": 0.912,
                "iso": 0.210,
                "k_pct": 18.0,
                "bb_pct": 12.0,
            },
        },
    }


def test_default_board_reaches_the_epoch_not_the_14d_momentum_cap():
    from prospects.movers import build_movers_board

    # 7/7 bug: the page's "All" view spanned 14 days while the 21d/30d presets
    # spanned 15 — the default board inherited the buys 14d momentum cap
    # instead of walking back to the scoring epoch, so "All" was the SHORTEST
    # window on the page. A slow 16-day climb (small daily steps, inside the
    # gap guard) must be measured in full on the default board.
    current = {
        "generated_at": f"{_d(16)}T12:00:00+00:00",
        "board": [_rank_row(1, "Slow Burner", 10, 56.0)],
    }
    history = [
        {"date": _d(offset), "board": [_rank_row(1, "Slow Burner", 20, s)]}
        for offset, s in [
            (0, 50.0), (2, 50.7), (4, 51.4),
            (6, 52.1), (8, 52.8), (10, 53.5),
            (12, 54.2), (14, 55.0),
        ]
    ]
    payload = build_movers_board(current, history_payloads=history)

    riser = payload["rising"][0]
    assert riser["window_days"] == 16  # _d(0) -> _d(16), past the old 14d cap
    assert riser["score_delta"] == 6.0
    # "All" must never span less than any windowed preset serves.
    for windowed in payload["windows"].values():
        for row in windowed["rising"]:
            assert riser["window_days"] >= row["window_days"]
