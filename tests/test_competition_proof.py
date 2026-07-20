from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import subprocess
import unicodedata

import pytest

import scripts.build_competition_benchmark as competition_script
from prospects.competition_benchmark import (
    MINIMUM_INDUSTRY_CLAIM_PLAYERS,
    _claim_decision,
    append_cohort,
    build_cohort,
    build_track,
)
from scripts.build_competition_benchmark import (
    PRIVATE_ARTIFACT_PATH,
    PRIVATE_SOURCES_PATH,
    PUBLIC_ARTIFACT_PATH,
    build_artifact,
    build_public_artifact,
    validate_public_artifact,
)


CRITERIA = {
    "primary_metric": "ordinal_rank_error",
    "minimum_cohorts": 3,
    "minimum_unique_players": 150,
    "minimum_outcome_coverage": 0.90,
    "minimum_relative_improvement_pct": 5.0,
    "maximum_single_cohort_regression_pct": 5.0,
    "maximum_segment_regression_pct": 5.0,
    "top_k": 10,
    "bootstrap_seed": 32019,
    "bootstrap_resamples": 1_000,
}


_REPO_ROOT = Path(__file__).resolve().parents[1]
_RESEARCH_ALLOWLIST = {
    Path("prospects/competition_benchmark.py"),
    Path("scripts/build_competition_benchmark.py"),
}
_PRODUCTION_ROOTS = (
    "prospects/",
    "quality/",
    "src/",
    "mlb/",
    "web/",
    "scripts/",
    ".github/workflows/",
)
_PRODUCTION_EXTENSIONS = {
    ".py",
    ".ps1",
    ".sh",
    ".yml",
    ".yaml",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".html",
}
_NONPRODUCTION_DIRECTORIES = {"tests", "test", "docs", "plans", "__pycache__"}
_PRODUCTION_SENTINELS = {
    Path("app.py"),
    Path("src/league_values/engine.py"),
    Path("mlb/playing_time_role.py"),
    Path("prospects/rank_v1.py"),
    Path("prospects/shadow_promotion.py"),
    Path("quality/valucast_governor.py"),
    Path("scripts/build_public_dynasty_snapshot.py"),
    Path("scripts/run_daily_public_build.py"),
    Path("scripts/deploy.ps1"),
    Path(".github/workflows/daily-public-data.yml"),
}
_FORBIDDEN_PRODUCTION_REFERENCES = (
    "competition_benchmark",
    "competition_benchmark_sources",
    "valucast_competition_evidence",
    "data/private/competition",
    "data/models/valucast_competition_benchmark.json",
)


def _normalized_reference(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().replace("\\", "/")


def _constant_string(node: ast.AST, names: dict[str, str] | None = None) -> str | None:
    names = names or {}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string(node.left, names)
        right = _constant_string(node.right, names)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        values = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                if value.conversion not in (-1, ord("s")) or value.format_spec:
                    return None
                resolved = _constant_string(value.value, names)
            else:
                resolved = _constant_string(value, names)
            if resolved is None:
                return None
            values.append(resolved)
        return "".join(values)
    return None


def _constant_names(tree: ast.AST) -> dict[str, str]:
    assignments: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            assignments.setdefault(node.target.id, []).append(node.value)

    resolved: dict[str, str] = {}
    pending = dict(assignments)
    while pending:
        changed = False
        for name, values in list(pending.items()):
            candidates = [_constant_string(value, resolved) for value in values]
            if all(candidate is not None for candidate in candidates) and len(
                set(candidates)
            ) == 1:
                candidate = candidates[0]
                assert candidate is not None
                resolved[name] = candidate
                del pending[name]
                changed = True
        if not changed:
            break
    return resolved


def _competition_references(path: Path, body: str) -> set[str]:
    candidates = []
    if path.suffix == ".py":
        tree = ast.parse(body, filename=str(path))
        names = _constant_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                candidates.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                candidates.extend(
                    f"{module}.{alias.name}" if module else alias.name
                    for alias in node.names
                )
            value = _constant_string(node, names)
            if value is not None:
                candidates.append(value)
    else:
        candidates.append(body)
    normalized = [_normalized_reference(value) for value in candidates]
    return {
        forbidden
        for forbidden in _FORBIDDEN_PRODUCTION_REFERENCES
        if any(_normalized_reference(forbidden) in value for value in normalized)
    }


def _production_paths() -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
        )
        tracked = result.stdout.decode("utf-8").split("\0")
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError) as exc:
        raise AssertionError("git tracked-file enumeration failed") from exc
    if not any(tracked):
        raise AssertionError("git tracked-file enumeration returned no files")

    paths = set()
    for value in tracked:
        if not value:
            continue
        path = Path(value)
        normalized = path.as_posix()
        in_production = path == Path("app.py") or any(
            normalized.startswith(root) for root in _PRODUCTION_ROOTS
        )
        if (
            in_production
            and path.suffix.casefold() in _PRODUCTION_EXTENSIONS
            and not (
                _NONPRODUCTION_DIRECTORIES
                & {part.casefold() for part in path.parts}
            )
        ):
            paths.add(path)
    return sorted(paths - _RESEARCH_ALLOWLIST)


