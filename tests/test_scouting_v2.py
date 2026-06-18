"""Scouting V2: voice guard + LLM writer (no real API calls — fake client only)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scouting import report_generator, repository
from scouting.voice import (
    VOICE_PROMPT,
    banned_phrase_hits,
    handedness_problems,
    unsupported_numbers,
    validate_report_text,
)

GROUNDING = {
    "name": "Test Prospect", "role": "hitter", "level": "AA", "age": 21,
    "current_minor_league_line": {"avg": 0.300, "obp": 0.380, "slg": 0.520, "ops": 0.900,
                                  "iso": 0.220, "k_pct": 18.0, "bb_pct": 11.0, "pa": 240},
    "current_skill_percentiles": {"ops": 96, "iso": 92, "k_pct": 70},
}


class TestVoiceGuard(unittest.TestCase):
    def test_banned_phrases_flagged(self):
        self.assertIn("tantalizing", banned_phrase_hits("A tantalizing bat."))
        self.assertIn("most accurate", banned_phrase_hits("the MOST ACCURATE read"))
        self.assertEqual(banned_phrase_hits("A direct, plain read."), [])

    def test_supported_numbers_pass(self):
        # cites the line + an ordinal percentile, all present in grounding
        text = "A .300/.380/.520 line over 240 PA, with a 96th-percentile OPS at age 21."
        self.assertEqual(unsupported_numbers(text, GROUNDING), [])

    def test_invented_number_flagged(self):
        text = "Sits 97 mph with the fastball."   # 97 is nowhere in the grounding
        self.assertIn("97", unsupported_numbers(text, GROUNDING))

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
            "current_minor_league_line": {"ip": 47.3, "k_per_9": 12.6, "bb_per_9": 5.3},
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
            "current_minor_league_line": {"ip": 47.3, "k_per_9": 12.6, "bb_per_9": 5.3},
        }

        result = validate_report_text("A right-hander with a 12.6 K/9 over 47.3 IP.", pitcher_grounding)

        self.assertFalse(result["hard_ok"])
        self.assertIn("missing", result["handedness_problems"][0])


class _FakeMessages:
    def __init__(self, text):
        self.text = text
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


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
        self.assertIn("current_minor_league_line", prompt)

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


if __name__ == "__main__":
    unittest.main()
