"""Promotion sanity report for the ValuCast H+P projection run.

This report is deliberately not a model. It is the small, explicit bridge
between "the ValuCast H+P run exists and is valid" and "make it the default
projection-board source." The public dynasty layer may already consume the run;
the redraft projection board should only flip defaults after this report says
the run is structurally sound and a human explicitly chooses promotion.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN_PATH = ROOT / "projections" / "runs" / "valucast_hp_2026_v1" / "projections.json"
MANIFEST_PATH = ROOT / "projections" / "runs" / "valucast_hp_2026_v1" / "run_manifest.json"
SCORECARD_PATH = ROOT / "data" / "validation" / "methodology_scorecard.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_hp_promotion_sanity_report.json"

ARTIFACT_NAME = "valucast_hp_promotion_sanity_report"
REPORT_VERSION = "0.1.0"
REQUIRED_POOLS = {"hitter", "pitcher"}
PITCHER_POOLS = {"pitcher", "starter", "reliever"}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _pool_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        pool = str(row.get("pool") or "").lower()
        counts[pool] = counts.get(pool, 0) + 1
    return counts


def _mlbam_id(row: dict) -> str | None:
    metadata = row.get("metadata") or {}
    value = metadata.get("mlbam_id")
    if value in (None, ""):
        return None
    return str(value)


def _identity_key(row: dict) -> tuple[str, str] | None:
    mlbam_id = _mlbam_id(row)
    pool = str(row.get("pool") or "").lower()
    if not mlbam_id or not pool:
        return None
    return mlbam_id, pool


def _gate(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def build_promotion_sanity_report(
    *,
    projections: list[dict],
    manifest: dict,
    scorecard: dict | None = None,
    generated_at: str | None = None,
    default_source: str = "steamer",
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    pool_counts = _pool_counts(projections)
    has_hitters = pool_counts.get("hitter", 0) > 0
    pitcher_count = sum(pool_counts.get(pool, 0) for pool in PITCHER_POOLS)
    has_pitchers = pitcher_count > 0
    identity_keys = [key for row in projections if (key := _identity_key(row))]
    duplicate_identity_count = len(identity_keys) - len(set(identity_keys))
    manifest_hitter_count = int(manifest.get("hitter_count") or 0)
    manifest_pitcher_count = int(manifest.get("pitcher_count") or 0)
    copied_stats_claim = "NO projection stats copied" in str(
        manifest.get("eligibility_source") or ""
    )
    scorecard_present = bool(scorecard and scorecard.get("version"))

    gates = [
        _gate(
            "both_pools_present",
            has_hitters and has_pitchers,
            f"hitters={pool_counts.get('hitter', 0)} pitchers={pitcher_count}",
        ),
        _gate(
            "manifest_counts_match_run",
            manifest_hitter_count == pool_counts.get("hitter", 0)
            and manifest_pitcher_count == pitcher_count,
            f"manifest hitters={manifest_hitter_count} pitchers={manifest_pitcher_count}",
        ),
        _gate(
            "source_named_valucast",
            manifest.get("source_name") == "valucast",
            f"source_name={manifest.get('source_name')}",
        ),
        _gate(
            "identity_keys_unique",
            duplicate_identity_count == 0,
            f"duplicate_mlbam_count={duplicate_identity_count}",
        ),
        _gate(
            "eligibility_stats_not_copied",
            copied_stats_claim,
            str(manifest.get("eligibility_source") or ""),
        ),
        _gate(
            "methodology_scorecard_present",
            scorecard_present,
            f"version={(scorecard or {}).get('version')}",
        ),
        _gate(
            "default_source_not_silently_flipped",
            default_source == "steamer",
            f"default_source={default_source}",
        ),
    ]
    blockers = [gate["name"] for gate in gates if not gate["passed"]]
    ready_for_opt_in = not blockers

    return {
        "artifact": ARTIFACT_NAME,
        "report_version": REPORT_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "run": {
            "run_id": manifest.get("run_id"),
            "source_name": manifest.get("source_name"),
            "as_of_season": manifest.get("as_of_season"),
            "projection_count": len(projections),
            "pool_counts": pool_counts,
            "hitter_count": pool_counts.get("hitter", 0),
            "pitcher_count": pitcher_count,
            "manifest_hitter_count": manifest_hitter_count,
            "manifest_pitcher_count": manifest_pitcher_count,
        },
        "promotion": {
            "default_source": default_source,
            "redraft_board_default": default_source,
            "status": "opt_in_ready" if ready_for_opt_in else "blocked",
            "ready_for_opt_in_source": ready_for_opt_in,
            "ready_for_default_promotion": False,
            "human_approval_required_for_default": True,
            "recommended_next_step": (
                "Keep Steamer as the default redraft source until H+P is "
                "intentionally promoted after human review."
            ),
        },
        "track_record": {
            "scorecard_present": scorecard_present,
            "scorecard_version": (scorecard or {}).get("version"),
            "scorecard_generated_at": (scorecard or {}).get("generated_at"),
            "hitting_baseline": ((scorecard or {}).get("hitting") or {}).get("baseline"),
            "pitching_baseline": ((scorecard or {}).get("pitching") or {}).get("baseline"),
        },
        "source_policy": {
            "kind": "valucast_hp_promotion_sanity",
            "dd_values_used": False,
            "dd_ranks_used": False,
            "public_rankings_used": False,
            "market_values_used": False,
            "external_projection_stats_copied": False,
            "external_projection_universe_metadata_used": True,
        },
        "gates": gates,
        "validation": {
            "ready_for_opt_in_source": ready_for_opt_in,
            "ready_for_default_promotion": False,
            "duplicate_identity_count": duplicate_identity_count,
            "blockers": blockers,
        },
    }


def run_promotion_sanity_report(
    *,
    run_path: Path = RUN_PATH,
    manifest_path: Path = MANIFEST_PATH,
    scorecard_path: Path = SCORECARD_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    default_source: str = "steamer",
) -> dict:
    projections = _load_json(run_path)
    manifest = _load_json(manifest_path)
    scorecard = _load_json(scorecard_path) if scorecard_path.exists() else None
    payload = build_promotion_sanity_report(
        projections=projections,
        manifest=manifest,
        scorecard=scorecard,
        default_source=default_source,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "ready_for_opt_in_source": payload["validation"]["ready_for_opt_in_source"],
        "ready_for_default_promotion": payload["validation"]["ready_for_default_promotion"],
        "projection_count": payload["run"]["projection_count"],
    }