def test_production_model_paths_do_not_import_competition_evidence():
    production_paths = _production_paths()
    assert _PRODUCTION_SENTINELS.issubset(production_paths)
    for path in production_paths:
        body = (_REPO_ROOT / path).read_text(encoding="utf-8")
        assert not _competition_references(path, body), path


def test_production_path_inventory_includes_engine_and_deploy_entrypoints():
    assert {
        Path("src/league_values/engine.py"),
        Path("scripts/deploy.ps1"),
    }.issubset(_production_paths())


def test_production_path_inventory_fails_closed_when_git_fails(monkeypatch):
    def fail(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "git ls-files")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(AssertionError, match="tracked-file enumeration"):
        _production_paths()


@pytest.mark.parametrize(
    "body",
    (
        "import prospects.competition_benchmark",
        'import importlib\nimportlib.import_module("prospects." + "competition_benchmark")',
        'PRIVATE = "data/private/competition/benchmark.json"',
        'PUBLIC = "data/validation/" + "valucast_competition_evidence.json"',
        (
            'import importlib\nleft = "competition"\nright = "_benchmark"\n'
            'importlib.import_module("prospects." + left + right)'
        ),
    ),
)
def test_competition_reference_scan_rejects_import_and_artifact_bypasses(body):
    assert _competition_references(Path("adversarial_fixture.py"), body)


def test_historical_replay_docs_keep_the_91_player_result_collecting():
    paths = (
        Path("plans/032-competition-proof-lane.md"),
        Path("plans/README.md"),
        Path(
            "docs/superpowers/specs/"
            "2026-07-19-competition-historical-replay-design.md"
        ),
        Path(
            "docs/superpowers/plans/"
            "2026-07-19-competition-proof-lane.md"
        ),
    )
    for path in paths:
        body = path.read_text(encoding="utf-8")
        relevant = " ".join(
            paragraph for paragraph in body.split("\n\n") if "91" in paragraph
        ).casefold()
        assert "collecting" in relevant, path
        assert "research_only" in relevant, path
        assert "150" in relevant or "underpowered" in relevant, path
        assert "no_significant_difference" not in relevant, path
        assert "no significant difference" not in relevant, path


def test_competition_docs_describe_the_hierarchical_bootstrap():
    paths = (
        Path("plans/032-competition-proof-lane.md"),
        Path(
            "docs/superpowers/specs/"
            "2026-07-19-competition-historical-replay-design.md"
        ),
        Path(
            "docs/superpowers/plans/"
            "2026-07-19-competition-proof-lane.md"
        ),
    )
    stale = (
        "paired player bootstrap",
        "paired player-level bootstrap",
        "paired 95% bootstrap intervals",
    )
    required = (
        "paired hierarchical bootstrap",
        "resamples completed cohorts first",
        "matched players within each sampled cohort",
    )
    for path in paths:
        body = path.read_text(encoding="utf-8").casefold()
        assert all(value not in body for value in stale), path
        assert all(value in body for value in required), path


def _private_artifact(*, authorized: bool) -> dict:
    cohort_ids = ["private-cohort-canary", "private-cohort-two", "private-cohort-three"]
    return {
        "artifact": "valucast_competition_benchmark",
        "protocol_version": "proof-v1",
        "generated_at": "2026-07-19",
        "tracks": {
            "private-track-canary": {
                "competitor": "PRIVATE SOURCE CANARY",
                "public_source_class": "leading_public_prospect_boards",
                "public_task": "four-year prospect-selection regret",
                "cohorts": [{"cohort_id": cohort_id} for cohort_id in cohort_ids],
                "evaluation": {
                    "status": (
                        "validated_superiority" if authorized else "collecting"
                    ),
                    "statistical_status": (
                        "validated_superiority" if authorized else "collecting"
                    ),
                    "claim_authorized": authorized,
                    "coverage": {
                        "registered": 150,
                        "resolved": 150,
                        "rate": 1.0,
                        "completed_cohorts": 3,
                        "unique_players": 150,
                    },
                    "criteria": CRITERIA
                    | {"primary_metric": "realized_value_regret"},
                    "primary": {
                        "metric": "realized_value_regret",
                        "valucast_error": 0.20,
                        "competitor_error": 0.25,
                        "competitor_minus_valucast_error": 0.05,
                        "relative_improvement_pct": 20.0,
                        "error_delta_ci_low": 0.01,
                        "error_delta_ci_high": 0.09,
                    },
                    "confirmers": {
                        "valucast_top_k_regret": 1.0,
                        "competitor_top_k_regret": 2.0,
                    },
                    "segments": [
                        {
                            "role": role,
                            "resolved": 75,
                            "valucast_error": 0.20,
                            "competitor_error": 0.25,
                            "regression_pct": -20.0,
                        }
                        for role in ("hitter", "pitcher")
                    ],
                    "cohorts": [
                        {
                            "cohort_id": cohort_id,
                            "registered": 50,
                            "resolved": 50,
                            "coverage": 1.0,
                            "valucast_error": 0.20,
                            "competitor_error": 0.25,
                            "regression_pct": -20.0,
                        }
                        for cohort_id in cohort_ids
                    ],
                },
            }
        },
    }


