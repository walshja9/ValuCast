from app import app


def test_scouting_page_renders_repository_and_role_tracker():
    client = app.test_client()

    response = client.get("/scouting")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Scouting Repository" in html
    assert "What the model sees" in html
    assert "Playing-time / role tracker" in html
    assert "H+P projection track" in html
    assert "Peak V2 calibration" in html
    assert "not public scouting grades" in html
    assert "Open board" in html


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
    assert "Scouting Repository" in html
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


def test_footer_links_to_scouting_repository_from_main_page():
    client = app.test_client()

    response = client.get("/")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'href="/scouting">Scouting Repository</a>' in html
    assert 'href="/intelligence">Intelligence Hub</a>' in html


def test_intelligence_hub_renders_all_roadmap_lanes():
    client = app.test_client()

    response = client.get("/intelligence")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "ValuCast Intelligence Hub" in html
    assert "Launch Stability" in html
    assert "Scouting Report Repository" in html
    assert "Prospect Peak Projection V2" in html
    assert "Player Card V2 Visuals" in html
    assert "Playing-Time / Role Tracker" in html
    assert "MLB Projection Center" in html
    assert "League Tools" in html
    assert "quality governor" in html
    assert "custom league settings" in html


def test_primary_nav_links_to_intelligence_surfaces():
    client = app.test_client()

    response = client.get("/")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'href="/intelligence">Intelligence Hub</a>' in html
    assert 'href="/scouting">Scouting</a>' in html
    assert 'href="/methodology">Methodology</a>' in html
