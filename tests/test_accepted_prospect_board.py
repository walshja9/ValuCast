"""Synthetic public export contracts; never real model or serving acceptance."""
import csv
import hashlib
import io
import json
from types import SimpleNamespace

import pytest


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def write_board(tmp_path, rows=None, mutate=None, metadata_bytes=None):
    if rows is None:
        rows = [
            [1, 10, "Héctor <Ace>", "hitter", 3.0, 9.0, "high"],
            [2, 20, "Pitcher", "pitcher", 2, 8, "moderate"],
            [3, 30, "'O'Brien", "two_way", 2, 8, "low"],
        ]
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows([
        ["Rank", "MLBAM ID", "Player", "Role", "Y12 Surplus", "Y24 Surplus", "Evidence Confidence"],
        *rows,
    ])
    body = stream.getvalue().encode("utf-8-sig")
    metadata = {
        "schema": "valucast_prospect_v2_6_6_board_export_v1", "model_version": "v2.6.6",
        "decision_date": "2026-08-26T12:00:00Z", "terminal_commit": "a" * 40,
        "registration_sha256": "b" * 64, "accepted_reproduction_binding_sha256": "c" * 64,
        "production_predictions_sha256": "d" * 64, "public_snapshot_sha256": "e" * 64,
        "csv_sha256": hashlib.sha256(body).hexdigest(), "byte_count": len(body), "row_count": len(rows),
        "role_counts": {role: sum(row[3] == role for row in rows) for role in ("hitter", "pitcher", "two_way")},
    }
    if mutate:
        mutate(metadata)
    raw = metadata_bytes if metadata_bytes is not None else canonical(metadata)
    (tmp_path / "board_metadata.json").write_bytes(raw)
    (tmp_path / "ValuCast_Combined_Prospect_Board_v2.6.6.csv").write_bytes(body)
    return hashlib.sha256(raw).hexdigest(), body


def test_load_preserves_exact_csv_values_names_and_immutable_rows(tmp_path):
    from web.accepted_prospect_board import load_board
    pin, body = write_board(tmp_path)
    board = load_board(tmp_path, pin)
    assert board.csv_bytes == body
    assert [row.mlbam_id for row in board.rows] == [10, 20, 30]
    assert board.rows[0].name == "Héctor <Ace>"
    assert board.rows[2].name == "'O'Brien"
    assert board.rows[0].y12_text == "3.0"
    assert board.rows[0].id == "v266-10"
    with pytest.raises((AttributeError, TypeError)):
        board.rows[0].rank = 99
    with pytest.raises(TypeError):
        board.metadata["row_count"] = 4


@pytest.mark.parametrize("mutation", [
    lambda m: m.update(row_count=4), lambda m: m.update(byte_count=True),
    lambda m: m.update(role_counts={"hitter": 3, "pitcher": 0, "two_way": 0}),
    lambda m: m.update(role_counts={"hitter": True, "pitcher": 1, "two_way": 1}),
    lambda m: m.update(decision_date="2026-09-07T12:00:00Z"),
    lambda m: m.update(model_version="v1"), lambda m: m.update(terminal_commit="a" * 64),
    lambda m: m.update(accepted_reproduction_binding_sha256="unknown"),
    lambda m: m.update(extra="unregistered"),
])
def test_rejects_coherently_pinned_invalid_metadata(tmp_path, mutation):
    from web.accepted_prospect_board import BoardError, load_board
    pin, _ = write_board(tmp_path, mutate=mutation)
    with pytest.raises(BoardError):
        load_board(tmp_path, pin)


@pytest.mark.parametrize("rows", [
    [[1, 10, "A", "hitter", 1, 2, "high"], [2, 10, "B", "pitcher", 0, 1, "high"]],
    [[2, 10, "A", "hitter", 1, 2, "high"]],
    [[1, 0, "A", "hitter", 1, 2, "high"]],
    [[1, "01", "A", "hitter", 1, 2, "high"]],
    [[1, 10, " ", "hitter", 1, 2, "high"]],
    [[1, 10, "A", "starter", 1, 2, "high"]],
    [[1, 10, "A", "hitter", 1, 2, "certain"]],
    [[1, 10, "A", "hitter", "NaN", 2, "high"]],
    [[1, 10, "A", "hitter", 1, "1e999", "high"]],
    [[1, 20, "B", "pitcher", 1, 2, "high"], [2, 10, "A", "hitter", 1, 2, "high"]],
    [[1, 10, "A", "hitter", 1, 2, "high"], [2, 20, "B", "pitcher", 2, 3, "high"]],
    [[1, 10, "A", "hitter", 1, 2, "high", "extra"]],
    [],
])
def test_rejects_coherently_pinned_invalid_csv_rows(tmp_path, rows):
    from web.accepted_prospect_board import BoardError, load_board
    pin, _ = write_board(tmp_path, rows)
    with pytest.raises(BoardError):
        load_board(tmp_path, pin)