def test_public_artifact_is_empty_until_a_claim_is_authorized():
    public = build_public_artifact(
        _private_artifact(authorized=False),
        forbidden_identifiers=["PRIVATE SOURCE CANARY"],
    )
    assert public["results"] == []
    assert public["validation"]["public_claim_count"] == 0


def test_public_artifact_anonymizes_authorized_aggregate_evidence():
    forbidden = [
        "PRIVATE SOURCE CANARY",
        "private-track-canary",
        "private-cohort-canary",
    ]
    public = build_public_artifact(
        _private_artifact(authorized=True),
        forbidden_identifiers=forbidden,
    )
    body = json.dumps(public).casefold()
    assert all(value.casefold() not in body for value in forbidden)
    assert public["results"][0]["benchmark_class"] == (
        "leading_public_prospect_boards"
    )
    assert public["results"][0]["cohorts"][0]["cohort_number"] == 1
    assert "baseline_error" in public["results"][0]["primary"]


def test_public_validator_fails_closed_on_private_identity():
    with pytest.raises(ValueError, match="private identity leak"):
        validate_public_artifact(
            {"results": [{"label": "PRIVATE SOURCE CANARY"}]},
            ["PRIVATE SOURCE CANARY"],
        )


@pytest.mark.parametrize(
    ("identifier", "payload"),
    (
        (
            'PRIVATE "CANARY"',
            {"results": [{'private "canary"': "safe"}]},
        ),
        (
            "PRIVATE\\CANARY",
            {"results": [{"label": "private\\canary"}]},
        ),
        (
            "Private Canary",
            {"results": [{"label": "  ｐＲＩＶＡＴＥ   ｃＡＮＡＲＹ  "}]},
        ),
        (
            "XY",
            {"results": [{"label": " xy "}]},
        ),
        (
            "Private Source Canary",
            {"results": [{"label": "canary-alias"}]},
        ),
    ),
)
def test_public_validator_blocks_normalized_identity_variants(identifier, payload):
    with pytest.raises(ValueError, match="private identity leak"):
        validate_public_artifact(payload, [identifier])


def test_public_validator_ignores_empty_private_identifiers():
    validate_public_artifact(
        {
            "artifact": "valucast_competition_evidence",
            "protocol_version": "proof-v1",
            "generated_at": "2026-07-19",
            "results": [],
            "validation": {"public_claim_count": 0},
        },
        ["", "   "],
    )


def test_public_validator_ignores_numeric_fragments_inside_private_identifiers():
    validate_public_artifact(
        {
            "artifact": "valucast_competition_evidence",
            "protocol_version": "proof-v1",
            "generated_at": "2026-07-19",
            "results": [],
            "validation": {"public_claim_count": 0},
        },
        ["private-cohort-2026-07-19"],
    )


def test_public_builder_rejects_truthy_non_boolean_authorization():
    private = _private_artifact(authorized=True)
    private["tracks"]["private-track-canary"]["evaluation"][
        "claim_authorized"
    ] = "false"

    with pytest.raises(ValueError, match="authorization state"):
        build_public_artifact(private, forbidden_identifiers=[])


def test_public_builder_rejects_inconsistent_authorized_status():
    private = _private_artifact(authorized=True)
    private["tracks"]["private-track-canary"]["evaluation"][
        "status"
    ] = "collecting"

    with pytest.raises(ValueError, match="authorization state"):
        build_public_artifact(private, forbidden_identifiers=[])


def test_public_builder_rejects_inconsistent_authorized_statistical_status():
    private = _private_artifact(authorized=True)
    private["tracks"]["private-track-canary"]["evaluation"][
        "statistical_status"
    ] = "collecting"

    with pytest.raises(ValueError, match="authorized evidence"):
        build_public_artifact(private, forbidden_identifiers=[])


def test_public_builder_rejects_non_claim_eligible_primary_metric():
    private = _private_artifact(authorized=True)
    private["tracks"]["private-track-canary"]["evaluation"]["primary"][
        "metric"
    ] = "ordinal_rank_error"

    with pytest.raises(ValueError, match="authorized primary"):
        build_public_artifact(private, forbidden_identifiers=[])


def test_public_builder_rejects_missing_authorized_primary():
    private = _private_artifact(authorized=True)
    private["tracks"]["private-track-canary"]["evaluation"].pop("primary")

    with pytest.raises(ValueError, match="authorized primary"):
        build_public_artifact(private, forbidden_identifiers=[])


@pytest.mark.parametrize("primary", (None, [], {}))
def test_public_builder_rejects_invalid_authorized_primary(primary):
    private = _private_artifact(authorized=True)
    private["tracks"]["private-track-canary"]["evaluation"]["primary"] = primary

    with pytest.raises(ValueError, match="authorized primary"):
        build_public_artifact(private, forbidden_identifiers=[])


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("coverage", "unique_players"), 149),
        (("coverage", "completed_cohorts"), 2),
        (("coverage", "rate"), 0.89),
        (("coverage", "registered"), 149),
        (("primary", "error_delta_ci_low"), 0.0),
        (("primary", "error_delta_ci_high"), float("inf")),
        (("primary", "relative_improvement_pct"), 4.999),
        (("cohorts", 0, "registered"), 49),
        (("cohorts", 0, "regression_pct"), 5.001),
        (("segments",), []),
        (("segments", 0, "regression_pct"), 5.001),
        (("segments", 0, "regression_pct"), float("nan")),
        (("confirmers", "valucast_top_k_regret"), 2.001),
    ),
)
def test_public_builder_independently_revalidates_claim_evidence(path, value):
    private = _private_artifact(authorized=True)
    evaluation = private["tracks"]["private-track-canary"]["evaluation"]
    _set_path(evaluation, path, value)

    with pytest.raises(ValueError, match="authorized evidence"):
        build_public_artifact(private, forbidden_identifiers=[])


