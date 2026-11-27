"""Run the single registered MLB pitcher skill challenger look.

The command intentionally exposes only readiness and spend modes.  Acquisition,
tuning, fold selection, output selection, and production wiring are out of scope.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import tempfile
from pathlib import Path

from projections.backtest.pitcher_skill_challenger_harness import (
    BASE_FLAGS,
    RESULT_PATH,
    TARGET_SEASONS,
    canonical_sha256,
    check_readiness as build_readiness,
    evaluate_registered_look,
    load_registration,
    missing_registration_seals,
    summarize_common_support,
    write_spent_result,
)
from projections.data.identity import load_identity_store
from projections.data.pitching_historical import load_pitching_season
from projections.models.marcel_pitcher import (
    build_pitcher_projections,
    compute_cfip,
)
from projections.models.pitcher_params import PitcherMarcelParams


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "plans" / "035-mlb-pitcher-skill-challenger.md"
OUTPUT_PATH = ROOT / RESULT_PATH
HISTORICAL_DATA_DIR = ROOT / "projections" / "data"
STATCAST_DATA_DIR = HISTORICAL_DATA_DIR / "pitching_statcast"
RESEARCH_IMPLEMENTATION_PATHS = (
    "projections/models/pitcher_skill_challenger.py",
    "projections/backtest/pitcher_skill_challenger_harness.py",
    "scripts/run_mlb_pitcher_skill_challenger.py",
    # Review P2-3: the raw feature aggregates are research evidence too — a
    # serving import of the acquisition module must trip the guard, not slide
    # under it. The fetch CLI rides along so its own import stays legal.
    "projections/data/pitching_statcast.py",
    "scripts/fetch_mlb_pitcher_statcast.py",
)
SEALED_IMPLEMENTATION_PATHS = (
    *RESEARCH_IMPLEMENTATION_PATHS,
    "projections/models/marcel_pitcher.py",
    "projections/models/pitcher_params.py",
    "projections/models/pitcher_role.py",
    "projections/backtest/pitching_harness.py",
    "projections/constants.py",
    "projections/data/pitching_historical.py",
    "projections/data/identity.py",
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Check or spend the one registered pitcher challenger look."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check-readiness", action="store_true")
    modes.add_argument("--spend-registered-look", action="store_true")
    return parser.parse_args(argv)


def _json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _derived_forecast(row: dict, *, season: int) -> dict | None:
    ip = float(row.get("IP", 0) or 0)
    if ip <= 0:
        return None
    return {
        "mlbam_id": str(row["mlbam_id"]),
        "season": int(season),
        "forecast_window": "full_season",
        "K_9": 9.0 * float(row.get("K", 0) or 0) / ip,
        "BB_9": 9.0 * float(row.get("BB", 0) or 0) / ip,
        "ERA": 9.0 * float(row.get("ER", 0) or 0) / ip,
        "WHIP": (
            float(row.get("BB", 0) or 0)
            + float(row.get("H_ALLOWED", 0) or 0)
        )
        / ip,
    }


def _control_rows(target_season: int) -> list[dict]:
    snapshots = []
    for season in range(target_season - 1, target_season - 4, -1):
        try:
            snapshots.append(load_pitching_season(season, HISTORICAL_DATA_DIR))
        except FileNotFoundError:
            snapshots.append([])
    cfip = compute_cfip(snapshots)
    if cfip is None:
        raise ValueError(f"Control cFIP is unavailable for {target_season}")

    rows = []
    for projection in build_pitcher_projections(
        target_season, HISTORICAL_DATA_DIR, PitcherMarcelParams()
    ):
        metadata = projection.get("metadata") or {}
        pitcher_id = str(metadata.get("mlbam_id") or "")
        stats = projection.get("stats") or {}
        if not pitcher_id or not stats:
            raise ValueError(f"malformed Control projection for {target_season}")
        rows.append(
            {
                **stats,
                "mlbam_id": pitcher_id,
                "season": int(target_season),
                "p_sp": float(metadata["p_sp"]),
                "cFIP": float(cfip),
            }
        )
    return rows


def load_study_bundle(registration: dict) -> dict:
    """Load only committed, sealed inputs; never acquire or inspect results."""
    feature_seasons = [int(value) for value in registration["statcast_feature_seasons"]]
    target_seasons = [int(value) for value in registration["retrospective_target_seasons"]]
    manifest = _json(STATCAST_DATA_DIR / "manifest.json")
    manifest_seasons = manifest.get("seasons")
    if not isinstance(manifest_seasons, dict):
        raise ValueError("pitching Statcast manifest lacks seasons")

    features = []
    for season in feature_seasons:
        entry = manifest_seasons.get(str(season))
        if not isinstance(entry, dict) or not entry.get("canonical_sha256"):
            raise ValueError(f"missing sealed Statcast feature season {season}")
        path = STATCAST_DATA_DIR / f"pitching_statcast_{season}.json"
        rows = _json(path)
        if not isinstance(rows, list):
            raise ValueError(f"malformed Statcast feature season {season}")
        if canonical_sha256(rows) != entry["canonical_sha256"]:
            raise ValueError(f"Statcast feature hash mismatch for {season}")
        features.extend(rows)

    controls = []
    outcomes = []
    persistence = []
    pair_keys = []
    outcome_seasons = range(min(feature_seasons) + 1, max(target_seasons) + 1)
    for target in outcome_seasons:
        target_controls = _control_rows(target)
        target_outcomes = [
            {**row, "mlbam_id": str(row["mlbam_id"]), "season": target}
            for row in load_pitching_season(target, HISTORICAL_DATA_DIR)
        ]
        control_ids = {row["mlbam_id"] for row in target_controls}
        outcome_ids = {row["mlbam_id"] for row in target_outcomes}
        if target in target_seasons:
            for pitcher_id in sorted(control_ids & outcome_ids):
                pair_keys.append({"mlbam_id": pitcher_id, "outcome_season": target})
        controls.extend(target_controls)
        outcomes.extend(target_outcomes)

        try:
            previous = load_pitching_season(target - 1, HISTORICAL_DATA_DIR)
        except FileNotFoundError:
            previous = []
        for row in previous:
            forecast = _derived_forecast(row, season=target)
            if forecast is not None:
                persistence.append(forecast)

    identity_store = load_identity_store(HISTORICAL_DATA_DIR)
    identities = [
        {"mlbam_id": str(pitcher_id), "throws": row.get("throws")}
        for pitcher_id, row in sorted(identity_store.items())
    ]
    bundle = {
        "pair_keys": pair_keys,
        "controls": controls,
        "outcomes": outcomes,
        "features": features,
        "identities": identities,
        "persistence": persistence,
        # No historical, exact-window Steamer archive is currently authorized.
        "steamer": [],
        "source_manifest": {
            "feature_seasons": feature_seasons,
            "source_hashes": {
                str(season): manifest_seasons[str(season)]["canonical_sha256"]
                for season in feature_seasons
            },
        },
    }
    bundle["common_support"] = summarize_common_support(bundle)
    return bundle


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def current_implementation_commit() -> str:
    dirty = _git("status", "--porcelain", "--", *SEALED_IMPLEMENTATION_PATHS)
    if dirty:
        raise ValueError("pitcher challenger implementation has uncommitted changes")
    value = _git(
        "log",
        "-1",
        "--format=%H",
        "--",
        *SEALED_IMPLEMENTATION_PATHS,
    )
    if len(value) != 40:
        raise ValueError("pitcher challenger implementation is not committed")
    return value


def current_source_hashes(registration: dict) -> dict:
    manifest = _json(STATCAST_DATA_DIR / "manifest.json")
    seasons = manifest.get("seasons") or {}
    result = {}
    for season in registration["statcast_feature_seasons"]:
        entry = seasons.get(str(season))
        if not isinstance(entry, dict) or not entry.get("canonical_sha256"):
            raise ValueError(f"missing source hash for Statcast season {season}")
        result[str(season)] = entry["canonical_sha256"]
    return result


def serving_import_matches() -> list[str]:
    """Fail closed on direct or transitive production imports of research code."""

    def module_name(path: Path) -> str:
        relative = path.relative_to(ROOT).with_suffix("")
        parts = list(relative.parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    excluded = {ROOT / path for path in RESEARCH_IMPLEMENTATION_PATHS}
    python_paths = []
    for path in sorted(ROOT.rglob("*.py")):
        relative = path.relative_to(ROOT)
        if path in excluded or "tests" in relative.parts:
            continue
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in relative.parts):
            continue
        python_paths.append(path)
    module_paths = {module_name(path): path for path in python_paths + list(excluded)}
    forbidden = {module_name(path) for path in excluded}
    graph = {}

    def imported_modules(path: Path) -> set[str]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            return set()
        current = module_name(path)
        package = (
            current.split(".")
            if path.name == "__init__.py"
            else current.split(".")[:-1]
        )
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    keep = max(0, len(package) - node.level + 1)
                    prefix = package[:keep]
                    base = ".".join(prefix + ([node.module] if node.module else []))
                else:
                    base = node.module or ""
                if base:
                    imports.add(base)
                for alias in node.names:
                    candidate = f"{base}.{alias.name}" if base else alias.name
                    if candidate in module_paths:
                        imports.add(candidate)
        return imports

    for module, path in module_paths.items():
        if module not in forbidden:
            graph[module] = imported_modules(path)

    matches = set()
    for start, path in sorted(module_paths.items()):
        if start in forbidden or "tests" in path.relative_to(ROOT).parts:
            continue
        queue = [(start, [start])]
        visited = set()
        while queue:
            module, chain = queue.pop(0)
            if module in visited:
                continue
            visited.add(module)
            for dependency in sorted(graph.get(module, ())):
                next_chain = chain + [dependency]
                if dependency in forbidden:
                    labels = [
                        module_paths[value].relative_to(ROOT).as_posix()
                        for value in next_chain
                    ]
                    matches.add(" -> ".join(labels))
                elif dependency in graph:
                    queue.append((dependency, next_chain))

    needles = tuple(path.stem for path in excluded)
    for directory in (ROOT / "templates", ROOT / "static", ROOT / ".github"):
        for path in sorted(directory.rglob("*")) if directory.exists() else []:
            if not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(lines, 1):
                if any(needle in line for needle in needles):
                    matches.add(f"{path.relative_to(ROOT).as_posix()}:{number}")
    return sorted(matches)


def _replace_reserved(path: Path, reservation: dict, payload: dict) -> None:
    current = _json(path)
    if current != reservation:
        raise FileExistsError("spent reservation changed; refusing replacement")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _spent_boundary(registration: dict, readiness: dict, verdict: str) -> dict:
    return {
        **BASE_FLAGS,
        "study_id": registration["study_id"],
        "registration_hash": canonical_sha256(registration),
        "implementation_commit": registration.get("implementation_commit"),
        "source_hashes": registration.get("source_hashes"),
        "readiness_hash": readiness.get("evidence_hash"),
        "verdict": verdict,
    }


def main(argv=None) -> int:
    args = parse_args(argv)
    registration = load_registration(PLAN_PATH)
    if args.spend_registered_look:
        missing = missing_registration_seals(registration)
        if missing:
            raise ValueError(
                "registered look cannot be spent until sealed: " + ", ".join(missing)
            )

    bundle = load_study_bundle(registration)
    readiness = build_readiness(
        bundle,
        registration,
        implementation_commit=current_implementation_commit(),
        source_hashes=current_source_hashes(registration),
        serving_import_matches=serving_import_matches(),
    )
    if args.check_readiness:
        print(json.dumps(readiness, indent=2, sort_keys=True, allow_nan=False))
        return 0 if readiness["ready_to_spend"] else 2
    if not readiness["ready_to_spend"]:
        raise ValueError("registered look is sealed but readiness checks failed")

    # Reserve the single look as an allowed fail-closed terminal result first.
    # A process death after this line still consumes the look honestly.
    reservation = _spent_boundary(registration, readiness, "spent_error")
    write_spent_result(OUTPUT_PATH, reservation)
    try:
        result = evaluate_registered_look(bundle, registration)
        _replace_reserved(OUTPUT_PATH, reservation, result)
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except Exception:
        failed = _spent_boundary(registration, readiness, "spent_error")
        _replace_reserved(OUTPUT_PATH, reservation, failed)
        print(json.dumps(failed, indent=2, sort_keys=True, allow_nan=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
