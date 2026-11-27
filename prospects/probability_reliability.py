"""Predicted-outcome-probability reliability report (audit repair R4).

The existing ``valucast_prospect_calibration_report.json`` is MISNAMED: it
reports board composition, not probability calibration. This module builds the
genuinely missing probability-reliability artifact
(``valucast_probability_reliability.json``) from the committed per-player
outcome-score OOF (R6, ``valucast_outcome_oof_scores.json``).

Per role we bin the OOF rows into equal-count deciles by predicted outcome
score and, per bin, report:
- ``predicted_mean``: mean predicted outcome score in the bin,
- ``realized_mean``: mean realized ordinal outcome tier in the bin,
- ``reached_role_or_better_freq`` with a Wilson 95% interval (binary success =
  realized tier > 0), and
- expected-calibration-error (ECE) per role, count-weighted over bins.

Known truth this must reproduce (else the join is wrong): the served score is
rank-good but probability-NONLINEAR -- the bottom deciles sit near-flat at ~0
realized outcome and resolution is concentrated in the top few deciles.

Research-only. Reads only the factual OOF artifact; stores no consensus or
third-party ranks; never feeds a score, rank, or value.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.outcome_oof import ARTIFACT_PATH as OUTCOME_OOF_PATH
from prospects.outcome_oof import validate_outcome_oof_artifact

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_probability_reliability.json"
SCHEMA_VERSION = "1.0.0"
ROLES = ("hitter", "pitcher")
N_DECILES = 10
WILSON_Z_95 = 1.959963984540054
_TOP_RESOLUTION_DECILES = 3


def _generated_at(value: str | None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def _wilson_interval(successes: int, total: int, z: float = WILSON_Z_95) -> dict:
    if total <= 0:
        return {"low": None, "high": None}
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    half = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return {"low": round(center - half, 6), "high": round(center + half, 6)}


def _role_reliability(rows: list[dict]) -> dict:
    """Equal-count decile reliability for one role's OOF rows."""
    # Deterministic order: predicted score asc, then mlbam_id asc for stable ties.
    ordered = sorted(rows, key=lambda row: (row["model_prediction"], row["mlbam_id"]))
    total = len(ordered)
    bins = []
    ece = 0.0
    for decile in range(N_DECILES):
        start = decile * total // N_DECILES
        stop = (decile + 1) * total // N_DECILES
        chunk = ordered[start:stop]
        if not chunk:
            continue
        count = len(chunk)
        predicted_mean = sum(row["model_prediction"] for row in chunk) / count
        realized_mean = sum(row["target"] for row in chunk) / count
        successes = sum(1 for row in chunk if row["target"] > 0)
        wilson = _wilson_interval(successes, count)
        ece += (count / total) * abs(predicted_mean - realized_mean)
        bins.append(
            {
                "decile": decile + 1,
                "count": count,
                "predicted_score_min": round(chunk[0]["model_prediction"], 6),
                "predicted_score_max": round(chunk[-1]["model_prediction"], 6),
                "predicted_mean": round(predicted_mean, 6),
                "realized_mean": round(realized_mean, 6),
                "reached_role_or_better_freq": round(successes / count, 6),
                "reached_role_or_better_wilson95": wilson,
            }
        )
    # Resolution summary: realized outcome in the bottom deciles vs the top few.
    if len(bins) >= N_DECILES:
        bottom = bins[: N_DECILES - _TOP_RESOLUTION_DECILES]
        top = bins[-_TOP_RESOLUTION_DECILES:]
        bottom_max_realized = max(b["realized_mean"] for b in bottom)
        top_min_realized = min(b["realized_mean"] for b in top)
        resolution = {
            "bottom_deciles": N_DECILES - _TOP_RESOLUTION_DECILES,
            "top_deciles": _TOP_RESOLUTION_DECILES,
            "bottom_max_realized_mean": round(bottom_max_realized, 6),
            "top_min_realized_mean": round(top_min_realized, 6),
            "resolution_concentrated_in_top_deciles": (
                top_min_realized > bottom_max_realized
            ),
        }
    else:
        resolution = None
    return {
        "sample_size": total,
        "n_deciles": N_DECILES,
        "expected_calibration_error": round(ece, 6),
        "bins": bins,
        "resolution": resolution,
    }


DEFAULT_SOURCE_PATH = "data/models/valucast_outcome_oof_scores.json"