def test_public_builder_cannot_raise_the_hard_regression_caps():
    private = _private_artifact(authorized=True)
    evaluation = private["tracks"]["private-track-canary"]["evaluation"]
    evaluation["criteria"]["maximum_single_cohort_regression_pct"] = 100.0
    evaluation["criteria"]["maximum_segment_regression_pct"] = 100.0
    evaluation["cohorts"][0]["regression_pct"] = 5.001
    evaluation["segments"][0]["regression_pct"] = 5.001

    with pytest.raises(ValueError, match="authorized evidence"):
        build_public_artifact(private, forbidden_identifiers=[])


def _authorized_public_artifact() -> dict:
    return build_public_artifact(
        _private_artifact(authorized=True),
        forbidden_identifiers=[],
    )


def _set_path(payload: dict, path: tuple, value) -> None:
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def test_public_builder_projects_the_exact_aggregate_schema():
    private = _private_artifact(authorized=True)
    private["tracks"]["private-track-canary"]["evaluation"]["coverage"].update(
        {
            "rows": [{"mlbam_id": "row-canary", "name": "ROW CANARY"}],
        }
    )

    public = build_public_artifact(private, forbidden_identifiers=[])

    assert public == {
        "artifact": "valucast_competition_evidence",
        "protocol_version": "proof-v1",
        "generated_at": "2026-07-19",
        "results": [
            {
                "benchmark_class": "leading_public_prospect_boards",
                "task": "four-year prospect-selection regret",
                "status": "validated_superiority",
                "coverage": {"registered": 150, "resolved": 150, "rate": 1.0},
                "primary": {
                    "metric": "realized_value_regret",
                    "valucast_error": 0.20,
                    "baseline_error": 0.25,
                    "baseline_minus_valucast_error": 0.05,
                    "relative_improvement_pct": 20.0,
                    "error_delta_ci_low": 0.01,
                    "error_delta_ci_high": 0.09,
                },
                "confirmers": {
                    "valucast_top_k_regret": 1.0,
                    "baseline_top_k_regret": 2.0,
                },
                "segments": [
                    {
                        "role": role,
                        "resolved": 75,
                        "valucast_error": 0.20,
                        "baseline_error": 0.25,
                        "regression_pct": -20.0,
                    }
                    for role in ("hitter", "pitcher")
                ],
                "cohorts": [
                    {
                        "cohort_number": index,
                        "registered": 50,
                        "resolved": 50,
                        "coverage": 1.0,
                        "valucast_error": 0.20,
                        "baseline_error": 0.25,
                        "regression_pct": -20.0,
                    }
                    for index in range(1, 4)
                ],
            }
        ],
        "validation": {"public_claim_count": 1},
    }


def test_public_validator_rejects_row_level_coverage_canary():
    public = _authorized_public_artifact()
    public["results"][0]["coverage"]["rows"] = [
        {"mlbam_id": "row-canary", "name": "ROW CANARY"}
    ]

    with pytest.raises(ValueError, match="public artifact schema"):
        validate_public_artifact(public, forbidden_identifiers=[])


@pytest.mark.parametrize(
    "path",
    (
        (),
        ("results", 0),
        ("results", 0, "coverage"),
        ("results", 0, "primary"),
        ("results", 0, "confirmers"),
        ("results", 0, "cohorts", 0),
        ("validation",),
    ),
)
def test_public_validator_rejects_unexpected_keys(path):
    public = _authorized_public_artifact()
    target = public
    for key in path:
        target = target[key]
    target["unexpected"] = "canary"

    with pytest.raises(ValueError, match="public artifact schema"):
        validate_public_artifact(public, forbidden_identifiers=[])


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("validation", "public_claim_count"), True),
        (("results", 0, "coverage", "registered"), True),
        (("results", 0, "coverage", "rate"), float("nan")),
        (("results", 0, "primary", "baseline_error"), float("inf")),
        (("results", 0, "confirmers", "baseline_top_k_regret"), []),
        (("results", 0, "cohorts", 0, "coverage"), {}),
    ),
)
def test_public_validator_rejects_invalid_numeric_fields(path, value):
    public = _authorized_public_artifact()
    _set_path(public, path, value)

    with pytest.raises(ValueError, match="public artifact schema"):
        validate_public_artifact(public, forbidden_identifiers=[])


def test_public_validator_accepts_finite_arbitrary_precision_integer():
    public = _authorized_public_artifact()
    public["results"][0]["primary"]["relative_improvement_pct"] = 10**1000

    validate_public_artifact(public, forbidden_identifiers=[])


