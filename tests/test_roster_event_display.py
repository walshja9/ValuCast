import ast
from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

from jinja2 import DictLoader, Environment, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
NEUTRAL = "MLB roster listed — active status unverified"
DEBUT = "MLB debut recorded"
LUKE_ID = 702726


@lru_cache
def app_tree():
    return ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))


@lru_cache
def load_badges():
    path = ROOT / "web" / "roster_event_display.py"
    namespace = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace["roster_event_badges"]


def badges(**facts):
    return load_badges()(**facts)


def app_functions(names, **stubs):
    """Execute only selected top-level function definitions from the app."""
    selected = [
        node for node in app_tree().body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in selected} == set(names)
    namespace = {"roster_event_badges": badges, **stubs}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<isolated app functions>", "exec"), namespace)
    return namespace


@lru_cache
def templates():
    sources = {
        name: (ROOT / "templates" / name).read_text(encoding="utf-8")
        for name in ("backfields.html", "track_record.html")
    }
    sources.update({
        "base.html": "{% block content %}{% endblock %}",
        "partials/_editorial_date.html": "{% macro editorial_date(day) %}{{ day }}{% endmacro %}",
        "partials/_board_nav.html": "{% macro board_nav(active, aria) %}{% endmacro %}",
        "partials/_stale_notice.html": "",
        "partials/_prospect_tag.html": "",
        "partials/_call_up_scoring_rules.html": "",
    })
    return Environment(loader=DictLoader(sources), autoescape=select_autoescape(("html",)))


def render(name, context):
    return templates().get_template(name).render(**context)


def row(mlbam_id, name, score, retained=False):
    return SimpleNamespace(
        id=f"vc_prospect_{mlbam_id}_hitter", mlbam_id=mlbam_id, role="hitter", name=name,
        is_prospect=True, active_mlb_callup=retained, positions=("3B",), mlb_team="MIL",
        level="AAA", value=score, dynasty_value=score,
    )


def backfields_app(service):
    luke = row(LUKE_ID, "Luke Adams", 20, retained=True)
    fillers = [row(800000 + i, f"Prospect {i}", 19 - i, retained=True) for i in range(7)]
    watch = row(800007, "Upcoming Prospect", 4)
    snapshot = [luke, *fillers, watch]
    pulse_key = "800008_pitcher"
    pulse = {"by_identity": {
        pulse_key: {"mlbam_id": "800008", "name": "Pulse-only Prospect", "mlb_team": "MIL"},
    }}

    def load_artifact(path):
        return pulse if path.name == "valucast_call_up_pulse.json" else None

    return app_functions(
        (
            "_identity_key", "_row_identity_key", "_prospect_has_debuted",
            "_active_mlb_roster_rows", "_build_backfields_page_context", "_prospect_has_roster_signal",
        ),
        Path=Path,
        __file__="synthetic-app-root/app.py",
        dd_store=SimpleNamespace(is_available=True, generated_at=None, get_all=lambda: snapshot),
        _ACTIVE_ROSTER_ROWS=None,
        _ACTIVE_ROSTER_PULSE_PATH=SimpleNamespace(
            name="valucast_call_up_pulse.json", stat=lambda: SimpleNamespace(st_mtime_ns=91),
        ),
        _load_artifact=load_artifact,
        _prospect_tiers=lambda: {},
        _prospect_rows=lambda: snapshot,
        _debuted_prospect_ids=lambda: service,
        _call_up_pulse_keys=lambda: frozenset({pulse_key}),
        _indexed_artifact_rows=lambda *args: {},
        _team_board_eta=lambda _: None,
        _team_board_year_bucket=lambda _: "This year",
        LEVEL_ORDER={"AAA": 5},
        quote=quote,
        urlencode=urlencode,
        _build_buys_page_context=lambda _: {},
        buy_score=SimpleNamespace(BOARD_SIZE=20),
        _build_team_board_context=lambda: {},
        _team_board_move_window_days=lambda: 7,
        _team_board_move_window_label=lambda: "7 days",
    )


