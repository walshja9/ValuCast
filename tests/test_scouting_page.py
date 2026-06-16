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
    assert "not public scouting grades" in html


def test_footer_links_to_scouting_repository_from_main_page():
    client = app.test_client()

    response = client.get("/")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'href="/scouting">Scouting Repository</a>' in html