@pytest.mark.parametrize(
    ("path", "rate_key"),
    (
        (("results", 0, "coverage"), "rate"),
        (("results", 0, "cohorts", 0), "coverage"),
    ),
)
def test_public_validator_rejects_contradictory_coverage_rates(path, rate_key):
    public = _authorized_public_artifact()
    target = public
    for key in path:
        target = target[key]
    target.update({"registered": 3, "resolved": 2, rate_key: 0.6666})

    with pytest.raises(ValueError, match="public artifact schema"):
        validate_public_artifact(public, forbidden_identifiers=[])


@pytest.mark.parametrize(
    ("path", "rate_key"),
    (
        (("results", 0, "coverage"), "rate"),
        (("results", 0, "cohorts", 0), "coverage"),
    ),
)
def test_public_validator_requires_zero_rate_when_nothing_is_registered(
    path, rate_key
):
    public = _authorized_public_artifact()
    target = public
    for key in path:
        target = target[key]
    target.update({"registered": 0, "resolved": 0, rate_key: 0.0001})

    with pytest.raises(ValueError, match="public artifact schema"):
        validate_public_artifact(public, forbidden_identifiers=[])


def test_public_validator_accepts_builder_rounded_coverage_rates():
    public = _authorized_public_artifact()
    public["results"][0]["coverage"].update(
        {"registered": 3, "resolved": 2, "rate": 0.6667}
    )
    public["results"][0]["cohorts"][0].update(
        {"registered": 3, "resolved": 2, "coverage": 0.6667}
    )

    validate_public_artifact(public, forbidden_identifiers=[])


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("artifact",), "other_artifact"),
        (("protocol_version",), "private-v1"),
        (("results", 0, "benchmark_class"), "private_board_alias"),
        (("results", 0, "task"), "private task alias"),
        (("results", 0, "status"), "collecting"),
        (("results", 0, "primary", "metric"), "ordinal_rank_error"),
    ),
)
def test_public_validator_constrains_anonymous_text_labels(path, value):
    public = _authorized_public_artifact()
    _set_path(public, path, value)

    with pytest.raises(ValueError, match="public artifact schema"):
        validate_public_artifact(public, forbidden_identifiers=[])


def test_public_validator_rejects_invalid_segment_shape_and_role():
    public = _authorized_public_artifact()
    public["results"][0]["segments"] = [
        {
            "role": "private-role-canary",
            "resolved": True,
            "valucast_error": 0.2,
            "baseline_error": 0.25,
            "regression_pct": -20.0,
            "player_id": "row-canary",
        }
    ]

    with pytest.raises(ValueError, match="public artifact schema"):
        validate_public_artifact(public, forbidden_identifiers=[])


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("generated_at",), 20260719),
        (("generated_at",), "not-a-date"),
        (("results",), {}),
        (("results", 0, "segments"), {}),
        (("results", 0, "cohorts"), {}),
    ),
)
def test_public_validator_rejects_invalid_container_shapes(path, value):
    public = _authorized_public_artifact()
    _set_path(public, path, value)

    with pytest.raises(ValueError, match="public artifact schema"):
        validate_public_artifact(public, forbidden_identifiers=[])


def test_public_validator_reconciles_claim_count():
    public = _authorized_public_artifact()
    public["validation"]["public_claim_count"] = 0

    with pytest.raises(ValueError, match="public artifact schema"):
        validate_public_artifact(public, forbidden_identifiers=[])


def test_private_paths_cannot_be_model_inputs():
    assert PRIVATE_SOURCES_PATH.as_posix().endswith(
        "data/private/competition/sources.json"
    )
    assert PRIVATE_ARTIFACT_PATH.as_posix().endswith(
        "data/private/competition/benchmark.json"
    )
    assert "models" not in PRIVATE_ARTIFACT_PATH.parts
    assert "models" not in PUBLIC_ARTIFACT_PATH.parts


def test_prospect_board_builder_consumes_generic_rank(monkeypatch, tmp_path):
    valucast_path = tmp_path / "valucast.json"
    competitor_path = tmp_path / "competitor.json"
    valucast_path.write_text(
        json.dumps({"board": [{"mlbam_id": "1", "name": "One", "rank": 1}]}),
        encoding="utf-8",
    )
    competitor_path.write_text(
        json.dumps(
            {"players_by_mlbam": {"1": {"name": "One", "rank": 7}}}
        ),
        encoding="utf-8",
    )
    paths = {"valucast.json": valucast_path, "competitor.json": competitor_path}
    monkeypatch.setattr(
        competition_script,
        "_checked_path",
        lambda relative, _expected_hash: paths[relative],
    )
    registration = {
        "valucast_path": "valucast.json",
        "valucast_sha256": "hash",
        "competitor_path": "competitor.json",
        "competitor_sha256": "hash",
        "competitor": "PRIVATE SOURCE CANARY",
        "competitor_url": "https://example.test/board",
    }

    _, competitor_rows, _ = competition_script._prospect_board_rows(registration)

    assert competitor_rows == [{"mlbam_id": "1", "name": "One", "rank": 7}]


