from app import app


def test_scouting_display_report_text_prefers_valid_llm_report():
    from app import _scouting_display_report_text

    report = {
        "report": "Deterministic fallback.",
        "report_llm": {
            "valid": True,
            "text": "A sharper Claude-written scouting read.",
        },
    }

    assert _scouting_display_report_text(report) == "A sharper Claude-written scouting read."


def test_scouting_display_report_text_falls_back_when_llm_invalid():
    from app import _scouting_display_report_text

    report = {
        "report": "Deterministic fallback.",
        "report_llm": {
            "valid": False,
            "text": "Do not publish this.",
        },
    }

    assert _scouting_display_report_text(report) == "Deterministic fallback."


def test_public_adapter_refreshes_stale_deterministic_prospect_shape_language():
    from app import _scouting_display_report_text

    report = {
        "player_type": "prospect",
        "published_report_source": "deterministic",
        "published_report": (
            "He consistently finishes at-bats with contact. "
            "Table-setter ceiling; the present floor is a light-hitting reserve."
        ),
        "report": (
            "He consistently finishes at-bats with contact. "
            "Table-setter ceiling; the present floor is a light-hitting reserve."
        ),
    }

    public = _scouting_display_report_text(report)

    assert "Contact-first table-setter shape" in public
    assert "ceiling" not in public.lower()
    assert "floor" not in public.lower()


def test_public_prospect_read_rejects_uncalibrated_peak_claims():
    from app import _scouting_display_report

    for published, fallback, expected in (
        (
            "Mid-rotation starter is the projection floor.",
            "This profiles as a mid-rotation starter.",
            "Current-performance ceiling scenario: mid-rotation starter.",
        ),
        (
            "The projection puts a 70% chance on a regular outcome.",
            "The likely outcome is an everyday run-producing bat.",
            "The current-performance ceiling scenario is an everyday run-producing bat.",
        ),
        (
            "If the bat softens, he is a low-risk bench option.",
            "Observed performance read.",
            "Observed performance read.",
        ),
    ):
        public = _scouting_display_report({
            "player_type": "prospect",
            "report": fallback,
            "published_report": published,
            "published_report_source": "llm",
            "report_llm": {"valid": True, "text": published},
        })

        assert public["display_report"] == expected
        assert public["display_report_source"] == "deterministic"


def test_public_prospect_read_fails_closed_when_fallback_is_still_uncalibrated():
    from app import _scouting_display_report_text

    assert _scouting_display_report_text({
        "player_type": "prospect",
        "report": "He has a 60% chance to become an everyday regular.",
    }) == ""


def test_public_mlb_read_keeps_supported_projection_language():
    from app import _scouting_display_report_text

    report = {
        "player_type": "mlb",
        "report": "Deterministic fallback.",
        "published_report": "The projection gives him a 12.5% walk rate.",
    }

    assert _scouting_display_report_text(report) == report["published_report"]


def test_scouting_route_uses_the_public_adapter_for_fallback_reports(monkeypatch):
    # The route must render deterministic-fallback prospect reports through the
    # public adapter (raw "profiles as" phrasing rewritten to ceiling-scenario
    # language). A synthetic report keeps this independent of which live players
    # happen to be on the fallback path after any given nightly refresh.
    import app as app_module

    real_load = app_module._load_artifact

    def fake_load(path):
        if str(path).endswith("valucast_scouting_reports.json"):
            return {
                "reports": [
                    {
                        "name": "Synthetic Fallback Pitcher",
                        "player_type": "prospect",
                        "team": "ZZZ",
                        "role": "pitcher",
                        "report": "This profiles as a mid-rotation starter.",
                    }
                ]
            }
        return real_load(path)

    monkeypatch.setattr(app_module, "_load_artifact", fake_load)
    client = app.test_client()

    response = client.get("/scouting?q=Synthetic%20Fallback%20Pitcher")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Current-performance ceiling scenario: mid-rotation starter" in html
    assert "This profiles as a mid-rotation starter" not in html
    assert "projection floor" not in html.lower()
    assert "with low risk" not in html.lower()
    assert 'class="scouting-peak"' not in html


