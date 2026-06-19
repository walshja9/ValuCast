import re
from pathlib import Path

import app as app_module
from app import app


def _html(path):
    response = app.test_client().get(path)
    return response, response.data.decode("utf-8")


def test_backfields_route_returns_200():
    response, html = _html("/backfields")

    assert response.status_code == 200
    assert "Backfields" in html
    assert "Prospects, call-ups, risers, and minor-league signal in one place." in html


def test_backfields_nav_link_and_active_state():
    response, html = _html("/")
    assert response.status_code == 200
    assert 'href="/backfields">Backfields' in html

    response, html = _html("/backfields")
    assert response.status_code == 200
    assert re.search(r'<a href="/backfields"\s+aria-current="page">Backfields</a>', html)


def test_backfields_section_anchors_present():
    response, html = _html("/backfields")

    assert response.status_code == 200
    for anchor in ("rankings", "ahead-of-the-curve", "call-up-desk", "stats"):
        assert f'id="{anchor}"' in html


def test_backfields_warm_css_is_scoped():
    css = Path("static/style.css").read_text(encoding="utf-8")

    assert ".backfields-page" in css
    assert "--bf-amber: #C8923F" in css

    for line in css.splitlines():
        if "#C8923F" in line:
            assert ".backfields-page" in line


def test_backfields_visual_contract_uses_semantic_signals():
    css = Path("static/style.css").read_text(encoding="utf-8")

    assert ".backfields-page .bf-value { color: var(--bf-signal)" in css
    assert ".backfields-page .bf-move-up { color: var(--bf-signal)" in css
    assert ".backfields-page .bf-move-down { color: var(--bf-clay)" in css
    assert ".backfields-page .bf-level" in css
    assert "color: var(--bf-amber)" in css


def test_backfields_degrades_when_artifacts_are_missing(monkeypatch):
    monkeypatch.setattr(app_module, "_load_artifact", lambda _path: None)

    response, html = _html("/backfields")

    assert response.status_code == 200
    assert "No reports yet - first looks land here." in html