def _synthetic_registry() -> dict:
    return {
        "protocol_version": "proof-v1",
        "registered_at": "2026-07-19",
        "outcome_file": "data/private/competition/missing.json",
        "registrations": [
            {
                "track": "private-track-canary",
                "kind": "prospect_board_rank",
                "cohort_id": "private-cohort-canary",
                "registered_at": "2026-07-19",
                "competitor": "PRIVATE SOURCE CANARY",
                "task": "private task",
                "public_source_class": "leading_public_prospect_boards",
                "public_task": "four-year prospect-selection regret",
                "criteria": CRITERIA,
            }
        ],
    }


def _synthetic_rows() -> list[dict]:
    return [
        {
            "mlbam_id": str(index),
            "name": f"Player {index}",
            "rank": index,
            "role": "hitter",
        }
        for index in range(1, 151)
    ]


def _synthetic_private_artifact(monkeypatch) -> tuple[dict, dict]:
    source = _synthetic_registry()
    rows = _synthetic_rows()
    monkeypatch.setattr(
        competition_script,
        "_prospect_board_rows",
        lambda _registration: (rows, rows, {}),
    )
    return source, build_artifact(existing={}, source=source)


def test_private_builder_accepts_anonymous_synthetic_registry(monkeypatch):
    source, artifact = _synthetic_private_artifact(monkeypatch)

    assert source["protocol_version"] == artifact["protocol_version"]
    track = artifact["tracks"]["private-track-canary"]
    assert track["public_source_class"] == "leading_public_prospect_boards"
    assert track["evaluation"]["status"] == "collecting"
    assert track["evaluation"]["claim_authorized"] is False


def test_private_builder_revalidates_every_persisted_cohort_seal(monkeypatch):
    source, existing = _synthetic_private_artifact(monkeypatch)
    existing["tracks"]["private-track-canary"]["cohorts"][0]["rows"][0][
        "competitor_rank"
    ] = 999

    with pytest.raises(ValueError, match="seal"):
        build_artifact(existing=existing, source=source)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("competitor", "CHANGED PRIVATE SOURCE"),
        ("task", "changed private task"),
        ("public_source_class", "public_pitcher_skill_benchmarks"),
        ("public_task", "forward pitcher-skill rate error"),
        ("criteria", CRITERIA | {"top_k": 99}),
    ),
)
def test_private_builder_rejects_persisted_track_registry_drift(
    monkeypatch, field, value
):
    source, existing = _synthetic_private_artifact(monkeypatch)
    existing["tracks"]["private-track-canary"][field] = value

    with pytest.raises(ValueError, match="registry mismatch"):
        build_artifact(existing=existing, source=source)


def test_private_builder_owns_loaded_cohort_copies(monkeypatch):
    source, existing = _synthetic_private_artifact(monkeypatch)
    rebuilt = build_artifact(existing=existing, source=source)
    original_rank = rebuilt["tracks"]["private-track-canary"]["cohorts"][0][
        "rows"
    ][0]["competitor_rank"]

    existing["tracks"]["private-track-canary"]["cohorts"][0]["rows"][0][
        "competitor_rank"
    ] = 999

    assert (
        rebuilt["tracks"]["private-track-canary"]["cohorts"][0]["rows"][0][
            "competitor_rank"
        ]
        == original_rank
    )


def test_private_builder_rejects_validly_sealed_unregistered_cohort(monkeypatch):
    source, existing = _synthetic_private_artifact(monkeypatch)
    existing["tracks"]["private-track-canary"]["cohorts"].append(
        _cohort("unregistered-cohort")
    )

    with pytest.raises(ValueError, match="unregistered cohort"):
        build_artifact(existing=existing, source=source)


def test_private_builder_rejects_resealed_registered_cohort_replacement(monkeypatch):
    source, existing = _synthetic_private_artifact(monkeypatch)
    valucast_rows = _synthetic_rows()
    competitor_rows = copy.deepcopy(valucast_rows)
    competitor_rows[0]["rank"] = 999
    replacement = build_cohort(
        cohort_id="private-cohort-canary",
        registered_at="2026-07-19",
        track="private-track-canary",
        valucast_rows=valucast_rows,
        competitor_rows=competitor_rows,
        sources={},
    )
    existing["tracks"]["private-track-canary"]["cohorts"][0] = replacement

    with pytest.raises(ValueError, match="registry cohort mismatch"):
        build_artifact(existing=existing, source=source)


def test_private_builder_appends_registered_cohort_missing_from_existing(monkeypatch):
    source, existing = _synthetic_private_artifact(monkeypatch)
    existing["tracks"]["private-track-canary"]["cohorts"] = []

    rebuilt = build_artifact(existing=existing, source=source)

    assert [
        cohort["cohort_id"]
        for cohort in rebuilt["tracks"]["private-track-canary"]["cohorts"]
    ] == ["private-cohort-canary"]


def test_registered_row_builder_rejects_pinned_source_hash_mismatch(
    monkeypatch, tmp_path
):
    (tmp_path / "valucast.json").write_text('{"board": []}', encoding="utf-8")
    (tmp_path / "competitor.json").write_text(
        '{"players_by_mlbam": {}}', encoding="utf-8"
    )
    monkeypatch.setattr(competition_script, "ROOT", tmp_path)
    registration = {
        "valucast_path": "valucast.json",
        "valucast_sha256": "0" * 64,
        "competitor_path": "competitor.json",
        "competitor_sha256": "0" * 64,
        "competitor": "PRIVATE SOURCE CANARY",
        "competitor_url": "https://example.test/board",
    }

    with pytest.raises(ValueError, match="source drift"):
        competition_script._prospect_board_rows(registration)


