"""Validated boundary between prospect outcome artifacts and fantasy ranking."""
from copy import deepcopy
from datetime import datetime

CONTRACT_VERSION = "1.0.0"
SERVED_STATES = frozenset({"incumbent", "promoted"})
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
) -> dict:
    if state not in SERVED_STATES:
        raise ValueError(f"Stage 1 state is not served: {state}")
    for label, payload in (("model", prospect_model), ("layer", dynasty_layer)):
        release = payload.get("release_contract") or {}
        if release.get("consumer") != "prospect_rank_v1" or release.get("feeds_live_valucast_rank") is not True:
            raise ValueError(f"Stage 1 {label} artifact is not authorized for Rank v1")
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
        "layer_version": dynasty_layer.get("layer_version"),
        "profiles_by_key": profiles,
    }
