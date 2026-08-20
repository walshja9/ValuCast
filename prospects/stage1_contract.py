"""Validated boundary between prospect outcome artifacts and fantasy ranking."""
from copy import deepcopy
from datetime import datetime

CONTRACT_VERSION = "1.0.0"
LINEAGE_CONTRACTS = {
    "incumbent": {
        "model_version": "0.6.1",
        "model_consumer": "prospect_rank_v1",
        "layer_consumer": "prospect_rank_v1",
        "score_source": "prospect_model_v0_6",
        "model_feed": True,
        "layer_feed": True,
    },
    "candidate": {
        "model_version": "0.8.0",
        "model_consumer": "prospect_rank_v2",
        "layer_consumer": "prospect_rank_v2",
        "score_source": "prospect_model_v0_8",
        "model_feed": False,
        "layer_feed": False,
    },
    "promoted": {
        "model_version": "0.8.0",
        "model_consumer": "prospect_rank_v2",
        "layer_consumer": "prospect_rank_v2",
        "score_source": "prospect_model_v0_8",
        "model_feed": False,
        "layer_feed": True,
    },
}
ROLES = frozenset({"hitter", "pitcher"})


def _date(value: object) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _index(rows: list[dict], label: str) -> dict[tuple[str, str], dict]:
    out = {}
    for row in rows:
        role = str(row.get("role") or "")
        mlbam_id = row.get("mlbam_id")
        if role not in ROLES:
            raise ValueError(f"Stage 1 {label} profile has invalid role")
        if isinstance(mlbam_id, bool) or not str(mlbam_id or "").isdigit():
            raise ValueError(f"Stage 1 {label} profile has invalid MLBAM identity")
        key = (str(mlbam_id), role)
        if key in out:
            raise ValueError(f"Stage 1 {label} profile has duplicate identity {key}")
        out[key] = deepcopy(row)
    return out


def build_stage1_contract(
    prospect_model: dict,
    dynasty_layer: dict,
    expected_generated_at: str,
    *,
    state: str = "incumbent",
    expected_model_version: str = "0.6.1",
    expected_model_consumer: str = "prospect_rank_v1",
    expected_layer_consumer: str = "prospect_rank_v1",
    expected_score_source: str = "prospect_model_v0_6",
    expected_model_feed: bool = True,
    expected_layer_feed: bool = True,
) -> dict:
    registered = LINEAGE_CONTRACTS.get(state)
    requested = {
        "model_version": expected_model_version,
        "model_consumer": expected_model_consumer,
        "layer_consumer": expected_layer_consumer,
        "score_source": expected_score_source,
        "model_feed": expected_model_feed,
        "layer_feed": expected_layer_feed,
    }
    if registered is None or requested != registered:
        raise ValueError(f"Stage 1 state or lineage contract is invalid for {state!r}")

    model_release = prospect_model.get("release_contract") or {}
    layer_release = dynasty_layer.get("release_contract") or {}
    if (
        prospect_model.get("model_version") != expected_model_version
        or model_release.get("consumer") != expected_model_consumer
        or model_release.get("feeds_live_valucast_rank") is not expected_model_feed
    ):
        raise ValueError("Stage 1 model artifact is not authorized: wrong version, consumer, or feed")
    artifact_source = model_release.get("score_source")
    if expected_score_source == "prospect_model_v0_8":
        if artifact_source != expected_score_source or any(
            row.get("score_source") != expected_score_source
            for row in prospect_model.get("ranked") or []
        ):
            raise ValueError("Stage 1 v0.8 source is missing or mixed")
    elif artifact_source not in (None, expected_score_source):
        raise ValueError("Stage 1 legacy model claims the wrong score source")
    if (
        layer_release.get("consumer") != expected_layer_consumer
        or layer_release.get("feeds_live_valucast_rank") is not expected_layer_feed
    ):
        raise ValueError("Stage 1 layer artifact is not authorized: wrong consumer or feed")
    expected_date = _date(expected_generated_at)
    model_date = _date((prospect_model.get("input_contract") or {}).get("generated_at"))
    layer_date = _date(dynasty_layer.get("generated_at"))
    if not expected_date or {model_date, layer_date} != {expected_date}:
        raise ValueError("Stage 1 artifacts do not match the expected generated date")
    models = _index(prospect_model.get("ranked") or [], "model")
    outcomes = _index(dynasty_layer.get("profiles") or [], "outcome")
    profiles = {
        key: {
            "mlbam_id": key[0],
            "role": key[1],
            "model_profile": models.get(key),
            "outcome_profile": outcomes.get(key),
        }
        for key in sorted(models.keys() | outcomes.keys())
    }
    return {
        "contract_version": CONTRACT_VERSION,
        "state": state,
        "generated_date": expected_date,
        "model_version": prospect_model.get("model_version"),
        "model_consumer": expected_model_consumer,
        "layer_consumer": expected_layer_consumer,
        "score_source": expected_score_source,
        "layer_version": dynasty_layer.get("layer_version"),
        "profiles_by_key": profiles,
    }