def call(identity_key, status, in_mlb):
    return {
        "identity_key": identity_key, "name": "Luke Adams", "status": status, "in_mlb": in_mlb,
        "valucast_then": 18, "valucast_now": 23, "consensus_then": 49, "consensus_now": 37,
        "consensus_catch_up": 12, "streak_since": None, "ahead_since": "2026-07-16",
        "days_tracked": 19, "grade": {"result": "fixture-grade", "numerator": 3, "denominator": 8},
    }


def scorecard():
    return {
        "gate": {"publishable": True, "min_publish_horizon_days": 30},
        "summary": {
            "first_call_date": "2026-07-02", "ever_flagged": 21, "wins": 7,
            "decided_count": 10, "horizon_days": 90, "immature_decided": 3,
            "decided_rate": 0.7, "control_lift": 1.5,
            "matured_open_rates": {"toward": 3, "n": 8, "toward_rate": 0.375},
            "control_matured_rates": {"toward": 2, "n": 8, "toward_rate": 0.25},
        },
        "targets": {"decided_rate": 0.5, "control_lift": 1.2},
        "funnel": {
            "open_toward": 4, "closed_caught_up": 3, "open_away": 2,
            "retired_we_backed_off": 1, "open_flat": 5,
            "resolved_called_up_or_graduated": 6, "left_universe": 0,
        },
        "calls": [
            call(f"{LUKE_ID}_hitter", "open_toward", True),
            call("800010_pitcher", "resolved_called_up_or_graduated", False),
            call("800010_unverified", "open_flat", "true"),
        ],
    }


def service_fixture(payload):
    fixture = SimpleNamespace(payload=payload, stamp=91)
    fixture.stat = lambda: SimpleNamespace(st_mtime_ns=fixture.stamp)
    fixture.read_text = lambda *, encoding: json.dumps(fixture.payload)
    return fixture


def ledger_app(sc, service_path):
    return app_functions(
        ("_track_record_scorecard", "_track_record_context", "_debuted_prospect_ids"),
        _load_scorecard_payload=lambda: sc,
        _build_receipts_page_context=lambda: {"receipts_available": False},
        _DEBUTED_PROSPECT_IDS=None,
        _DEBUTED_PROSPECT_IDS_PATH=service_path,
        json=json,
        math=math,
        SCOREBOARD_HOLD=False,
        _load_forward_scoreboard_payload=lambda: {"fixture": True},
        _scoreboard_view=lambda _: {
            "wins": 3, "losses": 1, "pool_size": 4, "win_rate_pct": 75,
            "clean_retractions": 2, "open": 8,
        },
    )


def ledger_context(sc):
    service = service_fixture({"mlb_service": [{"mlbam_id": 800010, "ip": 4}]})
    return ledger_app(sc, service)["_track_record_context"]()


class RosterBadgeTests(unittest.TestCase):
    def test_legacy_listing_carries_only_neutral_badge(self):
        self.assertEqual([b["label"] for b in badges(roster_listed=True)], [NEUTRAL])

    def test_rule_5_purpose_requires_explicit_40_man_membership_and_purpose(self):
        self.assertEqual(badges(rule_5_protection=True), [])
        plain = badges(on_40_man=True)
        self.assertEqual([b["label"] for b in plain], ["40-man roster"])
        self.assertNotIn("Rule 5", plain[0]["title"])
        protected = badges(on_40_man=True, rule_5_protection=True)
        self.assertEqual([b["label"] for b in protected], ["40-man roster · Rule 5 protection"])

    def test_active_membership_can_precede_debut(self):
        self.assertEqual([b["label"] for b in badges(active_roster=True)], ["Active MLB roster"])

    def test_recorded_debut_can_outlast_active_membership(self):
        self.assertEqual([b["label"] for b in badges(active_roster=False, debut_recorded=True)], [DEBUT])

    def test_confirmed_facts_can_coexist(self):
        confirmed = badges(roster_listed=True, on_40_man=True, active_roster=True, debut_recorded=True)
        self.assertEqual([b["label"] for b in confirmed], ["40-man roster", "Active MLB roster", DEBUT])
        self.assertEqual(len({b["kind"] for b in confirmed}), 3)

    def test_non_boolean_facts_do_not_promote_status(self):
        self.assertEqual(
            badges(roster_listed="true", on_40_man=1, active_roster="Active", debut_recorded="4 IP"),
            [],
        )
        self.assertEqual([b["label"] for b in badges(on_40_man=True, rule_5_protection=1)], ["40-man roster"])


