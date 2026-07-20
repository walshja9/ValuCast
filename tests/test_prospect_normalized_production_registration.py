import json
import re
from pathlib import Path

from prospects import challenger_eval
from prospects.realized_value_readiness import IDENTITY_POLICY


ROOT = Path(__file__).resolve().parents[1]


def _registration() -> dict:
    text = (ROOT / "plans/033-prospect-normalized-production-gate.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- normalized-production-registration:start -->\s*```json\s*(\{.*?\})\s*```\s*"
        r"<!-- normalized-production-registration:end -->",
        text,
        flags=re.S,
    )
    assert match
    return json.loads(match.group(1))


def test_registration_matches_code_and_cannot_authorize_a_public_claim():
    registration = _registration()
    assert registration["seed"] == challenger_eval.REGISTERED_SEED == 33021
    assert set(registration["forbidden_seeds"]) == challenger_eval.FORBIDDEN_SEEDS
    assert registration["same_level_min_other_peers"] == challenger_eval.SAME_LEVEL_MIN_PEERS == 25
    assert registration["role_season_min_other_peers"] == challenger_eval.ROLE_SEASON_MIN_PEERS == 250
    assert registration["minimum_exercised_coverage"] == challenger_eval.MIN_EXERCISED_COVERAGE == .90
    assert registration["public_claim_eligible"] is False
    assert registration["future_public_primary"] == "realized_value_regret"
    assert registration["research_primary"] == "ordinal_percentile_rank_mae"
    assert registration["hitters_and_pitchers_separate"] is True
    assert registration["v0_7_baseline"] == "excluded_unstable_prediction_contract"
    assert registration["combined_promotion_variant"] == "unavailable_until_prospective_archive_matures"
    assert registration["identity_policy"] == IDENTITY_POLICY
    assert registration["realized_value_readiness"]["required_ready"] is False