def test_rejects_wrong_external_pin_and_tampered_csv(tmp_path):
    from web.accepted_prospect_board import BoardError, load_board
    pin, body = write_board(tmp_path)
    with pytest.raises(BoardError):
        load_board(tmp_path, "0" * 64)
    (tmp_path / "ValuCast_Combined_Prospect_Board_v2.6.6.csv").write_bytes(body.replace(b"Pitcher", b"Changed"))
    with pytest.raises(BoardError):
        load_board(tmp_path, pin)


@pytest.mark.parametrize("raw", [b'{"schema":"a","schema":"b"}', b'{"row_count":NaN}', b'{}\n'])
def test_rejects_duplicate_key_nonfinite_and_noncanonical_json(tmp_path, raw):
    from web.accepted_prospect_board import BoardError, load_board
    pin, _ = write_board(tmp_path, metadata_bytes=raw)
    with pytest.raises(BoardError):
        load_board(tmp_path, pin)


@pytest.mark.parametrize("env", [{}, {"VALUCAST_PROSPECT_BOARD_DIR": ""},
    {"VALUCAST_PROSPECT_BOARD_DIR": "/missing"}, {"VALUCAST_PROSPECT_BOARD_METADATA_SHA256": "a" * 64}])
def test_selection_only_defaults_when_both_settings_absent(env):
    from web.accepted_prospect_board import select_board
    selected = select_board(env)
    assert selected.selected is bool(env)
    assert selected.board is None
    assert bool(selected.error) is bool(env)


@pytest.fixture
def accepted_site(tmp_path, monkeypatch):
    import app as site
    from web.accepted_prospect_board import select_board
    rows = [[1, 10, "Héctor <Ace>", "hitter", 3.12567, 9.45678, "high"],
            [2, 20, "Pitcher", "pitcher", 2.23456, 8.34567, "moderate"],
            [3, 30, "'O'Brien", "two_way", 2.23456, 8.34567, "low"]]
    rows += [[rank, rank * 10, f"Synthetic {rank}", "hitter", 1.234 + rank / 1000000,
              7 - rank / 1000, "low"] for rank in range(4, 206)]
    pin, body = write_board(tmp_path, rows)
    selection = select_board({"VALUCAST_PROSPECT_BOARD_DIR": str(tmp_path),
                              "VALUCAST_PROSPECT_BOARD_METADATA_SHA256": pin})
    assert selection.board is not None
    monkeypatch.setattr(site, "accepted_prospect_board", selection)

    def guard_accepted_routes(original):
        def guarded(*args, **kwargs):
            if site.request.endpoint in {'index', 'rankings', 'player_detail', 'compare', 'export_csv'}:
                raise AssertionError("Selected accepted board entered legacy scoring/ranking")
            return original(*args, **kwargs)
        return guarded

    for name in ("_build_dynasty_context", "_apply_prospect_board_context", "_build_context",
                 "_build_dynasty_player_detail_context", "_prospect_rows"):
        monkeypatch.setattr(site, name, guard_accepted_routes(getattr(site, name)))
    return site, site.app.test_client(), body


def test_selected_full_board_has_no_cap_or_legacy_values(accepted_site):
    _, client, _ = accepted_site
    response = client.get('/?mode=prospects')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.count('data-board-rank=') == 205
    assert 'Héctor &lt;Ace&gt;' in html
    assert '2026-08-26' in html and '12:00 UTC' in html
    assert 'Download full accepted board' in html
    assert 'hx-history="false"' in html and 'method="get"' in html
    assert 'name="role"' in html and 'type="submit"' in html
    assert 'Dynasty values blend' not in html and 'Data: Dynasty model' not in html
    assert 'today’s' not in html and 'today\'s' not in html
    assert 'Show all prospects' not in html and 'ValuCast Top 200' not in html
    assert 'committed daily' not in html and 'publicly scored' not in html
    assert html.index('<summary>Compare prospects</summary>') < html.index('id="rankings-container"')