class DebutFilterTests(unittest.TestCase):
    def test_shared_predicate_uses_recorded_service_only(self):
        namespace = app_functions(("_identity_key", "_row_identity_key", "_prospect_has_debuted"))
        predicate = namespace["_prospect_has_debuted"]
        luke = row(LUKE_ID, "Luke Adams", 20, retained=True)
        self.assertFalse(predicate(luke, {}, {f"{LUKE_ID}_hitter"}))
        pulsed = row(800008, "Pulse-only Prospect", 0)
        self.assertFalse(predicate(pulsed, {}, {"800008_hitter"}))
        self.assertTrue(predicate(luke, {str(LUKE_ID): "4 PA"}, set()))
        self.assertTrue(predicate(pulsed, {"800008": "2 IP"}, set()))

    def test_share_filter_keeps_internal_values_and_legacy_alias(self):
        namespace = app_functions(
            ("_identity_key", "_row_identity_key", "_prospect_has_debuted", "_prospect_share_debut_view"),
            _debuted_prospect_ids=lambda: {"800008": "2 IP"},
            _call_up_pulse_keys=lambda: {f"{LUKE_ID}_hitter"},
        )
        filters = namespace["_prospect_share_debut_view"]
        luke = row(LUKE_ID, "Luke Adams", 20, retained=True)
        appeared = row(800008, "Appeared Prospect", 1)
        for query, expected_view, expected_luke in (
            ("debuted", "debuted", False), ("undebuted", "undebuted", True), ("milb", "undebuted", True),
        ):
            with self.subTest(query=query):
                predicate, view = filters({"callups": query})
                self.assertEqual(view, expected_view)
                self.assertEqual(predicate(luke), expected_luke)
                self.assertEqual(predicate(appeared), not expected_luke)


