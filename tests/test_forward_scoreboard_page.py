"""Tests for the public /scoreboard page + share card (plan 030 S4, Lane B).

The page is additive and hold-gated: held (default) -> 404; unheld with the frozen
scoreboard artifact -> 200 rendering every number from the artifact; missing artifact
-> honest 'collecting' state. The CI-band verdict logic ('leading, not yet
significant' when the bootstrap CI straddles zero) is exercised on both sides of zero.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import app as app_module  # noqa: E402
from app import app  # noqa: E402

_FIXTURE = Path(__file__).parent / "fixtures" / "forward_scoreboard.json"
_RENDER_BLUEPRINT = Path(__file__).parent.parent / "render.yaml"


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_render_blueprint_releases_forward_scoreboard():
    blueprint = _RENDER_BLUEPRINT.read_text(encoding="utf-8")
    assert '- key: SCOREBOARD_HOLD\n        value: "0"' in blueprint


def _serve(monkeypatch, artifact_path):
    """Unhold the surface and point the loader at `artifact_path` (or a missing path
    for the collecting-state test). Clears the artifact cache so a prior path's cache
    entry can't leak across tests."""
    monkeypatch.setattr(app_module, "SCOREBOARD_HOLD", False)
    monkeypatch.setattr(app_module, "_FORWARD_SCOREBOARD_PATH", Path(artifact_path))
    app_module._ARTIFACT_CACHE.clear()


# --- hold gate ------------------------------------------------------------------

def test_scoreboard_held_returns_404(client, monkeypatch):
    monkeypatch.setattr(app_module, "SCOREBOARD_HOLD", True)
    assert client.get("/scoreboard").status_code == 404


def test_scoreboard_share_card_png_held_returns_404(client, monkeypatch):
    monkeypatch.setattr(app_module, "SCOREBOARD_HOLD", True)
    assert client.get("/scoreboard/share-card.png").status_code == 404


def test_scoreboard_share_card_preview_held_returns_404(client, monkeypatch):
    monkeypatch.setattr(app_module, "SCOREBOARD_HOLD", True)
    assert client.get("/scoreboard/share-card").status_code == 404


def test_env_flag_held_default_and_off_values():
    """Default (unset) = HELD; only explicit off values serve."""
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.delenv("SCOREBOARD_TEST_FLAG", raising=False)
        assert app_module._env_flag_held("SCOREBOARD_TEST_FLAG") is True
        for off in ("0", "off", "false", "FALSE", "No"):
            monkeypatch.setenv("SCOREBOARD_TEST_FLAG", off)
            assert app_module._env_flag_held("SCOREBOARD_TEST_FLAG") is False
        for on in ("1", "true", "yes", ""):
            monkeypatch.setenv("SCOREBOARD_TEST_FLAG", on)
            assert app_module._env_flag_held("SCOREBOARD_TEST_FLAG") is True
    finally:
        monkeypatch.undo()


# --- unheld with the fixture artifact -------------------------------------------

def test_scoreboard_renders_artifact_numbers(client, monkeypatch):
    _serve(monkeypatch, _FIXTURE)
    resp = client.get("/scoreboard")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    # Anti-trophy-case checklist strings, all rendered from the artifact:
    assert "EARLY RESULTS: 2 DAYS AHEAD" in html
    assert "Across 59 settled calls" in html
    assert "too early to declare a win" in html
    assert "Moved our way" in html
    assert "Moved against us" in html
    assert "Calls we changed" in html
    assert "Still waiting" in html
    assert '<span class="sb-co-label">Anticipation Score</span>' in html
    # (7) registration date + protocol version in the hero
    assert "protocol 030-v1" in html
    assert "Registered 2026-07-16" in html
    # (1) amber provisional banner above the fold + earliest expiry window
    assert "sb-provisional" in html
    assert "2026-08-23" in html
    # (3) consensus baseline as a NAMED co-entrant strip with board count
    assert "Aggregate public consensus" in html
    assert "sb-co-entrant" in html
    assert "each player consensus requires at least 2 public boards" in html
    # (5) self-retraction rate companion stat (fixture: 44%)
    assert "44%" in html
    # (2) losses shown (fixture has 28 real losses) + (6) funnel counts visible
    assert '<span class="ledger-tile-n">28</span>' in html
    assert "237 claims registered" in html
    # (4) headline CI band always present, with the artifact's own CI numbers
    # (fixture: [-6, +13]); provisional fixture renders the provisional verdict.
    assert "95% CI" in html
    assert "[-6, +13]" in html
    assert "provisional" in html.lower()


@pytest.mark.parametrize(
    ("median_lead_days", "headline", "summary"),
    [
        (-2.0, "EARLY RESULTS: 2 DAYS BEHIND", "2 days after the public board"),
        (0.0, "EARLY RESULTS: EVEN WITH THE FIELD", "moved at about the same time"),
    ],
)
def test_scoreboard_headline_tracks_result_sign(
    client, monkeypatch, tmp_path, median_lead_days, headline, summary
):
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload["anticipation_score"]["median_lead_days"] = median_lead_days
    artifact = tmp_path / "forward_scoreboard.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    _serve(monkeypatch, artifact)

    html = client.get("/scoreboard").data.decode("utf-8")
    assert headline in html
    assert summary in html


