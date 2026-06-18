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


def test_prospect_player_detail_surfaces_scouting_and_role_context():
    client = app.test_client()

    response = client.get(
        "/player/vc_prospect_808265_hitter?mode=prospects",
        headers={"HX-Request": "true"},
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Scouting Reports" in html
    assert "Role & Read" in html
    assert "Regular+" in html


def test_mlb_player_detail_surfaces_role_tracker_context():
    client = app.test_client()

    response = client.get(
        "/player/vc_mlb_677951_hitter?mode=dd_dynasty",
        headers={"HX-Request": "true"},
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Playing-Time Tracker" in html
    assert "Projected Role" in html
    assert "Everyday Regular" in html


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
    assert 'href="/intelligence">Intelligence Hub</a>' in html
    assert 'href="/buys">Buys</a>' in html
    assert 'href="/map">Map</a>' in html
    assert 'href="/scouting">Scouting</a>' in html
    assert 'href="/methodology">Methodology</a>' in html
