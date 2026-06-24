"""On-demand positional prospect share cards."""
import pytest

import app as app_module


@pytest.fixture
def client():
    return app_module.app.test_client()


@pytest.mark.skipif(not app_module.dd_store.is_available, reason="needs prospect feed")
@pytest.mark.parametrize("pos", ["c", "1b", "2b", "3b", "ss", "of", "p"])
def test_each_position_renders_png(client, pos):
    resp = client.get(f"/share/prospects/{pos}.png")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "image/png"
    assert len(resp.data) > 1000  # a real image, not an error page


def test_unknown_position_404s(client):
    assert client.get("/share/prospects/dh.png").status_code == 404


@pytest.mark.skipif(not app_module.dd_store.is_available, reason="needs prospect feed")
def test_limit_is_clamped_and_role_filtered():
    # n is clamped to <= 25, and pitcher pool only returns pitchers.
    rows = app_module._positional_prospect_rows("p", 25)
    assert 0 < len(rows) <= 25
    assert all(getattr(r, "role", None) == "pitcher" for r in rows)
    ss = app_module._positional_prospect_rows("ss", 20)
    assert all("SS" in (r.positions or ()) for r in ss)
