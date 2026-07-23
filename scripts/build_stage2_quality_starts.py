"""Build an input-bound, research-only quality-starts sidecar."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.mlb_actuals import derive_qs_from_games, fetch_game_logs  # noqa: E402


DEFAULT_INPUT = ROOT / "data/prospects/prospect_model_inputs.json"
DEFAULT_HISTORY = ROOT / "data/mlb/mlb_history_pitching_seasons.json"
DEFAULT_OUTPUT = ROOT / "data/validation/valucast_stage2_quality_starts.json"


def _content_sha256(payload: dict) -> str:
    body = {key: value for key, value in payload.items() if key != "content_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _collect_pitcher_seasons(payload: dict) -> tuple[dict, int, list, list]:
    grouped: dict[tuple[int, int], dict] = {}
    blockers: list[str] = []
    conflicts: list[dict] = []
    source_rows = 0

    for key, seasons in (payload.get("historical_mlb_seasons") or {}).items():
        if not str(key).endswith("_pitcher"):
            continue
        try:
            mlbam_id = int(str(key).rsplit("_", 1)[0])
        except ValueError:
            blockers.append(f"invalid_pitcher_identity:{key}")
            continue
        for season in seasons or []:
            source_rows += 1
            try:
                year = int(season["year"])
                ip = float(season.get("ip") or 0)
            except (KeyError, TypeError, ValueError):
                blockers.append(f"invalid_pitcher_season:{mlbam_id}:{source_rows}")
                continue
            row = grouped.setdefault(
                (mlbam_id, year), {"ip": 0.0, "qs": set(), "raw_rows": 0}
            )
            row["ip"] = max(row["ip"], ip)
            row["raw_rows"] += 1
            if season.get("qs") is not None:
                try:
                    row["qs"].add(int(season["qs"]))
                except (TypeError, ValueError):
                    blockers.append(f"invalid_existing_qs:{mlbam_id}:{year}")

    for (mlbam_id, season), row in sorted(grouped.items()):
        if len(row["qs"]) > 1:
            values = sorted(row["qs"])
            conflicts.append(
                {"mlbam_id": mlbam_id, "season": season, "values": values}
            )
            blockers.append(f"duplicate_qs_conflict:{mlbam_id}:{season}")

    return grouped, source_rows, conflicts, blockers


def _history_games_started(payload: dict) -> tuple[dict, list[str]]:
    games_started: dict[tuple[int, int], int] = {}
    blockers: list[str] = []
    for row in payload.get("rows") or []:
        try:
            key = (int(row["id"]), int(row["season"]))
            value = int(row.get("gs") or 0)
        except (KeyError, TypeError, ValueError):
            blockers.append("invalid_history_games_started_row")
            continue
        if key in games_started and games_started[key] != value:
            blockers.append(f"history_games_started_conflict:{key[0]}:{key[1]}")
        games_started[key] = value
    return games_started, blockers


def _load_checkpoint(path: Path | None, input_sha256: str) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if payload.get("input_sha256") != input_sha256:
        return {}
    rows = payload.get("rows")
    return rows if isinstance(rows, dict) else {}


def _save_checkpoint(path: Path | None, input_sha256: str, rows: dict) -> None:
    if path is not None:
        _write_json_atomic(
            path, {"input_sha256": input_sha256, "rows": rows}
        )


def _games_at_cutoff(games: list[dict], season: int, cutoff: date) -> list[dict]:
    if season < cutoff.year:
        return games
    if season > cutoff.year:
        raise ValueError("season is after the input cutoff")
    included = []
    for game in games:
        game_date = date.fromisoformat(str(game.get("date") or "")[:10])
        if game_date <= cutoff:
            included.append(game)
    return included


def build_quality_starts(
    input_payload: dict,
    history_payload: dict,
    *,
    input_path: str,
    input_sha256: str,
    fetcher=fetch_game_logs,
    checkpoint_path: Path | None = None,
    delay: float = 0.075,
) -> dict:
    """Return a complete QS sidecar report without mutating either input."""
    grouped, source_rows, conflicts, blockers = _collect_pitcher_seasons(
        input_payload
    )
    history_gs, history_blockers = _history_games_started(history_payload)
    blockers.extend(history_blockers)
    try:
        cutoff = date.fromisoformat(
            str((input_payload.get("current") or {}).get("fetched_date"))
        )
    except ValueError:
        cutoff = date.min
        blockers.append("invalid_input_cutoff_date")

    checkpoint = _load_checkpoint(checkpoint_path, input_sha256)
    rows = []
    resolved_keys = set()
    existing_checked = 0
    existing_mismatches = []
    current_season_superseded = []
    games_started_mismatches = []

    for (mlbam_id, season), source in sorted(grouped.items()):
        if len(source["qs"]) > 1:
            continue
        existing_qs = next(iter(source["qs"]), None)
        expected_gs = history_gs.get((mlbam_id, season))
        should_fetch = (
            expected_gs is not None and expected_gs > 0
        ) or (
            expected_gs is None and source["ip"] > 0
        )

        if not should_fetch:
            if existing_qs not in (None, 0):
                existing_mismatches.append(
                    {
                        "mlbam_id": mlbam_id,
                        "season": season,
                        "existing": existing_qs,
                        "derived": 0,
                    }
                )
                blockers.append(
                    f"quality_starts_mismatch:{mlbam_id}:{season}"
                )
                continue
            rows.append(
                {
                    "mlbam_id": mlbam_id,
                    "season": season,
                    "games_started": 0,
                    "quality_starts": 0,
                    "provenance": (
                        "existing_qs" if existing_qs is not None else "no_starts"
                    ),
                }
            )
            resolved_keys.add((mlbam_id, season))
            continue

        cache_key = f"{mlbam_id}:{season}"
        derived = checkpoint.get(cache_key)
        if derived is None:
            try:
                games = fetcher(str(mlbam_id), "pitching", season)
                games = _games_at_cutoff(games, season, cutoff)
                derived = {
                    "games_started": sum(
                        int((game.get("stat") or {}).get("gamesStarted", 0) or 0)
                        for game in games
                    ),
                    "quality_starts": derive_qs_from_games(games),
                }
            except Exception:
                blockers.append(f"game_log_fetch_failed:{mlbam_id}:{season}")
                continue
            checkpoint[cache_key] = derived
            _save_checkpoint(checkpoint_path, input_sha256, checkpoint)
            if delay:
                time.sleep(delay)

        row_valid = True
        actual_gs = int(derived["games_started"])
        derived_qs = int(derived["quality_starts"])
        if expected_gs is not None and actual_gs != expected_gs:
            games_started_mismatches.append(
                {
                    "mlbam_id": mlbam_id,
                    "season": season,
                    "expected": expected_gs,
                    "actual": actual_gs,
                }
            )
            blockers.append(f"games_started_mismatch:{mlbam_id}:{season}")
            row_valid = False
        if existing_qs is not None and season < cutoff.year:
            existing_checked += 1
            if existing_qs != derived_qs:
                existing_mismatches.append(
                    {
                        "mlbam_id": mlbam_id,
                        "season": season,
                        "existing": existing_qs,
                        "derived": derived_qs,
                    }
                )
                blockers.append(
                    f"quality_starts_mismatch:{mlbam_id}:{season}"
                )
                row_valid = False
        elif existing_qs is not None and existing_qs != derived_qs:
            current_season_superseded.append(
                {
                    "mlbam_id": mlbam_id,
                    "season": season,
                    "existing": existing_qs,
                    "derived": derived_qs,
                }
            )
        if row_valid:
            use_existing = existing_qs is not None and season < cutoff.year
            rows.append(
                {
                    "mlbam_id": mlbam_id,
                    "season": season,
                    "games_started": actual_gs,
                    "quality_starts": (
                        existing_qs if use_existing else derived_qs
                    ),
                    "provenance": (
                        "existing_qs" if use_existing else "derived_game_log"
                    ),
                }
            )
            resolved_keys.add((mlbam_id, season))

    blockers = list(dict.fromkeys(blockers))
    report = {
        "schema": "valucast_stage2_quality_starts",
        "version": "1.0.0",
        "status": "blocked" if blockers else "ready",
        "source": {
            "provider": "MLB StatsAPI",
            "stat": "gameLog",
            "group": "pitching",
            "game_type": "R",
            "definition": "GS > 0 and IP >= 6.0 and ER <= 3",
        },
        "input": {
            "path": input_path,
            "sha256": input_sha256,
            "cutoff_date": cutoff.isoformat(),
        },
        "coverage": {
            "source_rows": source_rows,
            "unique_player_seasons": len(grouped),
            "resolved_player_seasons": len(resolved_keys),
            "post_join_rows_with_qs": sum(
                source["raw_rows"]
                for key, source in grouped.items()
                if key in resolved_keys
            ),
        },
        "validation": {
            "existing_values_checked": existing_checked,
            "existing_value_mismatches": existing_mismatches,
            "current_season_values_superseded": current_season_superseded,
            "games_started_mismatches": games_started_mismatches,
            "duplicate_value_conflicts": conflicts,
        },
        "rows": rows,
        "blockers": blockers,
    }
    report["content_sha256"] = _content_sha256(report)
    return report


def build_from_files(
    input_path: Path,
    history_path: Path,
    output_path: Path,
    *,
    checkpoint_path: Path | None = None,
    fetcher=fetch_game_logs,
    delay: float = 0.075,
) -> dict:
    input_bytes = input_path.read_bytes()
    input_sha256 = hashlib.sha256(input_bytes).hexdigest()
    if checkpoint_path is None:
        checkpoint_path = (
            Path(tempfile.gettempdir())
            / f"valucast_stage2_qs_{input_sha256[:16]}.json"
        )
    try:
        display_path = input_path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        display_path = str(input_path)
    report = build_quality_starts(
        json.loads(input_bytes),
        json.loads(history_path.read_text(encoding="utf-8")),
        input_path=display_path,
        input_sha256=input_sha256,
        fetcher=fetcher,
        checkpoint_path=checkpoint_path,
        delay=delay,
    )
    _write_json_atomic(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--delay", type=float, default=0.075)
    args = parser.parse_args()
    report = build_from_files(
        args.input,
        args.history,
        args.output,
        checkpoint_path=args.checkpoint,
        delay=args.delay,
    )
    coverage = report["coverage"]
    print(
        f"{report['status']}: "
        f"{coverage['resolved_player_seasons']}/"
        f"{coverage['unique_player_seasons']} player-seasons resolved"
    )
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
