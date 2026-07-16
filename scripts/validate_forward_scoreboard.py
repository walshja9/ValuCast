"""Validate the forward-ledger scoreboard artifact (plan 030, S2).

Standalone validator (mirrors validate_gaps_claim_ledger.py): reads the committed
scoreboard, hard-asserts the registered invariants, and exits non-zero on any
problem. The load-bearing checks:

  1. QUARANTINE — no `role`, `pitcher`, `hitter`, or `source_ranks` key appears
     ANYWHERE in the artifact (recursive scan). The one-look protocol (plan 028)
     forbids a role field / pitcher-hitter split on a standings surface, and this
     is a public repo so no per-source rank may leak. Claim-SIDE keys
     (higher / lower) are the claim direction, not player role, and are allowed.
  2. Every headline number carries its matching CI / null / provisional field, and
     every numeric headline value is finite.
  3. The funnel totals reconcile with the ledger's claim count (no survivorship).
  4. The independence attestation string is present verbatim.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.forward_scoreboard import (  # noqa: E402
    ARTIFACT_NAME,
    INDEPENDENCE_ATTESTATION,
    PROTOCOL_VERSION,
)

DEFAULT_PATH = ROOT / "data" / "models" / "valucast_forward_scoreboard.json"

# Keys that must NEVER appear anywhere in a standings artifact (exact key match).
# `role`/`pitcher`/`hitter` = the one-look quarantine; `source_ranks` = the per-source
# container. The known public source NAMES are additionally forbidden as dict keys
# (defense-in-depth): even if a per-source rank ever leaked under a container renamed
# away from `source_ranks`, a `{"pl": 98}`-style leak is caught by the key name itself.
KNOWN_PUBLIC_SOURCE_KEYS = frozenset({"pl", "hkb", "sts", "pipeline", "fg_ord"})
FORBIDDEN_KEYS = frozenset(
    {"role", "pitcher", "hitter", "source_ranks"} | KNOWN_PUBLIC_SOURCE_KEYS
)


def _forbidden_key_paths(obj, path: str = "root") -> list[str]:
    """Every location where a FORBIDDEN key appears, recursively."""
    hits: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in FORBIDDEN_KEYS:
                hits.append(f"{path}.{key}")
            hits.extend(_forbidden_key_paths(value, f"{path}.{key}"))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            hits.extend(_forbidden_key_paths(value, f"{path}[{i}]"))
    return hits


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_forward_scoreboard(path: Path = DEFAULT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]
    problems: list[str] = []

    if payload.get("artifact") != ARTIFACT_NAME:
        problems.append(f"artifact must be {ARTIFACT_NAME}")
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        problems.append(f"protocol_version must be {PROTOCOL_VERSION}")

    # 1. Quarantine — no role / pitcher / hitter / source_ranks key anywhere.
    for hit in _forbidden_key_paths(payload):
        problems.append(f"forbidden key at {hit} (role/pitcher/hitter/source_ranks quarantine)")

    # 4. Independence attestation present verbatim.
    if payload.get("independence_attestation") != INDEPENDENCE_ATTESTATION:
        problems.append("independence_attestation missing or altered")

    # 2. Headline shape: median + ci + null + provisional, every number finite.
    headline = payload.get("anticipation_score")
    if not isinstance(headline, dict):
        problems.append("anticipation_score must be an object")
    else:
        for field in ("median_lead_days", "ci_low", "ci_high", "null", "provisional", "pool_size"):
            if field not in headline:
                problems.append(f"anticipation_score missing {field}")
        if not isinstance(headline.get("provisional"), bool):
            problems.append("anticipation_score.provisional must be a boolean")
        # An empty pool nulls the numeric fields (allowed); a non-empty pool must
        # carry finite median + CI bounds.
        if headline.get("pool_size"):
            for field in ("median_lead_days", "ci_low", "ci_high"):
                if not _is_finite_number(headline.get(field)):
                    problems.append(f"anticipation_score.{field} must be a finite number")
            null = headline.get("null")
            if not isinstance(null, dict):
                problems.append("anticipation_score.null must be an object for a non-empty pool")
            else:
                # null_median + the null CI interval are published as context; NO
                # p_value is emitted (degenerate for low-magnitude-variance pools).
                for field in ("null_median", "null_ci_low", "null_ci_high"):
                    if not _is_finite_number(null.get(field)):
                        problems.append(f"anticipation_score.null.{field} must be a finite number")
                if "p_value" in null:
                    problems.append("anticipation_score.null must NOT carry a p_value (removed pre-freeze)")

    # 3. Funnel totals reconcile with the ledger's claim count.
    funnel = payload.get("funnel")
    if not isinstance(funnel, dict):
        problems.append("funnel must be an object")
    else:
        total = funnel.get("total_claims")
        buckets = funnel.get("buckets")
        if not isinstance(buckets, dict):
            problems.append("funnel.buckets must be an object")
        elif total != sum(buckets.values()):
            problems.append(
                f"funnel.buckets sum ({sum(buckets.values())}) != total_claims ({total})"
            )
        # The four published derived views must PARTITION every claim: no bucket
        # belongs to no view (unscored/undatable/unclassified claims are their own
        # view, never silently dropped from the reconciliation).
        derived_views = ("wins", "losses", "excluded_from_pool", "unscored_or_unclassified")
        for view in derived_views:
            if not isinstance(funnel.get(view), int):
                problems.append(f"funnel.{view} must be an integer count")
        if all(isinstance(funnel.get(v), int) for v in derived_views):
            derived_total = sum(funnel[v] for v in derived_views)
            if derived_total != total:
                problems.append(
                    f"funnel derived views (wins+losses+excluded+unscored_or_unclassified="
                    f"{derived_total}) != total_claims ({total})"
                )
        by_side = funnel.get("by_side")
        if not isinstance(by_side, dict):
            problems.append("funnel.by_side must be an object")
        else:
            side_total = sum(
                v for side in by_side.values() if isinstance(side, dict) for v in side.values()
            )
            # Every claim carries a side, so the side buckets must sum to the total.
            if side_total != total:
                problems.append(
                    f"funnel.by_side sum ({side_total}) != total_claims ({total})"
                )
        retraction = funnel.get("self_retraction_rate")
        if not isinstance(retraction, dict) or "rate" not in retraction:
            problems.append("funnel.self_retraction_rate missing rate")

    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    payload, problems = validate_forward_scoreboard(args.path)
    if problems:
        print(f"FORWARD SCOREBOARD VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    assert payload is not None
    headline = payload["anticipation_score"]
    funnel = payload["funnel"]
    print(
        "forward scoreboard: "
        f"pool={headline['pool_size']} median={headline['median_lead_days']} "
        f"provisional={headline['provisional']} total_claims={funnel['total_claims']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
