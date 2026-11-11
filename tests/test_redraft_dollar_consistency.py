import ast
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


class _StripStrings(ast.NodeTransformer):
    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return None
        return self.generic_visit(node)


def _source_functions():
    tree = _StripStrings().visit(ast.parse((ROOT / 'app.py').read_text(encoding='utf-8-sig')))
    names = {
        '_compute_dollar_values', '_custom_dynasty_values', '_redraft_board_bundle',
    }
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(selected) == len(names)
    for node in selected:
        if node.name != '_custom_dynasty_values':
            node.decorator_list = []
    module = ast.Module(body=[
        ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
        *selected,
    ], type_ignores=[])
    return compile(ast.fix_missing_locations(module), '<selected-app-source-functions>', 'exec')


def _namespace(values):
    players = [SimpleNamespace(
        id=f'invented-{index:03}', name=f'Invented {index}', metadata={},
        positions=('OF',), pool='hitter',
    ) for index in range(len(values))]
    results = [SimpleNamespace(player=player, total_value=value) for player, value in zip(players, values)]
    rows = [SimpleNamespace(
        id=player.id, is_prospect=False,
    ) for index, player in enumerate(players)]
    by_id = {player.id: player for player in players}
    store = SimpleNamespace(get_all=lambda: list(players), as_of='invented-generation')
    dd_store = SimpleNamespace(
        get_all=lambda: list(rows),
    )
    ns = {
        'lru_cache': lru_cache, 'store': store, 'dd_store': dd_store,
        'build_config': lambda **kwargs: kwargs,
        '_valuation_players': lambda active_store: list(players),
        '_redraft_value_players': lambda players_arg, config: results,
        'build_outlook_match_index': lambda player_list: SimpleNamespace(find=lambda row: [by_id[row.id]]),
        '_redraft_value_scale': lambda results_arg: {},
        '_compute_position_ranks': lambda results_arg: {},
        '_compute_tiers': lambda results_arg: {},
        '_REDRAFT_BUNDLE_CACHE': OrderedDict(), '_REDRAFT_BUNDLE_MAX': 16,
    }
    exec(_source_functions(), ns)
    return ns, results, rows


def _annual_pair(values, teams=12, budget=200):
    ns, results, rows = _namespace(values)
    input_order = [result.player.id for result in results]
    now = ns['_custom_dynasty_values'](('HR',), ('K',), teams, budget)
    assert [result.player.id for result in results] == input_order
    bundle = ns['_redraft_board_bundle'](
        ns['store'], {}, 'steamer', ns['store'].as_of, 'categories', ('HR',), ('K',), '', (), False, (),
    )
    canonical = ns['_compute_dollar_values'](bundle['metadata_pool'], num_teams=teams, budget=budget)
    return ns, results, rows, now, canonical


@pytest.mark.parametrize('count', [199, 200, 201])
def test_now_uses_canonical_allocation_boundary(count):
    _, _, rows, now, canonical = _annual_pair([1] * count)
    assert now == {row.id: canonical.get(row.id, 0) for row in rows}
    assert now['invented-000'] == round(2400 / min(count, 200), 1)
    if count == 201:
        assert now['invented-200'] == 0


@pytest.mark.parametrize('values,highest_id', [([100] + [1] * 200, 'invented-000'),
                                               ([1] * 200 + [100], 'invented-200')])
def test_visible_unequal_case_sorts_final_values_without_reordering_mapping_input(values, highest_id):
    _, _, rows, now, canonical = _annual_pair(values)
    assert now[highest_id] == 802.7
    assert now == {row.id: canonical.get(row.id, 0) for row in rows}


def test_custom_team_budget_preserved_with_same_canonical_pool():
    _, _, rows, now, canonical = _annual_pair([100] + [1] * 200, teams=10, budget=300)
    assert now['invented-000'] == 1003.3
    assert now['invented-200'] == 0
    assert now == {row.id: canonical.get(row.id, 0) for row in rows}


@pytest.mark.parametrize('values', [[1] * 199 + [0, -1], [0, -1, -2], []])
def test_zero_negative_and_empty_values_match_canonical_lookup(values):
    _, _, rows, now, canonical = _annual_pair(values)
    assert now == {row.id: canonical.get(row.id, 0) for row in rows}
    if values and max(values) <= 0:
        assert canonical == {}
        assert set(now.values()) == {0}


def test_cutoff_ties_keep_stable_input_order_and_unallocated_player_stays_mapped():
    _, _, rows, now, _ = _annual_pair([1] * 201)
    assert list(now) == [row.id for row in rows]
    assert all(now[row.id] == 12 for row in rows[:200])
    assert now[rows[200].id] == 0