def test_selected_filters_preserve_rank_holes_two_way_and_search_history(accepted_site):
    _, client, _ = accepted_site
    headers = {'HX-Request': 'true'}
    pitcher = client.get('/rankings?mode=prospects&role=pitcher', headers=headers)
    assert pitcher.status_code == 200
    assert pitcher.data.count(b'data-board-rank=') == 2
    assert b'data-board-rank="2"' in pitcher.data and b'data-board-rank="3"' in pitcher.data
    assert 'role=pitcher' in pitcher.headers['HX-Replace-Url']
    hitter = client.get('/rankings?mode=prospects&role=hitter', headers=headers)
    assert hitter.data.count(b'data-board-rank=') == 204
    assert client.get('/rankings?mode=prospects&role=two_way', headers=headers).data.count(b'data-board-rank=') == 1
    search = client.get('/rankings?mode=prospects&search=hector', headers=headers)
    assert search.data.count(b'data-board-rank=') == 1
    assert 'search=hector' in search.headers['HX-Replace-Url']
    assert client.get('/?mode=prospects&role=starter').status_code == 400
    direct = client.get('/rankings?mode=prospects&role=pitcher', headers={'Accept': 'text/html'})
    assert direct.status_code in (301, 302) and 'role=pitcher' in direct.headers['Location']


@pytest.mark.parametrize('headers', [{}, {'HX-Request': 'true'}])
def test_selected_detail_and_compare_use_exact_identity_values(accepted_site, headers):
    _, client, _ = accepted_site
    detail = client.get('/player/v266-10?mode=prospects', headers=headers)
    assert detail.status_code == 200
    assert b'H\xc3\xa9ctor &lt;Ace&gt;' in detail.data
    assert b'3.13' in detail.data and b'9.46' in detail.data and b'high' in detail.data
    assert b'2026-08-26' in detail.data
    compare = client.get('/compare?mode=prospects&p1=v266-10&p2=v266-30', headers=headers)
    assert compare.status_code == 200
    assert b'3.13' in compare.data and b'two-way' in compare.data
    assert client.get('/player/10?mode=prospects', headers=headers).status_code == 404
    assert client.get('/compare?mode=prospects&p1=v266-10&p2=30', headers=headers).status_code == 404


def test_selected_download_is_exact_full_in_memory_artifact(accepted_site, tmp_path):
    _, client, body = accepted_site
    (tmp_path / 'ValuCast_Combined_Prospect_Board_v2.6.6.csv').write_bytes(b'changed after startup')
    response = client.get('/export?mode=prospects&search=hector&role=pitcher&limit=200')
    assert response.status_code == 200 and response.data == body
    assert 'ValuCast_Combined_Prospect_Board_v2.6.6.csv' in response.headers['Content-Disposition']


@pytest.mark.parametrize('route', ['/prospects/share-card', '/prospects/share-card.png',
    '/prospects/share-card.svg', '/prospects/graphic', '/prospects/player-card/v266-10',
    '/prospects/player-card/v266-10.png', '/share/prospects/SS.png'])
def test_selected_legacy_graphics_are_explicitly_unavailable(accepted_site, route):
    _, client, _ = accepted_site
    response = client.get(route)
    assert response.status_code == 503 and b'/?mode=prospects' in response.data


def test_selected_health_uses_own_identity_and_availability(accepted_site):
    _, client, _ = accepted_site
    body = client.get('/health/ready').get_json()
    assert body['prospect_board']['source'] == 'v2.6.6'
    assert body['prospect_board']['available'] is True
    assert body['prospect_board']['decision_date'] == '2026-08-26T12:00:00Z'
    assert body['prospect_board']['row_count'] == 205


def test_invalid_selected_board_never_falls_back_and_blocks_health(accepted_site, monkeypatch):
    site, client, _ = accepted_site
    from web.accepted_prospect_board import BoardSelection
    monkeypatch.setattr(site, 'accepted_prospect_board', BoardSelection(True, error='synthetic bad pin'))
    for route in ('/', '/rankings', '/player/v266-10', '/compare', '/export'):
        response = client.get(route + '?mode=prospects', headers={'HX-Request': 'true'})
        assert response.status_code == 503
        assert b'accepted prospect board is unavailable' in response.data
        assert b'synthetic bad pin' not in response.data
    response = client.get('/health/ready')
    assert response.status_code == 503 and response.json['prospect_board']['available'] is False


