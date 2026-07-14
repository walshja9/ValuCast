"""Offline tests for the prospect current-org refresh (pure resolution logic).

Network fetch itself is not tested; these lock the resolution map, the
off-ladder (foreign/winter league) guard, and merge-preserves-prior behavior.
"""
from scripts.refresh_prospect_orgs import (
    build_team_org_map,
    merge_preserving_prior,
    resolve_orgs,
)


def _teams_payload():
    return {
        "teams": [
            {"id": 138, "abbreviation": "STL", "sport": {"id": 1}},
            {"id": 111, "abbreviation": "BOS", "sport": {"id": 1}},
            # AZ normalizes to house-style ARI via consensus_join_util
            {"id": 109, "abbreviation": "AZ", "sport": {"id": 1}},
            {"id": 5015, "abbreviation": "SPR", "sport": {"id": 12}, "parentOrgId": 138},
            {"id": 5030, "abbreviation": "GVL", "sport": {"id": 14}, "parentOrgId": 111},
            # affiliate pointing at a parent NOT in sport-1 (defensive): dropped
            {"id": 9001, "abbreviation": "XXX", "sport": {"id": 12}, "parentOrgId": 9999},
        ]
    }


def test_team_org_map_resolves_parents_and_normalizes():
    org_map = build_team_org_map(_teams_payload())

    assert org_map[138] == "STL"  # sport-1 self
    assert org_map[109] == "ARI"  # AZ -> ARI normalization
    assert org_map[5015] == "STL"  # AA affiliate -> parent org
    assert org_map[5030] == "BOS"
    assert 9001 not in org_map  # orphan parent dropped


def test_resolve_orgs_skips_off_ladder_teams():
    org_map = build_team_org_map(_teams_payload())
    # 700251 traded to a STL affiliate; 999 plays winter ball (team not on ladder)
    resolved = resolve_orgs({700251: 5015, 999: 7777}, org_map)

    assert resolved == {"700251": "STL"}


def test_merge_preserves_prior_on_missing_and_overrides_on_fetch():
    prior = {"700251": "BOS", "999": "TBR"}
    fetched = {"700251": "STL"}

    merged = merge_preserving_prior(prior, fetched)

    assert merged == {"700251": "STL", "999": "TBR"}