def test_scoreboard_share_card_png_ok(client, monkeypatch):
    _serve(monkeypatch, _FIXTURE)
    resp = client.get("/scoreboard/share-card.png")
    assert resp.status_code == 200
    assert "image/png" in resp.content_type
    assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_scoreboard_view_labels_registered_cohort_count():
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload["cohorts"]["cohort_count"] = 1
    assert app_module._scoreboard_view(payload)["cohort_label"] == "1 registered cohort"

    payload["cohorts"]["cohort_count"] = 2
    assert app_module._scoreboard_view(payload)["cohort_label"] == "2 registered cohorts"


def test_scoreboard_share_card_keeps_full_provisional_ci_label(monkeypatch):
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    view = app_module._scoreboard_view(payload)
    original = app_module._graphic_fit_text
    rendered = {}

    def track_fit(draw, text, font, max_width):
        fitted = original(draw, text, font, max_width)
        if text == view["ci_label"]:
            rendered["ci_label"] = fitted
        return fitted

    monkeypatch.setattr(app_module, "_graphic_fit_text", track_fit)
    app_module._forward_scoreboard_share_card_png(view)

    assert rendered["ci_label"] == view["ci_label"]


def test_scoreboard_share_card_discloses_consensus_board_minimum(monkeypatch):
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    original = app_module._graphic_fit_text
    rendered = []

    def track_fit(draw, text, font, max_width):
        rendered.append(text)
        return original(draw, text, font, max_width)

    monkeypatch.setattr(app_module, "_graphic_fit_text", track_fit)
    app_module._forward_scoreboard_share_card_png(app_module._scoreboard_view(payload))

    assert any("at least 2 public boards" in text for text in rendered)


def test_scoreboard_share_card_preview_ok(client, monkeypatch):
    _serve(monkeypatch, _FIXTURE)
    resp = client.get("/scoreboard/share-card")
    assert resp.status_code == 200
    assert b"/scoreboard/share-card.png" in resp.data


# --- missing artifact -> honest collecting state --------------------------------

def test_scoreboard_missing_artifact_collecting_state(client, monkeypatch, tmp_path):
    _serve(monkeypatch, tmp_path / "does_not_exist.json")
    resp = client.get("/scoreboard")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Collecting" in html
    # No fabricated numbers in the collecting state.
    assert "<h1>EARLY RESULTS</h1>" in html
    assert "DAYS AHEAD" not in html
    assert "DAYS BEHIND" not in html
    assert "95% CI" not in html


def test_scoreboard_share_card_png_missing_artifact_404(client, monkeypatch, tmp_path):
    """Share PNG has no honest empty graphic — a missing artifact is a 404, not a
    zeroed card (mirrors /ledger/share-card.png)."""
    _serve(monkeypatch, tmp_path / "does_not_exist.json")
    assert client.get("/scoreboard/share-card.png").status_code == 404


# --- CI-band verdict logic on BOTH sides of zero (pure function) -----------------

def test_ci_label_straddles_zero_not_significant():
    label = app_module._scoreboard_ci_label(
        {"ci_low": -6.0, "ci_high": 13.0, "provisional": False}
    )
    assert label == "leading, not yet significant"


def test_ci_label_clear_of_zero_significant():
    label = app_module._scoreboard_ci_label(
        {"ci_low": 3.0, "ci_high": 13.0, "provisional": False}
    )
    assert label == "clear of zero"


def test_ci_label_mirrors_sign_test_when_artifact_carries_it():
    # Post-7/21 artifacts gate the verdict on the exact sign test; the page must
    # mirror it even when the bootstrap CI would have said "clear of zero".
    base = {
        "ci_low": 3.0,
        "ci_high": 13.0,
        "median_lead_days": 5.0,
        "provisional": False,
    }
    label = app_module._scoreboard_ci_label(
        {**base, "sign_test": {"p_value": 0.2, "direction": "leading", "significant": False}}
    )
    assert label == "leading, not yet significant"
    label = app_module._scoreboard_ci_label(
        {**base, "sign_test": {"p_value": 0.01, "direction": "leading", "significant": True}}
    )
    assert label == "significant - sign test clear of coin-flip"
    label = app_module._scoreboard_ci_label(
        {**base, "sign_test": {"p_value": 0.3, "direction": "behind", "significant": False}}
    )
    assert label == "behind, not yet significant"


def test_ci_label_reports_significant_behind_and_even_results_honestly():
    base = {"ci_low": -3.0, "ci_high": 3.0, "median_lead_days": -1.0, "provisional": False}

    assert app_module._scoreboard_ci_label({
        **base,
        "sign_test": {"p_value": 0.01, "direction": "behind", "significant": False},
    }) == "behind, significant"
    assert app_module._scoreboard_ci_label({
        **base,
        "median_lead_days": 0.0,
        "sign_test": {"p_value": 1.0, "direction": "even", "significant": False},
    }) == "even, not yet significant"


def test_ci_label_recomputes_significance_instead_of_trusting_the_flag():
    label = app_module._scoreboard_ci_label({
        "ci_low": -3.0,
        "ci_high": 3.0,
        "median_lead_days": 1.0,
        "provisional": False,
        "sign_test": {"p_value": 0.2, "direction": "leading", "significant": True},
    })

    assert label == "leading, not yet significant"


def test_ci_label_provisional_takes_precedence():
    # A band clear of zero is still reported provisional while the expiry window is
    # closed — the loss lane hasn't been able to fire yet.
    label = app_module._scoreboard_ci_label(
        {"ci_low": 3.0, "ci_high": 13.0, "provisional": True}
    )
    assert "provisional" in label


def test_ci_label_empty_pool_collecting():
    label = app_module._scoreboard_ci_label(
        {"ci_low": None, "ci_high": None, "provisional": True}
    )
    assert "collecting" in label