class BackfieldsTests(unittest.TestCase):
    def test_folded_row_keeps_roster_badges_outside_team_and_value(self):
        context = backfields_app({"800008": "3 IP"})["_build_backfields_page_context"]()
        player = context["recently_called_up_more"][0]
        html = render("backfields.html", context)
        folded = html.split('<ul class="bf-callup-more-list">', 1)[1].split('</ul>', 1)[0]
        entry = ElementTree.fromstring(folded.strip().replace("<br>", "<br/>"))
        name, meta, *status_line = entry
        self.assertEqual(name.text.strip(), player["name"])
        self.assertEqual("".join(meta.itertext()).strip(), f'{player["flag"]} · {player["value"]}')
        self.assertEqual(len(status_line), 1)
        self.assertEqual([badge.text for badge in status_line[0]], [NEUTRAL, DEBUT])

    def test_legacy_rows_render_neutral_in_cards_and_folded_list(self):
        context = backfields_app({})["_build_backfields_page_context"]()
        self.assertEqual(context["recently_called_up_total"], 9)
        self.assertEqual(context["recently_called_up"][0]["name"], "Luke Adams")
        self.assertEqual([r["value"] for r in context["recently_called_up"]], [
            "20.0", "19.0", "18.0", "17.0", "16.0", "15.0", "14.0", "13.0",
        ])
        self.assertEqual([r["name"] for r in context["recently_called_up_more"]], ["Pulse-only Prospect"])
        self.assertEqual([r["name"] for r in context["callups"]], ["Upcoming Prospect"])

        html = render("backfields.html", context)
        nav_label = html.split('href="#got-the-call">', 1)[1].split('</a>', 1)[0]
        self.assertEqual(nav_label, 'MLB roster status')
        for label in ('data-bf-debut="Debuted"', 'data-bf-debut="Not debuted"', 'callups=debuted',
                      'callups=undebuted', '>Debut recorded</', '>No debut recorded</'):
            self.assertIn(label, html)
        section = html.split('id="got-the-call"', 1)[1].split("</section>", 1)[0]
        main, folded = section.split('<details class="bf-callup-more">', 1)
        self.assertIn("9 rookie-eligible prospects listed", main)
        self.assertIn("Luke Adams", main)
        self.assertEqual(main.count(NEUTRAL), 8)
        self.assertIn("Pulse-only Prospect", folded)
        self.assertEqual(folded.count(NEUTRAL), 1)
        self.assertNotIn("In the show", section)
        self.assertNotIn(DEBUT, section)

    def test_service_changes_refresh_labels_with_cached_roster_rows(self):
        service = {}
        namespace = backfields_app(service)
        context = namespace["_build_backfields_page_context"]()
        cached_rows = namespace["_ACTIVE_ROSTER_ROWS"]
        self.assertFalse(context["rankings"][0]["debuted"])
        service.update({str(LUKE_ID): "2 PA", "800008": "3 IP"})
        context = namespace["_build_backfields_page_context"]()
        self.assertIs(namespace["_ACTIVE_ROSTER_ROWS"], cached_rows)
        self.assertTrue(context["rankings"][0]["debuted"])
        for field in ("recently_called_up", "recently_called_up_more"):
            self.assertEqual([b["label"] for b in context[field][0]["roster_badges"]], [NEUTRAL, DEBUT])

    def test_explicit_facts_and_html_escaping_in_real_template(self):
        context = backfields_app({})["_build_backfields_page_context"]()
        context["recently_called_up"][0]["roster_badges"] = badges(
            on_40_man=True, rule_5_protection=True, active_roster=True,
        )
        context["recently_called_up_more"][0]["roster_badges"] = [
            *badges(debut_recorded=True), {"label": '<b>"unsafe"</b>', "title": '"<&'},
        ]
        html = render("backfields.html", context)
        section = html.split('id="got-the-call"', 1)[1].split("</section>", 1)[0]
        main, folded = section.split('<details class="bf-callup-more">', 1)
        self.assertIn("40-man roster · Rule 5 protection", main)
        self.assertIn("Active MLB roster", main)
        self.assertIn(DEBUT, folded)
        self.assertIn("&lt;b&gt;&#34;unsafe&#34;&lt;/b&gt;", folded)
        self.assertIn('title="&#34;&lt;&amp;"', folded)
        self.assertNotIn('<b>"unsafe"</b>', folded)


