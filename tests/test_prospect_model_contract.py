import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _documented_contract() -> dict:
    text = (ROOT / "docs/prospect-model.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- prospect-model-contract:start -->\s*```json\s*(\{.*?\})\s*```\s*"
        r"<!-- prospect-model-contract:end -->",
        text,
        flags=re.S,
    )
    assert match, "machine-readable prospect model contract is missing"
    return json.loads(match.group(1))


def test_documented_contract_matches_live_artifacts():
    documented = _documented_contract()
    model = _load(documented["live_model_artifact"])
    rank = _load(documented["live_rank_artifact"])
    preview = _load(documented["v0_7_artifact"])

    assert documented["model_score_consumed_by_live_rank"] is True
    assert model["release_contract"]["feeds_live_valucast_rank"] is True
    assert model["release_contract"]["consumer"] == "prospect_rank_v1"
    assert model["release_contract"]["model_score_weight"] == 0.76
    assert model["release_contract"]["standalone_public_board"] is False
    assert not any(
        "never consumed by the live prospect board" in limitation
        for limitation in model["limitations"]
    )
    assert any(
        "full-store percentile references" in limitation
        and "fold-local replay" in limitation
        for limitation in model["limitations"]
    )
    assert rank["promotion"]["feeds_live_valucast_rank"] is True
    assert (
        rank["rank_contract"]["score_weights"]["prospect_model_v0_6"]["model_score"]
        == documented["live_model_score_weight"]
        == 0.76
    )
    impact = model["impact_target_contract"]
    assert impact["kind"] == documented["impact_target_kind"]
    assert impact["direct_7x7"] is documented["impact_target_direct_7x7"] is False
    assert impact["missing_pitcher_categories"] == documented["missing_pitcher_categories"] == ["qs"]
    assert preview["status"] == documented["v0_7_status"] == "shadow_preview"
    assert preview["model_contract"]["feeds_live_valucast_rank"] is False
    assert preview["model_contract"]["purpose"] == documented["v0_7_purpose"]