def _cohort(
    cohort_id: str,
    offset: int = 0,
    *,
    size: int = 50,
    valucast_wins: bool = True,
) -> dict:
    players = [
        {
            "mlbam_id": str(offset + i),
            "name": f"Player {offset + i}",
            "role": "hitter" if i <= size // 2 else "pitcher",
            "rank": i if valucast_wins else size + 1 - i,
        }
        for i in range(1, size + 1)
    ]
    baseline = [
        {
            "mlbam_id": str(offset + i),
            "name": f"Player {offset + i}",
            "role": "hitter" if i <= size // 2 else "pitcher",
            "rank": size + 1 - i if valucast_wins else i,
        }
        for i in range(1, size + 1)
    ]
    return build_cohort(
        cohort_id=cohort_id,
        registered_at="2026-07-19",
        track="test",
        valucast_rows=players,
        competitor_rows=baseline,
        sources={},
    )


def _outcomes(cohorts: list[dict]) -> dict[str, float]:
    result = {}
    for cohort in cohorts:
        ordered = sorted(
            cohort["rows"], key=lambda row: int(row["mlbam_id"])
        )
        for index, row in enumerate(ordered, start=1):
            result[f"{cohort['cohort_id']}:{row['mlbam_id']}"] = 51.0 - index
    return result


def _ready_claim(**overrides) -> dict:
    ready = {
        "evidence_ready": True,
        "ci_low": 0.01,
        "ci_high": 0.03,
        "relative_improvement_pct": 5.0,
        "cohort_regressions": [0.0, 2.0, 5.0],
        "segment_regressions": [1.0, 5.0],
        "top_k_non_regression": True,
        "claim_eligible": True,
        "criteria": {
            "minimum_relative_improvement_pct": 5.0,
            "maximum_single_cohort_regression_pct": 5.0,
            "maximum_segment_regression_pct": 5.0,
        },
    }
    return ready | overrides


def test_industry_claim_policy_requires_effect_ci_and_clean_subgroups():
    ready = _ready_claim()

    assert _claim_decision(**ready) == (
        "validated_superiority",
        True,
        "validated_superiority",
    )

    for field, value in (
        ("relative_improvement_pct", 4.999),
        ("ci_low", 0.0),
        ("cohort_regressions", [5.001]),
        ("segment_regressions", [5.001]),
        ("top_k_non_regression", False),
    ):
        blocked = ready | {field: value}
        assert _claim_decision(**blocked) == (
            "no_significant_difference",
            False,
            "no_significant_difference",
        )

    research_only = ready | {"claim_eligible": False}
    assert _claim_decision(**research_only) == (
        "research_only",
        False,
        "validated_superiority",
    )


def test_claim_policy_cannot_lower_hard_practical_floor():
    criteria = _ready_claim()["criteria"] | {
        "minimum_relative_improvement_pct": 0.0
    }

    assert _claim_decision(
        **_ready_claim(relative_improvement_pct=4.999, criteria=criteria)
    ) == (
        "no_significant_difference",
        False,
        "no_significant_difference",
    )


@pytest.mark.parametrize(
    ("criterion", "regressions"),
    (
        ("maximum_single_cohort_regression_pct", "cohort_regressions"),
        ("maximum_segment_regression_pct", "segment_regressions"),
    ),
)
def test_claim_policy_cannot_raise_hard_regression_caps(criterion, regressions):
    criteria = _ready_claim()["criteria"] | {criterion: 100.0}

    assert _claim_decision(
        **_ready_claim(criteria=criteria, **{regressions: [5.001]})
    ) == (
        "no_significant_difference",
        False,
        "no_significant_difference",
    )


@pytest.mark.parametrize(
    ("criterion", "regressions"),
    (
        ("maximum_single_cohort_regression_pct", "cohort_regressions"),
        ("maximum_segment_regression_pct", "segment_regressions"),
    ),
)
def test_claim_policy_honors_stricter_regression_caps(criterion, regressions):
    criteria = _ready_claim()["criteria"] | {criterion: 2.0}

    assert _claim_decision(
        **_ready_claim(criteria=criteria, **{regressions: [2.001]})
    ) == (
        "no_significant_difference",
        False,
        "no_significant_difference",
    )


@pytest.mark.parametrize(
    "value",
    (float("nan"), float("inf"), -0.001, "invalid", None, [], True),
)
@pytest.mark.parametrize(
    "criterion",
    (
        "maximum_single_cohort_regression_pct",
        "maximum_segment_regression_pct",
    ),
)
def test_claim_policy_fails_closed_on_invalid_regression_caps(criterion, value):
    criteria = _ready_claim()["criteria"] | {criterion: value}

    assert _claim_decision(**_ready_claim(criteria=criteria)) == (
        "no_significant_difference",
        False,
        "no_significant_difference",
    )