class LedgerTests(unittest.TestCase):
    def test_malformed_service_payload_preserves_ledger(self):
        for payload in (None, [1], "bad payload", {"mlb_service": 1}, {"mlb_service": "bad rows"},
                        {"mlb_service": {"mlbam_id": 800010, "ip": 4}}):
            with self.subTest(payload=payload):
                sc = scorecard()
                original = deepcopy(sc)
                context = ledger_app(sc, service_fixture(payload))["_track_record_context"]()
                self.assertIs(context["sc"], sc)
                self.assertEqual(sc, original)
                self.assertEqual(
                    [[b["label"] for b in group] for group in context["call_roster_badges"]],
                    [[NEUTRAL], [], []],
                )

    def test_invalid_service_stats_do_not_hide_positive_evidence_or_ledger_numbers(self):
        invalid = (None, "unknown", "12", True, False, math.nan, math.inf, -math.inf, {}, [], -1, 0)
        service_rows = [{"mlbam_id": LUKE_ID, "pa": True, "ip": math.nan}]
        service_rows += [
            {"mlbam_id": 800020 + i, "pa": value, "ip": value} for i, value in enumerate(invalid)
        ]
        service_rows += [
            None, [1], "bad row", {},
            {"mlbam_id": 800010, "pa": "unknown", "ip": 4},
            {"mlbam_id": "800011", "pa": 12, "ip": math.inf, "graduated": False},
            {"mlbam_id": 800012, "pa": 2, "ip": 7.1},
            {"mlbam_id": 800013, "ip": 1.2},
            {"mlbam_id": 800014, "pa": 25, "graduated": True},
        ]
        sc = scorecard()
        original = deepcopy(sc)
        namespace = ledger_app(sc, service_fixture({"mlb_service": service_rows}))
        context = namespace["_track_record_context"]()
        self.assertIs(context["sc"], sc)
        self.assertEqual(sc, original)
        self.assertEqual(namespace["_debuted_prospect_ids"](), {
            "800010": "4 IP", "800011": "12 PA", "800012": "2 PA", "800013": "1.2 IP",
        })
        self.assertEqual(
            [[b["label"] for b in group] for group in context["call_roster_badges"]],
            [[NEUTRAL], [DEBUT], []],
        )
        self.assertEqual(render("track_record.html", context), render("track_record.html", ledger_context(original)))

    def test_real_service_cache_refreshes_when_file_stamp_changes(self):
        service = service_fixture({"mlb_service": [{"mlbam_id": LUKE_ID, "pa": 2}]})
        namespace = ledger_app(scorecard(), service)
        read_service = namespace["_debuted_prospect_ids"]
        initial = read_service()
        self.assertEqual(initial, {str(LUKE_ID): "2 PA"})
        service.payload = {"mlb_service": [{"mlbam_id": 800010, "ip": 4}]}
        self.assertIs(read_service(), initial)
        service.stamp += 1
        context = namespace["_track_record_context"]()
        self.assertEqual(read_service(), {"800010": "4 IP"})
        self.assertEqual(
            [[b["label"] for b in group] for group in context["call_roster_badges"]],
            [[NEUTRAL], [DEBUT], []],
        )

    def test_badges_join_by_identity_without_mutating_scorecard(self):
        sc = scorecard()
        original = deepcopy(sc)
        context = ledger_context(sc)
        self.assertIs(context["sc"], sc)
        self.assertEqual(sc, original)
        self.assertEqual(
            [[b["label"] for b in group] for group in context.get("call_roster_badges", [])],
            [[NEUTRAL], [DEBUT], []],
        )

    def test_missing_scorecard_has_no_roster_badges(self):
        context = ledger_context(None)
        self.assertIsNone(context["sc"])
        self.assertEqual(context.get("call_roster_badges"), [])
        self.assertIn("The ledger artifact is not available", render("track_record.html", context))

    def test_real_template_preserves_values_and_outcomes_and_renders_new_badges(self):
        context = ledger_context(scorecard())
        html = render("track_record.html", context)
        rows = re.findall(r'<article class="ledger-row".*?</article>', html, re.S)
        self.assertEqual(len(rows), 3)
        self.assertIn(NEUTRAL, rows[0])
        self.assertIn("Active roster status is unverified", rows[0])
        self.assertIn(DEBUT, rows[1])
        self.assertNotIn('ledger-chip-mlb', rows[2])
        self.assertNotIn(">in the majors<", html)
        for text in (
            "3–1 across 4 scored calls (75%)", "7 of 10 mature decisions (70%)",
            "21 calls tracked since 2026-07-02", "3/8 vs 2/8 matched controls (1.5x)",
            "3 caught up &middot; 4 trending our way", "6 resolved by call-up/graduation",
        ):
            self.assertIn(text, html)
        for rendered, kind, outcome in zip(rows, ("win", "resolved", "open"), (
            "Field moving to us", "Called up / graduated", "No decisive move",
        )):
            self.assertIn(f'data-ledger-kind="{kind}"', rendered)
            self.assertIn(outcome, rendered)
            self.assertIn("us #18 &rarr; #23", rendered)
            self.assertIn("field ~#49 &rarr; ~#37", rendered)
            self.assertIn("field +12", rendered)
            self.assertIn("2026-07-16 &middot; 19d", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
