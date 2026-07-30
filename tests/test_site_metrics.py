"""First-party site-metrics tests: the narrow, owner-scoped analytics layer.

Scope is the contract (owner decision, 2026-07-30): pageviews by ROUTE
PATTERN, anonymous unique/returning visitors via the first-party vc_vid
cookie, referrer domain + UTM fields, X-visit classification, and the three
named click events — nothing else. NO raw IP, NO stored user agent, NO
fingerprinting; the public summary endpoint serves aggregates only. These
tests lock both what is collected and what is refused.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import app as app_module
from app import app
from web.site_metrics import SiteMetricsStore


# ---------------------------------------------------------------------------
# Store unit tests
# ---------------------------------------------------------------------------
def _store(tmp_path):
    return SiteMetricsStore(str(tmp_path / "metrics.sqlite3"))


def test_disabled_store_is_a_silent_noop(tmp_path):
    store = SiteMetricsStore(None)
    assert store.enabled is False
    store.record_pageview(route="/", vid="a" * 32, is_new_visitor=True)
    store.record_click(metric="share_card")
    assert store.summary(days=7) == {"enabled": False}
    assert list(tmp_path.iterdir()) == []   # nothing written anywhere


def test_pageviews_aggregate_by_route(tmp_path):
    store = _store(tmp_path)
    for _ in range(3):
        store.record_pageview(route="/", vid="a" * 32, is_new_visitor=False)
    store.record_pageview(route="/player/<player_id>", vid="a" * 32,
                          is_new_visitor=False)
    s = store.summary(days=7)
    assert s["enabled"] is True
    assert s["pageviews"]["total"] == 4
    by_route = {r["route"]: r["n"] for r in s["pageviews"]["by_route"]}
    assert by_route == {"/": 3, "/player/<player_id>": 1}


def test_unique_and_returning_visitors(tmp_path):
    store = _store(tmp_path)
    store.record_pageview(route="/", vid="a" * 32, is_new_visitor=True)
    store.record_pageview(route="/", vid="a" * 32, is_new_visitor=False)
    store.record_pageview(route="/", vid="b" * 32, is_new_visitor=True)
    s = store.summary(days=7)
    assert s["visitors"]["unique"] == 2
    # "Returning" = a visitor whose cookie predates the visit — only vid a.
    assert s["visitors"]["returning"] == 1


def test_referrer_utm_and_x_classification(tmp_path):
    store = _store(tmp_path)
    store.record_pageview(route="/", vid="a" * 32, is_new_visitor=True,
                          referrer_domain="t.co", utm_source="x",
                          utm_campaign="launch", from_x=True)
    store.record_pageview(route="/", vid="b" * 32, is_new_visitor=True,
                          referrer_domain="news.ycombinator.com")
    s = store.summary(days=7)
    referrers = {r["domain"]: r["n"] for r in s["referrers"]}
    assert referrers == {"t.co": 1, "news.ycombinator.com": 1}
    assert s["x_visits"] == 1
    campaigns = s["utm_campaigns"]
    assert campaigns == [{"source": "x", "campaign": "launch", "n": 1}]


def test_clicks_counted_by_metric(tmp_path):
    store = _store(tmp_path)
    store.record_click(metric="share_card", vid="a" * 32)
    store.record_click(metric="share_card")
    store.record_click(metric="trade_analyzer")
    store.record_click(metric="outbound", target_domain="fangraphs.com")
    s = store.summary(days=7)
    assert s["clicks"] == {"share_card": 2, "trade_analyzer": 1, "outbound": 1}


def test_summary_window_excludes_old_events(tmp_path):
    store = _store(tmp_path)
    store.record_pageview(route="/", vid="a" * 32, is_new_visitor=True,
                          ts="2020-01-01T00:00:00Z")
    store.record_pageview(route="/", vid="b" * 32, is_new_visitor=True)
    s = store.summary(days=7)
    assert s["pageviews"]["total"] == 1
    assert s["visitors"]["unique"] == 1


def test_schema_stores_no_ip_or_user_agent_and_summary_leaks_no_vid(tmp_path):
    store = _store(tmp_path)
    store.record_pageview(route="/", vid="a" * 32, is_new_visitor=True)
    import sqlite3
    with sqlite3.connect(store.db_path) as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(events)")}
    assert not columns & {"ip", "remote_addr", "user_agent", "fingerprint"}
    # The public summary must be aggregates only — no visitor id anywhere.
    assert "a" * 32 not in json.dumps(store.summary(days=7))


def test_prune_drops_only_expired_events(tmp_path):
    store = _store(tmp_path)
    store.record_pageview(route="/", vid="a" * 32, is_new_visitor=True,
                          ts="2020-01-01T00:00:00Z")
    store.record_pageview(route="/", vid="b" * 32, is_new_visitor=True)
    store.prune(keep_days=400)
    import sqlite3
    with sqlite3.connect(store.db_path) as con:
        remaining = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert remaining == 1


# ---------------------------------------------------------------------------
# App integration
# ---------------------------------------------------------------------------
@pytest.fixture
def metrics_client(tmp_path, monkeypatch):
    store = SiteMetricsStore(str(tmp_path / "metrics.sqlite3"))
    monkeypatch.setattr(app_module, "site_metrics", store)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, store


def test_html_pageview_sets_anonymous_cookie_and_records(metrics_client):
    client, store = metrics_client
    resp = client.get("/methodology")
    assert resp.status_code == 200
    cookie = next(
        (c for c in resp.headers.getlist("Set-Cookie") if c.startswith("vc_vid=")),
        None,
    )
    assert cookie is not None
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    s = store.summary(days=1)
    assert s["pageviews"]["total"] == 1
    assert s["visitors"]["unique"] == 1
    assert s["visitors"]["returning"] == 0


def test_second_visit_with_cookie_counts_returning(metrics_client):
    client, store = metrics_client
    client.get("/methodology")
    client.get("/methodology")   # test client persists the cookie jar
    s = store.summary(days=1)
    assert s["pageviews"]["total"] == 2
    assert s["visitors"]["unique"] == 1
    assert s["visitors"]["returning"] == 1


def test_pageview_stores_route_pattern_not_raw_path(metrics_client):
    client, store = metrics_client
    row = app_module.store.get_all()[0]
    resp = client.get(f"/player/{row.id}", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    routes = [r["route"] for r in store.summary(days=1)["pageviews"]["by_route"]]
    assert "/player/<player_id>" in routes
    assert all(str(row.id) not in r for r in routes)


def test_static_health_bots_and_404s_not_recorded(metrics_client):
    client, store = metrics_client
    client.get("/static/style.css")
    client.get("/health/ready")
    client.get("/methodology", headers={"User-Agent": "Examplebot/1.0 crawler"})
    client.get("/definitely-not-a-page-404")
    assert store.summary(days=1)["pageviews"]["total"] == 0


def test_x_visit_classified_from_referrer(metrics_client):
    client, store = metrics_client
    client.get("/methodology", headers={"Referer": "https://t.co/abc123"})
    s = store.summary(days=1)
    assert s["x_visits"] == 1
    assert {r["domain"] for r in s["referrers"]} == {"t.co"}


def test_utm_recorded_from_query(metrics_client):
    client, store = metrics_client
    client.get("/methodology?utm_source=x&utm_medium=social&utm_campaign=launch")
    s = store.summary(days=1)
    assert s["utm_campaigns"] == [{"source": "x", "campaign": "launch", "n": 1}]
    assert s["x_visits"] == 1   # utm_source=x classifies even without referrer


def test_click_event_endpoint_records_allowlisted_metric(metrics_client):
    client, store = metrics_client
    resp = client.post("/metrics/event", json={"metric": "share_card"})
    assert resp.status_code == 204
    resp = client.post(
        "/metrics/event", json={"metric": "outbound", "target": "fangraphs.com"}
    )
    assert resp.status_code == 204
    assert store.summary(days=1)["clicks"] == {"share_card": 1, "outbound": 1}


def test_click_event_endpoint_ignores_unknown_metric(metrics_client):
    client, store = metrics_client
    resp = client.post("/metrics/event", json={"metric": "evil_probe_xyz"})
    assert resp.status_code == 204   # no oracle for probing the allowlist
    assert store.summary(days=1)["clicks"] == {}


def test_summary_endpoint_serves_aggregates_only(metrics_client):
    client, store = metrics_client
    client.get("/methodology")
    resp = client.get("/metrics/summary?days=7")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["enabled"] is True
    assert data["pageviews"]["total"] == 1
    text = resp.get_data(as_text=True)
    # No 32-hex visitor id may appear anywhere in the public payload.
    import re
    assert not re.search(r"\b[0-9a-f]{32}\b", text)


def test_csp_and_security_headers_unchanged(metrics_client):
    client, _ = metrics_client
    resp = client.get("/methodology")
    assert resp.headers["Content-Security-Policy"] == app_module._CSP_POLICY
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_metrics_js_served_and_included_in_base(metrics_client):
    client, _ = metrics_client
    assert b"metrics.js" in client.get("/methodology").data
    resp = client.get("/static/metrics.js")
    assert resp.status_code == 200
    assert b"data-metric" in resp.data


def test_disabled_store_sets_no_cookie(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "site_metrics", SiteMetricsStore(None))
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/methodology")
        assert not any(
            c.startswith("vc_vid=") for c in resp.headers.getlist("Set-Cookie")
        )
        assert client.get("/metrics/summary").get_json() == {"enabled": False}