def build_probability_reliability(
    oof_payload: dict,
    *,
    oof_sha256: str,
    generated_at: str | None = None,
    source_path: str = DEFAULT_SOURCE_PATH,
) -> dict:
    problems = validate_outcome_oof_artifact(oof_payload)
    if problems:
        raise ValueError("outcome OOF artifact invalid: " + "; ".join(problems))
    rows = oof_payload["rows"]
    roles = {
        role: _role_reliability([row for row in rows if row["role"] == role])
        for role in ROLES
    }
    return {
        "artifact": "valucast_probability_reliability",
        "schema_version": SCHEMA_VERSION,
        "status": "research_only",
        "generated_at": _generated_at(generated_at),
        "source": {
            "artifact": "valucast_outcome_oof_scores",
            "path": source_path,
            "sha256": oof_sha256,
        },
        "method": {
            "binning": "equal_count_deciles_by_predicted_outcome_score",
            "predicted": "model_prediction (out-of-fold ordinal outcome score)",
            "realized": "ordinal outcome tier (bust=0, role=0.5, star=1)",
            "wilson_success": "reached role-or-better (realized tier > 0)",
            "wilson_z": WILSON_Z_95,
            "ece": "count_weighted_mean_abs(predicted_mean - realized_mean)",
        },
        "interpretation": (
            "The served score is rank-good but probability-nonlinear: realized "
            "outcome is near-flat in the bottom deciles and resolution is "
            "concentrated in the top deciles. Reliability, not ranking, is the gap."
        ),
        "roles": roles,
        "policy": {
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "consensus_or_third_party_ranks_used": False,
        },
        "validation": {"problems": []},
    }


def validate_probability_reliability(payload: dict) -> list[str]:
    problems: list[str] = []
    if payload.get("artifact") != "valucast_probability_reliability":
        problems.append("artifact must be valucast_probability_reliability")
    if payload.get("status") != "research_only":
        problems.append("status must be research_only")
    if payload.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version is invalid")
    source_sha = (payload.get("source") or {}).get("sha256")
    if not isinstance(source_sha, str) or len(source_sha) != 64:
        problems.append("source.sha256 must be a 64-character digest")
    policy = payload.get("policy") or {}
    for flag in (
        "feeds_model_score",
        "feeds_public_rank",
        "feeds_buy_score",
        "consensus_or_third_party_ranks_used",
    ):
        if policy.get(flag) is not False:
            problems.append(f"policy.{flag} must be false")
    roles = payload.get("roles") or {}
    if set(roles) != set(ROLES):
        problems.append("roles must contain exactly hitter and pitcher")
        roles = {}
    for role, summary in roles.items():
        bins = summary.get("bins") or []
        if not bins:
            problems.append(f"{role} has no reliability bins")
            continue
        total = summary.get("sample_size")
        if total != sum(b.get("count", 0) for b in bins):
            problems.append(f"{role} sample_size does not match bin counts")
        ece = summary.get("expected_calibration_error")
        if not isinstance(ece, (int, float)) or ece < 0.0:
            problems.append(f"{role} ECE is invalid")
        prev_min = None
        for index, b in enumerate(bins):
            if b.get("decile") != index + 1:
                problems.append(f"{role} bins are not ordered by decile")
            freq = b.get("reached_role_or_better_freq")
            if not isinstance(freq, (int, float)) or not 0.0 <= freq <= 1.0:
                problems.append(f"{role} decile {b.get('decile')} freq is invalid")
            wilson = b.get("reached_role_or_better_wilson95") or {}
            low, high = wilson.get("low"), wilson.get("high")
            if low is None or high is None or low > high:
                problems.append(
                    f"{role} decile {b.get('decile')} Wilson interval is invalid"
                )
            # deciles are equal-count and ordered by predicted score, so each
            # bin's predicted-score floor must not fall below the previous bin's.
            floor = b.get("predicted_score_min")
            if prev_min is not None and floor is not None and floor < prev_min:
                problems.append(f"{role} decile ordering broke predicted-score sort")
            prev_min = floor
    return problems


def run_probability_reliability(
    *,
    oof_path: Path = OUTCOME_OOF_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    generated_at: str | None = None,
) -> dict:
    oof_bytes = oof_path.read_bytes()
    oof_payload = json.loads(oof_bytes)
    payload = build_probability_reliability(
        oof_payload,
        oof_sha256=hashlib.sha256(oof_bytes).hexdigest(),
        generated_at=generated_at,
    )
    problems = validate_probability_reliability(payload)
    if problems:
        raise ValueError("; ".join(problems))
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "roles": {
            role: {
                "sample_size": summary["sample_size"],
                "ece": summary["expected_calibration_error"],
            }
            for role, summary in payload["roles"].items()
        },
    }