def test_absent_selection_preserves_existing_public_board(monkeypatch):
    import app as site
    from web.accepted_prospect_board import BoardSelection
    monkeypatch.setattr(site, 'accepted_prospect_board', BoardSelection(False))
    response = site.app.test_client().get('/?mode=prospects')
    assert response.status_code == 200 and b'Show all prospects' in response.data


@pytest.mark.parametrize('url', ['/trade?mode=prospects', '/map?mode=prospects', '/farms?mode=prospects'])
def test_unrelated_endpoints_do_not_borrow_accepted_provenance(accepted_site, url):
    site, _, _ = accepted_site
    with site.app.test_request_context(url):
        context = site._accepted_prospect_provenance()
        assert context['accepted_prospect_view'] is False


def test_legacy_detail_joins_only_known_snapshot_mlbam_and_explains_uncovered(accepted_site, monkeypatch):
    site, client, _ = accepted_site
    records = {
        'old-hitter-id': SimpleNamespace(mlbam_id=10, is_prospect=True),
        'old-pitcher-id': SimpleNamespace(mlbam_id=20, is_prospect=True),
        'new-entrant': SimpleNamespace(mlbam_id=99999, is_prospect=True),
        'unrelated-redraft': SimpleNamespace(mlbam_id=10, is_prospect=False),
    }
    monkeypatch.setattr(site.dd_store, 'get_by_id', records.get)
    for headers in ({}, {'HX-Request': 'true'}):
        matched = client.get('/player/old-hitter-id?mode=prospects', headers=headers)
        assert matched.status_code == 200 and b'H\xc3\xa9ctor' in matched.data
        assert b'3.13' in matched.data and b'9.46' in matched.data
        compared = client.get('/compare?mode=prospects&p1=old-hitter-id&p2=old-pitcher-id', headers=headers)
        assert compared.status_code == 200 and b'Pitcher' in compared.data
        for identity in ('new-entrant', 'unrelated-redraft', 'made-up-id', '10'):
            absent = client.get(f'/player/{identity}?mode=prospects', headers=headers)
            assert absent.status_code == 404 and b'not covered by the accepted 2026-08-26 forecast' in absent.data
            assert b'/?mode=prospects' in absent.data
            assert absent.headers['X-ValuCast-Forecast-Coverage'] == 'uncovered'


def test_shared_generated_links_use_explicit_mlbam_identity(accepted_site, monkeypatch):
    site, _, _ = accepted_site
    legacy = SimpleNamespace(id='old-hitter-id', mlbam_id=10, name='Wrong display name', is_prospect=True)
    monkeypatch.setattr(site.dd_store, 'get_by_id', lambda identity: legacy if identity == legacy.id else None)
    with site.app.test_request_context('/'):
        assert site._team_board_player_url(legacy) == '/player/v266-10?mode=prospects'
        assert site._prospect_player_url('historical-role-id', mlbam_id=20) == '/player/v266-20?mode=prospects'
        assert site._prospect_player_url('not-an-id', name='Héctor') != '/player/v266-10?mode=prospects'


def test_help_and_precision_are_shared_without_changing_csv(accepted_site):
    _, client, body = accepted_site
    board = client.get('/?mode=prospects').data
    detail = client.get('/player/v266-10?mode=prospects').data
    for page in (board, detail):
        assert b'3.13' in page and b'9.46' in page and b'3.12567' not in page
        assert b'first 12 months' in page and b'first 24 months' in page
        assert b'standard 5' in page and b'replacement' in page
        assert b'not a probability' in page and b'current and prior' in page
    assert b'<details' in board and b'Metadata SHA-256' in board
    assert client.get('/export?mode=prospects').data == body


def test_retained_farm_backfields_sources_are_labeled_and_no_dead_graphic_controls(accepted_site):
    _, client, _ = accepted_site
    for url in ('/farms', '/backfields', '/backfields/team/BOS'):
        response = client.get(url)
        assert response.status_code == 200
        assert b'public-v1 snapshot' in response.data
        assert b'current ValuCast prospect board' not in response.data
        assert b'href="/prospects/share-card?' not in response.data
    # These source-specific graphics retain their old numbers, with explicit source labeling.
    farms = client.get('/farms').data
    assert b'public-v1' in farms and b'Top 20 value' in farms
