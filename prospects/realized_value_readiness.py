"""Pure readiness audit for prospect realized-value validation."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict


IDENTITY_POLICY = {
    "identity_key": "integer_mlbam_id",
    "cohort_key": "cohort_year:mlbam_id",
    "one_row_per_cohort_identity": True,
    "historical_role": "frozen_from_cohort_cutoff_row",
    "later_role_changes": "disclosed_never_relabels_prior_cohort",
    "same_cohort_role_conflict": "block_affected_cohort",
    "common_pool": "unique_mlbam_identities",
    "role_results": "frozen_cohort_role",
}

_ROLES = ("hitter", "pitcher")


def _identity(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _has_opportunity(
    seasons: dict, cohort_year: int, mlbam_id: int, role: str
) -> bool:
    opportunity_field = "pa" if role == "hitter" else "ip"
    for season in seasons.get(f"{mlbam_id}_{role}") or []:
        year = _identity(season.get("year"))
        try:
            opportunity = float(season.get(opportunity_field) or 0)
        except (TypeError, ValueError):
            opportunity = 0
        if year is not None and cohort_year < year <= cohort_year + 4 and opportunity > 0:
            return True
    return False


def _category_coverage(seasons: dict, impact: dict, role: str) -> dict:
    canonical = list(impact.get(f"canonical_{role}_categories") or [])
    declared_missing = list(impact.get(f"missing_{role}_categories") or [])
    missing_set = set(declared_missing)
    missing = [category for category in canonical if category in missing_set]
    missing.extend(sorted(missing_set - set(canonical)))
    source_fields = {
        category: (["sv", "hld"] if category == "sv_hld" else [category])
        for category in canonical
    }
    role_seasons = [
        season
        for key, values in seasons.items()
        if str(key).endswith(f"_{role}")
        for season in (values or [])
        if isinstance(season, dict)
    ]
    return {
        "canonical": canonical,
        "available": [category for category in canonical if category not in missing_set],
        "missing": missing,
        "complete": bool(canonical) and not missing,
        "source_fields": source_fields,
        "season_rows": len(role_seasons),
        "season_rows_with_category": {
            category: sum(
                all(season.get(field) is not None for field in fields)
                for season in role_seasons
            )
            for category, fields in source_fields.items()
        },
    }


def _content_sha256(payload: dict) -> str:
    body = {key: value for key, value in payload.items() if key != "content_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def audit_realized_value_readiness(contract: dict, model_artifact: dict) -> dict:
    rows = list((contract.get("historical") or {}).get("rows") or [])
    seasons = contract.get("historical_mlb_seasons") or {}
    impact = model_artifact.get("impact_target_contract") or {}

    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    invalid_rows = []
    for index, row in enumerate(rows):
        cohort_year = _identity(row.get("cohort_year"))
        mlbam_id = _identity(row.get("mlbam_id"))
        if cohort_year is None or mlbam_id is None or row.get("role") not in _ROLES:
            invalid_rows.append(index)
            continue
        grouped[(cohort_year, mlbam_id)].append(row)

    duplicates = sorted(
        f"{year}:{mlbam_id}"
        for (year, mlbam_id), identity_rows in grouped.items()
        if len(identity_rows) > 1
    )
    conflicts = sorted(
        f"{year}:{mlbam_id}"
        for (year, mlbam_id), identity_rows in grouped.items()
        if len({row["role"] for row in identity_rows}) > 1
    )

    frozen_roles = {
        key: next(iter(roles))
        for key, identity_rows in grouped.items()
        if len(roles := {row["role"] for row in identity_rows}) == 1
    }
    roles_by_player: dict[int, dict[int, str]] = defaultdict(dict)
    for (cohort_year, mlbam_id), role in frozen_roles.items():
        roles_by_player[mlbam_id][cohort_year] = role
    later_role_changes = [
        {
            "mlbam_id": str(mlbam_id),
            "roles_by_cohort": {
                str(year): role for year, role in sorted(roles_by_cohort.items())
            },
        }
        for mlbam_id, roles_by_cohort in sorted(roles_by_player.items())
        if len(set(roles_by_cohort.values())) > 1
    ]

    cohorts = {}
    for cohort_year in sorted({year for year, _ in grouped}):
        cohort_keys = [key for key in grouped if key[0] == cohort_year]
        cohort_duplicates = [
            key for key in duplicates if key.startswith(f"{cohort_year}:")
        ]
        cohort_conflicts = [
            key for key in conflicts if key.startswith(f"{cohort_year}:")
        ]
        eligible = {role: 0 for role in _ROLES}
        resolved = {role: 0 for role in _ROLES}
        with_opportunity = {role: 0 for role in _ROLES}
        zero_opportunity = {role: 0 for role in _ROLES}
        for key in cohort_keys:
            role = frozen_roles.get(key)
            if role is None:
                continue
            eligible[role] += 1
            if any(row.get("outcome") is not None for row in grouped[key]):
                resolved[role] += 1
            if _has_opportunity(seasons, key[0], key[1], role):
                with_opportunity[role] += 1
            else:
                zero_opportunity[role] += 1
        for counts in (eligible, resolved, with_opportunity, zero_opportunity):
            counts["common_pool"] = sum(counts.values())
        cohorts[str(cohort_year)] = {
            "identity_status": (
                "blocked" if cohort_duplicates or cohort_conflicts else "ready"
            ),
            "eligible": eligible,
            "resolved": resolved,
            "with_opportunity": with_opportunity,
            "zero_opportunity": zero_opportunity,
            "duplicate_cohort_identities": cohort_duplicates,
            "conflicting_cohort_roles": cohort_conflicts,
        }

    category_coverage = {
        "direct_7x7": impact.get("direct_7x7") is True,
        **{
            role: _category_coverage(seasons, impact, role)
            for role in _ROLES
        },
    }
    replay = {
        "historical_cutoff": "cohort_season_completion",
        "intra_season_cutoff_reconstructable": False,
        "retrospective_input_kind": "reconstructed_full_season",
        "exact_prospective_replay_ready": False,
        "partial_category_secondary_ready": (
            not impact.get("missing_hitter_categories")
            and bool(
                set(impact.get("canonical_pitcher_categories") or [])
                - set(impact.get("missing_pitcher_categories") or [])
            )
        ),
        "realized_value_regret_ready": False,
    }

    blockers = [
        f"missing_{role}_category:{category}"
        for role in _ROLES
        for category in category_coverage[role]["missing"]
    ]
    blockers.extend(f"duplicate_cohort_identity:{key}" for key in duplicates)
    blockers.extend(f"conflicting_cohort_roles:{key}" for key in conflicts)
    blockers.extend(f"invalid_historical_row:{index}" for index in invalid_rows)
    if not grouped:
        blockers.append("missing_historical_cohorts")
    if not impact.get("direct_7x7"):
        blockers.append("impact_target_not_direct_7x7")
    if not replay["exact_prospective_replay_ready"]:
        blockers.append("exact_prospective_replay_not_reconstructable")

    report = {
        "schema": "valucast_prospect_realized_value_readiness",
        "status": "blocked" if blockers else "ready",
        "identity_policy": dict(IDENTITY_POLICY),
        "identity_audit": {
            "historical_row_count": len(rows),
            "cohort_identity_count": len(grouped),
            "unique_mlbam_identities": len({mlbam_id for _, mlbam_id in grouped}),
            "invalid_historical_rows": invalid_rows,
            "duplicate_cohort_identities": duplicates,
            "conflicting_cohort_roles": conflicts,
            "later_role_changes": later_role_changes,
        },
        "category_coverage": category_coverage,
        "cohorts": cohorts,
        "replay": replay,
        "blockers": blockers,
    }
    report["content_sha256"] = _content_sha256(report)
    return report