def test_scouting_page_renders_repository_and_role_tracker():
    client = app.test_client()

    response = client.get("/scouting")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Scouting Reports" in html
    assert "What the reports say" in html
    assert "role profiles" in html
    assert "peak buckets" in html
    assert "recent movers" in html
    assert "Playing-time / role tracker" in html
    assert "MLB Projection Source" in html
    assert "Peak Projection Buckets" in html
    assert "not public scouting grades" in html
    assert "Open board" in html
    assert "Share graphic" in html


def test_scouting_page_filters_reports_by_query():
    client = app.test_client()

    response = client.get("/scouting?q=Franklin%20Arias")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Franklin Arias" in html
    assert "matching report" in html


def test_scouting_page_survives_mlb_reports_in_every_filter():
    # 7/3 review: MLB reports carry no dynasty_value key at all; the template's
    # `is not none` guard doesn't cover a MISSING key (Undefined is not none ==
    # True), so 30 of 31 team filters 500'd the whole page.
    client = app.test_client()

    for url in ("/scouting?team=ATL", "/scouting?team=LAD", "/scouting?q=Ohtani"):
        response = client.get(url)
        assert response.status_code == 200, url
        assert b"P#None" not in response.data, url


def test_prospect_player_detail_surfaces_scouting_and_role_context():
    client = app.test_client()

    response = client.get(
        "/player/vc_prospect_808265_hitter?mode=prospects",
        headers={"HX-Request": "true"},
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert '<span class="profile-card-kicker">Opportunity</span>' in html
    assert "<h4>Role, playing time &amp; availability</h4>" in html
    assert '<a href="/scouting?q=Franklin%20Arias" class="mini-link">Open report</a>' in html
    assert "Peak Outlook" not in html
    assert "<b>Ceiling scenario</b>" not in html
    assert "<b>Floor scenario</b>" not in html
    assert "Regular+" not in html


def test_mlb_player_detail_surfaces_role_tracker_context():
    client = app.test_client()

    response = client.get(
        "/player/vc_mlb_677951_hitter?mode=dd_dynasty",
        headers={"HX-Request": "true"},
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    # 7/14 declutter: the standalone "Playing-Time Tracker" card folded into the
    # Opportunity card; the tracker grid now renders under that hierarchy header
    # with a "Projected Role" stat label (matching the prospect path).
    assert '<span class="profile-card-kicker">Opportunity</span>' in html
    assert "<h4>Role, playing time &amp; availability</h4>" in html
    assert "Projected Role" in html
    # Wiring test: the tracker artifact regenerates daily, so read the expected
    # role from it instead of pinning a label that drifts with the data.
    import json
    from pathlib import Path as _Path
    tracker = json.loads(
        _Path("data/models/valucast_playing_time_role_tracker.json").read_text(encoding="utf-8")
    )
    profile = next(
        p for p in tracker["profiles"] if str(p.get("mlbam_id")) == "677951"
    )
    from app import _format_context_label
    assert _format_context_label(profile["projected_role"]) in html


def test_footer_links_to_scouting_reports_from_main_page():
    client = app.test_client()

    response = client.get("/")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'href="/scouting">Scouting Reports</a>' in html
    assert 'href="/intelligence">Intelligence Hub</a>' in html


def test_intelligence_hub_renders_all_roadmap_lanes():
    client = app.test_client()

    response = client.get("/intelligence")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "ValuCast Intelligence Hub" in html
    assert "Launch Stability" in html
    assert "Scouting Reports" in html
    assert "Prospect Peak Projection V2" in html
    assert "Player Card V2 Visuals" in html
    assert "Playing-Time / Role Tracker" in html
    assert "MLB Projection Track" in html
    assert "League Tools" in html
    assert "publish checks" in html
    assert "custom league settings" in html


def test_peak_public_status_is_display_only():
    client = app.test_client()

    intelligence = client.get("/intelligence").data.decode("utf-8")
    intelligence_peak = intelligence[intelligence.index("Prospect Peak Projection V2"):]
    intelligence_peak = intelligence_peak[:intelligence_peak.index("</article>")]
    assert "Display only" in intelligence_peak

    scouting = client.get("/scouting").data.decode("utf-8")
    scouting_peak = scouting[scouting.index("Peak Projection Buckets"):]
    scouting_peak = scouting_peak[:scouting_peak.index("</article>")]
    assert "Display only" in scouting_peak


def test_intelligence_hub_leads_with_user_facing_surfaces():
    client = app.test_client()

    response = client.get("/intelligence")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert html.index("Scouting Reports") < html.index("Launch Stability")
    assert html.index("Player Card V2 Visuals") < html.index("Launch Stability")
    assert html.index("Recent Signals") < html.index("Launch Stability")
    assert "MLB Projection Track" in html
    assert "H+P model track" not in html


def test_primary_nav_links_to_intelligence_surfaces():
    client = app.test_client()

    response = client.get("/")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    # Core surfaces stay in the primary nav. aria-current is wired for every
    # primary-nav entry (not just Backfields) — "/" is current on the homepage.
    assert 'href="/" aria-current="page">Board</a>' in html
    assert 'href="/backfields"' in html and ">Backfields</a>" in html
    assert 'href="/map">Map</a>' in html
    assert 'href="/methodology">Methodology</a>' in html
    # Intelligence Hub demoted out of the site-nav (7/14 declutter); the footer
    # still links it on every page.
    import re
    site_nav = re.search(r'<nav class="site-nav".*?</nav>', html, re.S).group(0)
    assert 'href="/intelligence"' not in site_nav
    assert 'href="/intelligence">Intelligence Hub</a>' in html
    # Intelligence surfaces promoted into the primary nav (hold flags default off).
    assert 'href="/movers">Movers</a>' in html
    assert 'href="/buys">Buys</a>' in html
    assert 'href="/receipts">Receipts</a>' in html
    assert 'href="/gaps">Gaps</a>' in html
    # Scouting is consolidated into Backfields; still no top-nav item.
    assert 'href="/scouting">Scouting</a>' not in html


def test_primary_nav_hold_flags_hide_buys_and_receipts(monkeypatch):
    # The nav guards must track the live hold constants: a held surface never
    # advertises itself in the primary nav.
    import app as app_module

    monkeypatch.setattr(app_module, "AHEAD_OF_THE_CURVE_HOLD", True)
    monkeypatch.setattr(app_module, "RECEIPTS_HOLD", True)
    html = app.test_client().get("/").data.decode("utf-8")
    assert 'href="/buys">Buys</a>' not in html
    assert 'href="/receipts">Receipts</a>' not in html
    # Unheld promoted items stay.
    assert 'href="/movers">Movers</a>' in html
    assert 'href="/gaps">Gaps</a>' in html


def _arias_card_html():
    return app.test_client().get(
        "/player/vc_prospect_808265_hitter?mode=prospects",
        headers={"HX-Request": "true"},
    )


def test_prospect_card_renders_vc_rank_trend_block():
    # Arias is #1 on 2026-06-18 in the committed rank-history artifact; the card must
    # surface the inverted-axis sparkline + a caption that names the #1 peak.
    response = _arias_card_html()
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "VC Rank Trend" in html
    assert "vc-rank-trend-spark" in html          # the SVG sparkline rendered
    assert "vc-rank-trend-line" in html           # the polyline path rendered
    assert "Best #1 (Jun 18)" in html             # caption anchors on the #1 peak
    assert "#1" in html


def test_prospect_card_survives_missing_rank_history_artifact(monkeypatch):
    # Missing/absent artifact -> the store degrades to empty, the block is hidden,
    # and the page still renders 200 (never 500).
    import app as app_module
    from web.rank_history_store import RankHistoryStore

    monkeypatch.setattr(
        app_module,
        "rank_history_store",
        RankHistoryStore(path="data/models/__does_not_exist__.json"),
    )
    response = _arias_card_html()
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "VC Rank Trend" not in html
    assert "vc-rank-trend-spark" not in html