@pytest.mark.parametrize(
    ("ci_low", "ci_high"),
    (
        (None, 0.03),
        (0.01, None),
        (float("nan"), 0.03),
        (0.01, float("nan")),
        (float("inf"), float("inf")),
        (0.01, float("inf")),
        (0.03, 0.01),
    ),
)
def test_claim_policy_requires_finite_ordered_two_sided_ci(ci_low, ci_high):
    assert _claim_decision(**_ready_claim(ci_low=ci_low, ci_high=ci_high)) == (
        "no_significant_difference",
        False,
        "no_significant_difference",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("cohort_regressions", []),
        ("segment_regressions", []),
        ("cohort_regressions", [float("-inf")]),
        ("segment_regressions", [float("nan")]),
    ),
)
def test_claim_policy_requires_nonempty_finite_guardrails(field, value):
    assert _claim_decision(**_ready_claim(**{field: value})) == (
        "no_significant_difference",
        False,
        "no_significant_difference",
    )


def test_claim_policy_uses_hard_defaults_for_missing_new_criteria():
    criteria = {"maximum_single_cohort_regression_pct": 5.0}

    assert _claim_decision(**_ready_claim(criteria=criteria)) == (
        "validated_superiority",
        True,
        "validated_superiority",
    )
    assert _claim_decision(
        **_ready_claim(
            criteria=criteria,
            relative_improvement_pct=4.999,
        )
    ) == (
        "no_significant_difference",
        False,
        "no_significant_difference",
    )


def test_industry_claim_floor_is_150_unique_players():
    assert MINIMUM_INDUSTRY_CLAIM_PLAYERS == 150


def test_build_cohort_preserves_role_for_guardrail_scoring():
    cohort = build_cohort(
        cohort_id="c1",
        registered_at="2026-07-19",
        track="test",
        valucast_rows=[
            {"mlbam_id": "1", "name": "One", "rank": 1, "role": "pitcher"}
        ],
        competitor_rows=[
            {"mlbam_id": "1", "name": "One", "rank": 2, "role": "pitcher"}
        ],
        sources={},
    )

    assert cohort["rows"][0]["role"] == "pitcher"


def test_append_cohort_rejects_a_changed_sealed_cohort():
    cohort = _cohort("c1")
    registry = {"cohorts": {}}
    append_cohort(registry, cohort)
    append_cohort(registry, copy.deepcopy(cohort))

    changed = copy.deepcopy(cohort)
    changed["rows"][0]["competitor_rank"] = 999
    changed["content_sha256"] = "changed"
    with pytest.raises(ValueError, match="immutable"):
        append_cohort(registry, changed)


def test_append_cohort_rejects_an_invalid_content_seal():
    cohort = _cohort("c1")
    cohort["rows"][0]["competitor_rank"] = 999

    with pytest.raises(ValueError, match="seal"):
        append_cohort({"cohorts": {}}, cohort)


def test_append_cohort_owns_an_immutable_copy():
    cohort = _cohort("c1")
    original_rank = cohort["rows"][0]["competitor_rank"]
    registry = {"cohorts": {}}
    append_cohort(registry, cohort)

    cohort["rows"][0]["competitor_rank"] = 999

    assert registry["cohorts"]["c1"]["rows"][0]["competitor_rank"] == original_rank


def test_missing_outcomes_cannot_authorize_a_claim():
    result = build_track([_cohort("c1")], {}, CRITERIA)
    assert result["status"] == "collecting"
    assert result["claim_authorized"] is False
    assert result["primary"] is None


def test_ordinal_track_stays_research_only_after_150_unique_players():
    cohorts = [_cohort(f"c{i}", i * 50) for i in range(3)]
    result = build_track(cohorts, _outcomes(cohorts), CRITERIA)

    assert result["coverage"]["unique_players"] == 150
    assert result["primary"]["bootstrap_cohorts"] == 3
    assert result["primary"]["relative_improvement_pct"] >= 5.0
    assert result["status"] == "research_only"
    assert result["statistical_status"] == "validated_superiority"
    assert result["claim_authorized"] is False


def test_rounded_coverage_cannot_complete_an_incomplete_cohort():
    cohort = _cohort("partial", size=6)
    outcomes = _outcomes([cohort])
    for row in cohort["rows"][4:]:
        outcomes.pop(f"partial:{row['mlbam_id']}")
    criteria = CRITERIA | {
        "minimum_cohorts": 1,
        "minimum_outcome_coverage": 0.6667,
    }

    result = build_track([cohort], outcomes, criteria)

    assert result["cohorts"][0]["coverage"] == 0.6667
    assert result["coverage"]["completed_cohorts"] == 0
    assert result["primary"] is None


def test_incomplete_cohort_cannot_contaminate_a_valid_conclusion():
    complete = [_cohort(f"c{i}", i * 50) for i in range(3)]
    outcomes = _outcomes(complete)
    expected = build_track(complete, outcomes, CRITERIA)
    partial = _cohort("partial", 150, valucast_wins=False)
    first = partial["rows"][0]
    outcomes[f"partial:{first['mlbam_id']}"] = 1.0

    result = build_track([*complete, partial], outcomes, CRITERIA)

    assert result["primary"] == expected["primary"]
    assert result["segments"] == expected["segments"]
    assert result["confirmers"] == expected["confirmers"]
    assert result["status"] == expected["status"]
    assert result["statistical_status"] == expected["statistical_status"]
    assert result["claim_authorized"] == expected["claim_authorized"]
