"""Build the ValuCast prospect rank-history artifact from the dated rank archive.

PURE aggregation: ZERO network. Reads every dated file in the committed archive
data/prediction_archive/valucast_prospect_peak_projection_v1/*.json and rolls the
prospect-board rank (rank_v1_rank) over time into one compact per-player artifact:
data/models/valucast_prospect_rank_history.json.

WHY RANK, NOT SCORE: ranks are RELATIVE and survive score re-baselines, so this
surface is epoch-robust where a raw-score history is not. Franklin Arias 2026-07-14
re-based 60.1 -> 54.6 in score but only moved 6 -> 7 in rank; the rank archive still
proves ValuCast ranked him #1 overall on 2026-06-18, weeks before consensus.

SCOPE: a player is included iff rank_v1_rank <= TOP_N on at least one archived date.
Per player: the ordered rank series (absent/null-rank dates omitted, never fabricated),
plus best_rank / earliest best_rank_date / latest_rank / latest_date. Series entries are
compact [date, rank] pairs (documented in source_policy.series_shape).

DUPLICATE POLICY: the archive carries genuine same-mlbam duplicate rows for deep
organizational-depth arms (e.g. 826141 Sean Barnett, split A/A+ rows, rank ~2400/2779,
score 0.0) that appear in every recent file. Those never enter our top-N universe, so
they can never corrupt a series. We fail loudly ONLY on a duplicate mlbam among the
rows we actually INCLUDE on a date (rank_v1_rank <= TOP_N) -- that is the only case
where two conflicting ranks would make a single date's series entry ambiguous. Verified:
zero such in-universe duplicates across the current archive.

DISPLAY-ONLY: nothing here feeds a model score, public rank, buy score, or AOTC. It is
card context only. Atomic write with an artifact/generated_at/source_policy/validation
envelope in house style (mirrors scripts/build_aaa_statcast_features.py and the archive's
own validation block).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# --- Paths -----------------------------------------------------------------
ARCHIVE_DIR = (
    ROOT / "data" / "prediction_archive" / "valucast_prospect_peak_projection_v1"
)
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_history.json"

# --- Scope -----------------------------------------------------------------
# A player must crack the top-N board on at least one archived date to be tracked.
# 500 keeps the artifact focused on the real prospect universe (787 players ever
# ranked <= 500 across the current archive) and compact (well under the ~3MB budget).
TOP_N = 500


def _archive_dates(archive_dir: Path) -> list[str]:
    """Sorted YYYY-MM-DD stems of every *.json in the archive dir."""
    return sorted(p.stem for p in archive_dir.glob("*.json"))


def _iter_ranked_rows(payload: dict, date: str):
    """Yield (mlbam_id_str, name, rank) for in-universe rows on one date.

    In-universe = rank_v1_rank is an int <= TOP_N. Null / missing / out-of-band ranks
    are skipped here (never fabricated). Raises ValueError on a duplicate mlbam_id
    AMONG the included rows -- the only duplicate that would corrupt a series entry.
    """
    seen: set[str] = set()
    for row in payload.get("projections") or ():
        rank = row.get("rank_v1_rank")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank > TOP_N:
            continue
        mlbam = row.get("mlbam_id")
        if mlbam is None:
            continue
        key = str(mlbam)
        if key in seen:
            raise ValueError(
                f"duplicate mlbam_id {key} among top-{TOP_N} rows in {date}.json "
                "(two conflicting ranks for one player on one date -- refusing to "
                "build an ambiguous rank series)"
            )
        seen.add(key)
        yield key, row.get("name"), rank


def build_history(archive_dir: Path = ARCHIVE_DIR) -> dict:
    """Aggregate the dated archive into per-player rank series + summaries."""
    dates = _archive_dates(archive_dir)
    # player_key -> {"name": str, "series": [[date, rank], ...]}  (dates ascending)
    players: dict[str, dict] = {}
    for date in dates:
        payload = json.loads((archive_dir / f"{date}.json").read_text(encoding="utf-8"))
        for key, name, rank in _iter_ranked_rows(payload, date):
            entry = players.get(key)
            if entry is None:
                entry = players[key] = {"name": name, "series": []}
            # Keep the most recent non-empty display name we saw for this player.
            if name:
                entry["name"] = name
            entry["series"].append([date, rank])

    out_players: dict[str, dict] = {}
    for key, entry in players.items():
        series = entry["series"]  # already date-ascending (dates iterated sorted)
        # best_rank = lowest rank number; best_rank_date = EARLIEST date achieving it.
        best_date, best_rank = min(series, key=lambda dr: (dr[1], dr[0]))
        latest_date, latest_rank = series[-1]
        out_players[key] = {
            "name": entry["name"],
            "series": series,
            "best_rank": best_rank,
            "best_rank_date": best_date,
            "latest_rank": latest_rank,
            "latest_date": latest_date,
        }

    return {
        "artifact": "valucast_prospect_rank_history",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_policy": {
            "display_only": True,
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "inputs": "valucast_prospect_peak_projection_v1_dated_archive",
            "top_n": TOP_N,
            "series_shape": "[date, rank] pairs, date-ascending; null/absent dates omitted",
        },
        "archive_dates": dates,
        "player_count": len(out_players),
        "players": out_players,
        "validation": _validation_block(out_players, dates),
    }


def _validation_block(players: dict[str, dict], dates: list[str]) -> dict:
    """House-style {blockers, sanity counts, ready_for_...} validation envelope."""
    blockers: list[str] = []
    if not dates:
        blockers.append("no archive dates found")
    if not players:
        blockers.append("no players cracked the top-N board on any date")
    # Every series must be non-empty, and every rank in it must be a positive int.
    malformed = 0
    for entry in players.values():
        series = entry.get("series") or []
        if not series or any(
            not isinstance(r, int) or isinstance(r, bool) or r < 1 for _, r in series
        ):
            malformed += 1
    if malformed:
        blockers.append(f"{malformed} players have a malformed rank series")
    return {
        "blockers": blockers,
        "archive_date_count": len(dates),
        "player_count": len(players),
        "malformed_series_count": malformed,
        "ready_for_rank_history": not blockers,
    }


def write_artifact(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, default=ARCHIVE_DIR)
    parser.add_argument("--out", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args(argv)

    if not args.archive_dir.is_dir():
        # Cold checkout / missing archive: no-op so the daily build continues and
        # the reader/card fail soft (missing artifact -> feature hidden).
        print(
            f"rank-history: archive dir absent ({args.archive_dir}); "
            "skipping build, keeping any stale artifact",
            flush=True,
        )
        return 0

    payload = build_history(args.archive_dir)
    path = write_artifact(payload, args.out)
    print(
        "prospect rank history: "
        f"dates={len(payload['archive_dates'])} "
        f"players={payload['player_count']} -> {path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
