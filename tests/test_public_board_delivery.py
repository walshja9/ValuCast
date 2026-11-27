"""User-facing coverage, freshness, and unavailable-state regressions."""
import csv
import io
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from werkzeug.datastructures import MultiDict

import app as site


def test_full_combined_export_has_every_unique_asset_and_provenance():
    response = site.app.test_client().get('/export?mode=prospects')
    rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
    expected = {str(r.mlbam_id) for r in site.dd_store.get_all() if r.is_prospect}
    assert len(expected) > 200
    assert len(rows) == len(expected)
    assert {r['MLBAM ID'] for r in rows} == expected
    assert {r['Role'] for r in rows} == {'hitter', 'pitcher'}
    assert [int(r['Board Rank']) for r in rows] == list(range(1, len(rows) + 1))
    assert {r['As Of'] for r in rows} == {site.dd_store.generated_at}
    gate = site.dd_store.surface_readiness.get('prospects')
    expected_status = {True: 'qualified', False: 'preliminary'}.get(gate, 'unknown')
    assert {r['Publication Status'] for r in rows} == {expected_status}
    if gate is False:
        assert all(r['Publication Note'] for r in rows)
    assert 'valucast-prospect-rankings.csv' in response.headers['Content-Disposition']


def test_all_prospects_are_accessible_in_web_board_and_limit_survives_htmx():
    client = site.app.test_client()
    default = client.get('/?mode=prospects').get_data(as_text=True)
    assert 'Show all prospects' in default
    full = client.get('/rankings?mode=prospects&limit=all', headers={'HX-Request': 'true'})
    expected = {str(r.mlbam_id) for r in site.dd_store.get_all() if r.is_prospect}
    assert full.get_data(as_text=True).count('class="compare-cb"') == len(expected)
    assert 'limit=all' in full.headers['HX-Replace-Url']


def test_old_snapshot_shows_date_and_age_instead_of_today_claim():
    old = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()
    with patch.object(type(site.dd_store), 'generated_at', new_callable=property, fget=lambda _: old):
        response = site.app.test_client().get('/?mode=prospects')
        html = response.get_data(as_text=True)
        assert '21 days old' in html
        assert old[:10] in html
        assert "today's refresh hasn't published yet" not in html
        assert 'Latest on ValuCast' in html


def test_health_distinguishes_missing_surface_and_stale_data():
    client = site.app.test_client()
    old = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()
    with patch.object(type(site.public_snapshot_store), 'generated_at', new_callable=property, fget=lambda _: old):
        body = client.get('/health/ready').get_json()
        assert body['public_snapshot']['generated_at'] == old
        assert body['public_snapshot']['fresh'] is False
        assert body['public_snapshot']['surface_readiness'] == site.public_snapshot_store.surface_readiness
    with patch.object(site, 'dd_store', site._UNAVAILABLE_DYNASTY_STORE):
        assert client.get('/health/ready').status_code == 503


def test_unavailable_board_never_substitutes_redraft_rows():
    with patch.object(site, 'dd_store', site._UNAVAILABLE_DYNASTY_STORE):
        client = site.app.test_client()
        for mode in ('prospects', 'dd_dynasty'):
            for route in ('/', '/rankings'):
                response = client.get(f'{route}?mode={mode}', headers={'HX-Request': 'true'})
                assert response.status_code == 503
                assert b'Showing default rankings' not in response.data
                assert b'rankings-table' not in response.data


def test_future_timestamp_is_not_fresh():
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert site._artifact_is_fresh(future) is False


def test_league_order_is_applied_before_display_limit():
    all_rows = site._prospect_rows(limit=None)
    target = all_rows[200]
    ranks = {site._prospect_adapter_key(row): {'adapter_rank': index + 2}
             for index, row in enumerate(all_rows)}
    ranks[site._prospect_adapter_key(target)] = {'adapter_rank': 1}
    scored = {'ranks': ranks, 'role_status': {role: {'status': 'ok'} for role in ('hitter', 'pitcher')}}
    args = MultiDict([('mode', 'prospects'), ('rank_by', 'league'), ('cats', 'HR')])
    with patch.object(site, '_custom_prospect_ranks', return_value=scored):
        ctx = site._build_dynasty_context(args)
        site._apply_prospect_board_context(ctx, args)
        response = site.app.test_client().get('/export?mode=prospects&rank_by=league&cats=HR')
    exported = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
    assert ctx['dd_rows'][0].id == target.id
    assert [str(row.mlbam_id) for row in ctx['dd_rows']] == [row['MLBAM ID'] for row in exported[:200]]
