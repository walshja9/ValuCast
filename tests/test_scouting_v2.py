"""Scouting V2: voice guard + LLM writer (no real API calls — fake client only)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scouting import report_generator, repository
from scouting.mlb_read import stat_line_stats
from scouting.voice import (
    VOICE_PROMPT,
    banned_phrase_hits,
    derived_word_number_problems,
    handedness_problems,
    role_vocab_problems,
    sample_context_stale,
    unsupported_numbers,
    validate_report_text,
)

GROUNDING = {
    "name": "Test Prospect", "role": "hitter", "level": "AA", "age": 21,
    "card_display_line": {
        "avg": 0.300, "obp": 0.380, "slg": 0.520, "ops": 0.900,
        "iso": 0.220, "k_pct": 18.0, "bb_pct": 11.0, "pa": 240,
        "usage": "the line shown on the card skill bars",
    },
    "current_skill_percentiles": {"ops": 96, "iso": 92, "k_pct": 70},
}


class TestVoiceGuard(unittest.TestCase):
    def test_banned_phrases_flagged(self):
        self.assertIn("tantalizing", banned_phrase_hits("A tantalizing bat."))
        self.assertIn("most accurate", banned_phrase_hits("the MOST ACCURATE read"))
        self.assertEqual(banned_phrase_hits("A direct, plain read."), [])

    def test_style_problems_flag_robotic_tells(self):
        from scouting.voice import style_problems

        # 7/5 audit tells: identity-template opener, em-dash chains, "is real" stamp
        self.assertTrue(style_problems("Cam Cannarella is a 22-year-old center fielder who hits."))
        self.assertTrue(style_problems("Josue De Paula is an advanced bat."))
        self.assertTrue(style_problems("Good bat — real power — no glove to speak of."))
        self.assertTrue(style_problems("His .236 ISO says the power is real."))
        self.assertEqual(style_problems("The bat carries the profile — everything else follows."), [])
        self.assertEqual(style_problems("A contact-first shortstop with sneaky pop."), [])

    def test_style_problems_gate_ok_but_not_hard_ok(self):
        text = "Test Prospect is a 21-year-old hitter with a .300 average."
        guard = validate_report_text(text, GROUNDING)
        self.assertTrue(guard["style_problems"])
        self.assertFalse(guard["ok"])
        self.assertTrue(guard["hard_ok"])

    def test_derived_word_number_problems_catches_real_examples(self):
        # 7/9 claims audit: a derived numeric delta spelled as a WORD slips the
        # digit-only number guard. Verbatim caught fragments from the live artifact.
        # Template A: "<word> points/ticks above|below" (Eli Willits, 816113_hitter).
        self.assertTrue(derived_word_number_problems(
            "translates to a 12.0% MLB-equivalent rate, more than three points above "
            "the big-league average"))
        # Template B: multiplier comparative "double the ... norm" (Brody Hopkins).
        self.assertTrue(derived_word_number_problems(
            "the MLB-equivalent BB/9 of 6.5 is double the major-league norm"))
        # Sirota's "double the 8.5% major-league baseline" — the modifier rides the gap.
        self.assertTrue(derived_word_number_problems(
            "sits at double the 8.5% major-league baseline for the position"))

    def test_derived_word_number_problems_excludes_measured_false_positives(self):
        # Regression pins for the precision anchor. Both are real artifact text the
        # naive pattern flagged and the tightened regex correctly clears.
        # Jacob Gonzalez: "half the power" is not a numeric claim (no anchor word).
        self.assertEqual(
            derived_word_number_problems("translation normally scrubs half the power"), [])
        # Enrique Bradfield Jr.: "more than half the time" is an idiom, not a delta.
        self.assertEqual(
            derived_word_number_problems(
                "lands him as organizational depth more than half the time"), [])

    def test_derived_word_number_problems_ignores_clean_cited_rate(self):
        # A grounded rate cited plainly is fine — no multiplier word before "rate",
        # so Template B's anchor must not fire on a bare cited rate.
        self.assertEqual(
            derived_word_number_problems(
                "A .416 OBP at 18 with a 12.0% MLB-equivalent walk rate."), [])

    def test_derived_word_number_gates_ok_but_not_hard_ok(self):
        # Same soft-signal class as unsupported_numbers: gates ok (drives regen),
        # leaves hard_ok True (not a factual hazard that discards a good read).
        guard = validate_report_text(
            "A clean opener. It runs three points above the big-league average over 240 PA.",
            GROUNDING,
        )
        self.assertTrue(guard["derived_word_number_problems"])
        self.assertFalse(guard["ok"])
        self.assertTrue(guard["hard_ok"])

    def test_role_vocab_catches_the_five_real_cache_leaks(self):
        # 7/5 cache scan: 4 confirmed "<pitcher-role> arm" leaks + 1 "mid-rotation" tier
        # borrow, all in HITTER reads. Verbatim fragments from the actual leaked text.
        hitter = {"role": "hitter"}
        self.assertTrue(role_vocab_problems(
            "you're left with a patient organizational depth arm at shortstop", hitter))
        self.assertTrue(role_vocab_problems(
            "this is a depth arm at a position and nothing more", hitter))
        self.assertTrue(role_vocab_problems(
            "he's a depth arm behind the dish", hitter))
        self.assertTrue(role_vocab_problems(
            "a useful bench piece... and an organizational arm if the strikeouts", hitter))
        self.assertTrue(role_vocab_problems(
            "a .276/.339/.467 line ... is a mid-rotation regular", hitter))

    def test_role_vocab_does_not_flag_legitimate_hitter_arm_usage(self):
        hitter = {"role": "hitter"}
        for text in (
            "he's got a plus arm across the infield",
            "a 70-grade arm that plays anywhere on the dirt",
            "the arm is a carrying tool, strong and accurate",
            "cannon arm, elite arm strength from center",
            "he's a non-starter at short but the bat plays",
            "not a starter at the position long-term",
            "an everyday starter once the bat catches up",
            "a rotation that actively hunts left-handed hitters",
            "he's closer to a everyday regular than a bench bat",
        ):
            self.assertEqual(role_vocab_problems(text, hitter), [], text)

    def test_role_vocab_catches_pitcher_arm_rephrasings(self):
        # Adversarial-review addendum: the retry loop feeds the exact flagged phrase
        # back, so the model's next paraphrase attempt must also be caught.
        hitter = {"role": "hitter"}
        for text in (
            "he's just a spare arm off the bench",
            "profiles as a filler arm at the position",
            "an up-and-down arm if the bat never develops",
            "nothing more than an emergency arm",
            "a mop-up arm at best",
            "a bulk-innings arm if the power doesn't show",
            "profiles as a long reliever" ,
            "settles in as a middle reliever type",
        ):
            self.assertTrue(role_vocab_problems(text, hitter), text)

    def test_role_vocab_pitcher_direction_ignores_opponent_facing_language(self):
        # Adversarial review's serious flaw: a pitcher legitimately describes the
        # hitters he faces this way constantly. Must never fire.
        pitcher = {"role": "pitcher"}
        for text in (
            "neutralizes platoon bats all night",
            "keeps corner bats honest with the changeup",
            "gets everyday bats out with the same fastball",
            "fools utility bats but not stars",
            "shuts down first-division bats in the division",
            "works around the everyday regular in the three-hole",
            "against a fringe regular he cruises",
            "his batted-ball profile plays even in a bandbox",
            "off his bat, contact quality craters against the slider",
        ):
            self.assertEqual(role_vocab_problems(text, pitcher), [], text)

    def test_role_vocab_pitcher_direction_catches_self_referential_verdicts(self):
        pitcher = {"role": "pitcher"}
        for text in (
            "he's an everyday bat masquerading as an arm",
            "projects as a bench bat if the stuff never ticks up",
            "bat-first profile with a fringe fastball",
        ):
            self.assertTrue(role_vocab_problems(text, pitcher), text)

    def test_role_vocab_skips_two_way_players(self):
        self.assertEqual(
            role_vocab_problems("a depth arm at short and a mop-up arm on the mound",
                                 {"role": "two_way"}),
            [],
        )

    def test_role_vocab_gates_ok_and_hard_ok(self):
        guard = validate_report_text(
            "you're left with a patient organizational depth arm at shortstop",
            {**GROUNDING, "role": "hitter"},
        )
        self.assertTrue(guard["role_vocab_problems"])
        self.assertFalse(guard["ok"])
        self.assertFalse(guard["hard_ok"])

    def test_supported_numbers_pass(self):
        # cites the line + an ordinal percentile, all present in grounding
        text = "A .300/.380/.520 line over 240 PA, with a 96th-percentile OPS at age 21."
        self.assertEqual(unsupported_numbers(text, GROUNDING), [])

    def test_stat_line_stats_derives_slg_from_ops_and_obp(self):
        stats = stat_line_stats({"stats": {"AVG": 0.300, "OBP": 0.380, "OPS": 0.900}})

        self.assertEqual(stats["SLG"], 0.520)

    def test_ops_in_triple_slash_slg_slot_is_hard_fail(self):
        result = validate_report_text("A .300/.380/.900 line over 240 PA.", GROUNDING)

        self.assertFalse(result["hard_ok"])
        self.assertFalse(result["ok"])

    def test_invented_number_flagged(self):
        text = "Sits 97 mph with the fastball."   # 97 is nowhere in the grounding
        self.assertIn("97", unsupported_numbers(text, GROUNDING))

    def test_leading_dot_two_digit_rate_supported(self):
        # Regression: ".22" used to tokenize as 22 and fail to match grounding's 0.220
        # (the >=30 leading-zero workaround only caught 3-digit forms like ".220"),
        # which silently discarded otherwise-correct LLM reports to deterministic copy.
        text = "Real game power — a .22 ISO with an 11.0% walk rate over 240 PA."
        self.assertEqual(unsupported_numbers(text, GROUNDING), [])
        self.assertTrue(validate_report_text(text, GROUNDING)["ok"])

    def test_count_does_not_validate_same_digits_rate(self):
        # BUG A regression: a PA *count* of 322 must not "ground" a hallucinated .322 AVG.
        # The /1000 collapse is rate-only, so a count cannot back a same-digits rate.
        grounding = {"role": "hitter", "card_display_line": {"pa": 322}}
        # report cites a .322 AVG that is NOT in the grounding (only the 322 PA count is)
        flagged = unsupported_numbers("A .322 hitter.", grounding)
        self.assertIn(".322", flagged)
        self.assertFalse(validate_report_text("A .322 hitter.", grounding)["ok"])

    def test_real_rate_still_validates(self):
        # A genuine .322 AVG grounded by a real .322 rate value stays supported.
        grounding = {"role": "hitter", "card_display_line": {"avg": 0.322, "pa": 322}}
        self.assertEqual(unsupported_numbers("A .322 hitter over 322 PA.", grounding), [])
        self.assertTrue(validate_report_text("A .322 hitter over 322 PA.", grounding)["ok"])

    def test_sample_context_stale_when_current_sample_never_cited(self):
        # 7/1 bug: Nolan Perry's report described his old single-level A+ line
        # (30.7 IP) after his card moved to a combined 3-level line (54.7 IP).
        # None of the old text's numbers look "unsupported" -- they still appear
        # in the new grounding's per-level breakdown -- so unsupported_numbers()
        # alone lets it through. sample_context_stale() must catch it separately.
        grounding = {**GROUNDING, "sample_context": {"sample": 54.7, "sample_unit": "IP"}}
        stale_text = "Over 30.7 IP at A+, he posted a 3.23 ERA and 1.24 WHIP."
        self.assertTrue(sample_context_stale(stale_text, grounding))

    def test_sample_context_not_stale_when_current_sample_is_cited(self):
        grounding = {**GROUNDING, "sample_context": {"sample": 54.7, "sample_unit": "IP"}}
        fresh_text = "Over 54.7 IP across three levels, he posted a 2.47 ERA."
        self.assertFalse(sample_context_stale(fresh_text, grounding))

    def test_sample_context_stale_false_without_a_sample_context(self):
        # No sample_context in the grounding (e.g. an MLB-player report shape) ->
        # nothing to compare against, so this must never false-positive.
        self.assertFalse(sample_context_stale("Any text at all.", GROUNDING))

    def test_wrong_hitter_handedness_is_flagged(self):
        # BUG B: a hitter described with the wrong batting side must be flagged.
        lefty_hitter = {**GROUNDING, "role": "hitter", "bats": "L"}
        problems = handedness_problems("A right-handed bat with real pop.", lefty_hitter)
        self.assertTrue(problems)
        result = validate_report_text("A right-handed bat over 240 PA.", lefty_hitter)
        self.assertFalse(result["hard_ok"])
        self.assertTrue(result["handedness_problems"])

        # a correct side (or a switch hitter) is not flagged
        self.assertEqual(handedness_problems("A left-handed bat.", lefty_hitter), [])
        switch = {**GROUNDING, "role": "hitter", "bats": "S"}
        self.assertEqual(handedness_problems("A left-handed bat from the right side too.", switch), [])

    def test_llm_grounding_includes_peak_detail_and_rank_movement(self):
        base = dict(
            name="Test", role="hitter", positions=["SS"], team="BOS", level="AA", age=21,
            prospect_rank=12, context={}, metadata={}, bats=None, throws=None,
            stat_line={"avg": 0.300}, stat_line_translated=None, best_single_level_stat_line=None,
            availability_context=None, has_peak_projection=True,
            peak_projection_summary="impact regular",
            peak_role_label="everyday regular", peak_floor_label="bench bat",
            peak_eta_label="2027", peak_trajectory_label="ahead of current value",
            peak_shape_items=[{"label": "Power", "grade": 55}],
            peak_role_probability_items=[{"label": "star", "pct": 18}],
        )
        g = repository._llm_grounding(
            SimpleNamespace(**base), {}, "AA hitters",
            recent_signal={"movement_label": "rising", "score_delta_3d": 1.2, "rank_delta_3d": 5},
        )
        self.assertEqual(g["peak_projection_detail"]["role_ceiling"], "everyday regular")
        self.assertEqual(g["peak_projection_detail"]["floor"], "bench bat")
        self.assertEqual(g["valucast_rank_movement"]["direction"], "rising")
        # absent (filtered) when there's no peak projection and no movement
        g2 = repository._llm_grounding(
            SimpleNamespace(**{**base, "has_peak_projection": False}), {}, "AA hitters")
        self.assertNotIn("peak_projection_detail", g2)
        self.assertNotIn("valucast_rank_movement", g2)

    def test_validate_combines_hard_and_soft(self):
        clean = validate_report_text("A .300 hitter over 240 PA with a 96th-pct OPS.", GROUNDING)
        self.assertTrue(clean["ok"])
        self.assertTrue(clean["hard_ok"])

        banned = validate_report_text("A tantalizing .300 bat over 240 PA.", GROUNDING)
        self.assertFalse(banned["hard_ok"])      # banned phrase = hard fail
        self.assertFalse(banned["ok"])

        invented = validate_report_text("A .300 bat who sits 97 over 240 PA.", GROUNDING)
        self.assertTrue(invented["hard_ok"])     # no banned phrase
        self.assertFalse(invented["ok"])         # but an unsupported number

    def test_pitcher_handedness_mismatch_is_a_hard_fail(self):
        lefty_grounding = {
            **GROUNDING,
            "role": "pitcher",
            "throws": "L",
            "card_display_line": {"ip": 47.3, "k_per_9": 12.6, "bb_per_9": 5.3},
            "current_skill_percentiles": {"k_per_9": 88, "bb_per_9": 35},
        }

        problems = handedness_problems("A right-hander with a bat-missing fastball.", lefty_grounding)
        self.assertTrue(problems)

        result = validate_report_text("A right-hander with a 12.6 K/9 over 47.3 IP.", lefty_grounding)
        self.assertFalse(result["ok"])
        self.assertFalse(result["hard_ok"])
        self.assertTrue(result["handedness_problems"])

    def test_pitcher_handedness_mentions_are_blocked_when_grounding_missing(self):
        pitcher_grounding = {
            **GROUNDING,
            "role": "pitcher",
            "card_display_line": {"ip": 47.3, "k_per_9": 12.6, "bb_per_9": 5.3},
        }

        result = validate_report_text("A right-hander with a 12.6 K/9 over 47.3 IP.", pitcher_grounding)

        self.assertFalse(result["hard_ok"])
        self.assertIn("missing", result["handedness_problems"][0])


class _FakeMessages:
    def __init__(self, text):
        if isinstance(text, (list, tuple)):
            self.responses = list(text)
        else:
            self.responses = [text]
        self.kwargs = None
        self.calls = 0

    def create(self, **kwargs):
        self.kwargs = kwargs
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.responses[index])])


class _FakeClient:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


class TestGenerator(unittest.TestCase):
    def test_grounding_hash_stable_and_sensitive(self):
        h1 = report_generator.grounding_hash(GROUNDING)
        self.assertEqual(h1, report_generator.grounding_hash(dict(GROUNDING)))
        changed = {**GROUNDING, "age": 22}
        self.assertNotEqual(h1, report_generator.grounding_hash(changed))

    def test_build_prompt_contains_facts_only(self):
        prompt = report_generator.build_prompt(GROUNDING)
        self.assertIn("Test Prospect", prompt)
        self.assertIn("card_display_line", prompt)

    def test_generate_with_fake_client_passes_voice_system_prompt(self):
        client = _FakeClient("A patient AA bat: .300/.380/.520 over 240 PA, 96th-pct OPS.")
        result = report_generator.generate_report(GROUNDING, client=client)
        self.assertIsNotNone(result)
        self.assertTrue(result["valid"])
        self.assertEqual(client.messages.kwargs["system"], VOICE_PROMPT)
        self.assertIn("240 PA", result["text"])

    def test_generate_flags_banned_response(self):
        client = _FakeClient("A tantalizing .300 bat over 240 PA.")
        result = report_generator.generate_report(GROUNDING, client=client)
        self.assertFalse(result["valid"])
        self.assertFalse(result["hard_ok"])

    def test_generate_retries_invalid_numeric_format(self):
        client = _FakeClient([
            "A patient AA bat with a 22.0% ISO over 240 PA.",
            "A patient AA bat with a .220 ISO over 240 PA.",
        ])

        result = report_generator.generate_report(GROUNDING, client=client)

        self.assertTrue(result["valid"])
        self.assertEqual(client.messages.calls, 2)
        self.assertEqual(result["text"], "A patient AA bat with a .220 ISO over 240 PA.")

    def test_voice_prompt_preserves_decimal_rate_format(self):
        self.assertIn("AVG/OBP/SLG/OPS/ISO", VOICE_PROMPT)
        self.assertIn("decimal form", VOICE_PROMPT)

    def test_offline_returns_none(self):
        # No client + no available default client -> None (caller keeps deterministic).
        with patch.object(report_generator, "default_client", return_value=None):
            self.assertIsNone(report_generator.generate_report(GROUNDING))


class TestLlmWiring(unittest.TestCase):
    def test_attach_llm_reports_can_be_published_when_valid(self):
        row = SimpleNamespace(
            is_prospect=True, name="X", role="hitter", positions=["OF"], team="MIL",
            level="AA", age=21, prospect_rank=5,
            stat_line={"pa": 200, "avg": 0.300, "obp": 0.380, "slg": 0.500, "ops": 0.880,
                       "iso": 0.200, "k_pct": 18.0, "bb_pct": 10.0},
            stat_line_translated=None, best_single_level_stat_line=None,
            has_peak_projection=False, peak_projection_summary=None,
            availability_context={}, context={},
        )
        report = {"identity_key": "1_hitter", "report": "deterministic read"}
        store = SimpleNamespace(get_all=lambda: [row])
        with tempfile.TemporaryDirectory() as d, \
                patch.object(report_generator, "default_client",
                             return_value=_FakeClient("A patient AA bat with real contact.")), \
                patch.object(repository, "LLM_CACHE_PATH", Path(d) / "cache.json"):
            res = repository._attach_llm_reports([row], [report], store)
            cached = (Path(d) / "cache.json").exists()
        self.assertTrue(res["available"])
        self.assertEqual(res["generated"], 1)
        repository._publish_report_fields([report])
        self.assertEqual(report["report"], "deterministic read")
        self.assertEqual(report["published_report"], "A patient AA bat with real contact.")
        self.assertEqual(report["published_report_source"], "llm")
        self.assertEqual(report["report_llm"]["text"], "A patient AA bat with real contact.")
        self.assertTrue(report["report_llm"]["valid"])
        self.assertTrue(cached)

    def test_attach_llm_reports_regenerates_invalid_cached_entry(self):
        row = SimpleNamespace(
            is_prospect=True, name="X", role="hitter", positions=["OF"], team="MIL",
            level="AA", age=21, prospect_rank=5,
            stat_line={"pa": 240, "avg": 0.300, "obp": 0.380, "slg": 0.520, "ops": 0.900,
                       "iso": 0.220, "k_pct": 18.0, "bb_pct": 10.0},
            stat_line_translated=None, best_single_level_stat_line=None,
            has_peak_projection=False, peak_projection_summary=None,
            availability_context={}, context={},
        )
        report = {"identity_key": "1_hitter", "report": "deterministic read"}
        store = SimpleNamespace(get_all=lambda: [row])
        with tempfile.TemporaryDirectory() as d:
            cache_path = Path(d) / "cache.json"
            cache_path.write_text(
                '{"artifact":"valucast_scouting_llm_cache","entries":{"1_hitter":'
                '{"hash":"will-be-patched","text":"bad","model":"test",'
                '"valid":false,"hard_ok":true,"problems":{"unsupported_numbers":["22.0"]}}}}',
                encoding="utf-8",
            )
            with patch.object(report_generator, "grounding_hash", return_value="will-be-patched"), \
                    patch.object(report_generator, "default_client",
                                 return_value=_FakeClient("A patient AA bat with a .220 ISO.")), \
                    patch.object(repository, "LLM_CACHE_PATH", cache_path):
                res = repository._attach_llm_reports([row], [report], store)

        self.assertEqual(res["reused"], 0)
        self.assertEqual(res["generated"], 1)
        self.assertEqual(report["report_llm"]["text"], "A patient AA bat with a .220 ISO.")


if __name__ == "__main__":
    unittest.main()
