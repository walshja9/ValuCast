"""Build a network-free FanGraphs FV snapshot from committed Board exports.

Inputs (committed, refreshed by re-exporting from FanGraphs "The Board"):
  data/fangraphs/fg_board_hitters.csv   - all prospects, hitter tool-grade columns
  data/fangraphs/fg_board_pitchers.csv  - all prospects, pitcher tool-grade columns

Both files list the SAME player universe; they differ only in which grade columns
are populated, so we union by FanGraphs PlayerId and merge grade blocks.

Output:
  data/fangraphs/fg_fv_snapshot.json - keyed by mlbam_id (str) for the app join.

FV / tool grades are SCOUTING REFERENCE only. They are display + divergence
context. They never feed the ValuCast score, rank, value, or buy-score
(independence policy). The join to mlbam_id uses the projections crosswalk
(ros.json fangraphs_id -> mlbam_id), with a normalized-name fallback.

ponytail: deterministic, stdlib only, no network. Re-run after re-exporting the
two CSVs. Self-check in __main__ asserts the known-good shape.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HIT_CSV = ROOT / "data" / "fangraphs" / "fg_board_hitters.csv"
PIT_CSV = ROOT / "data" / "fangraphs" / "fg_board_pitchers.csv"
ROS_PATH = ROOT / "data" / "projections" / "ros.json"
RANK_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
OUT_PATH = ROOT / "data" / "fangraphs" / "fg_fv_snapshot.json"

HIT_GRADE_COLS = ["Hit", "Pitch Sel", "Bat Ctrl", "Con Style", "Game Pwr",
                  "Raw Pwr", "Spd", "Fld", "Versa", "Hard Hit%"]
PIT_GRADE_COLS = ["TJ Date", "FB Type", "FB", "SL", "CB", "CH", "CMD",
                  "Sits", "Tops"]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", s.lower())).strip()


def _int_or_none(v):
    v = (v or "").strip()
    return int(v) if v.isdigit() and v != "0" else None


def _fv_numeric(fv: str):
    """'55' -> 55.0 ; '45+' -> 47.5 (half-tier bump). None if unparseable."""
    fv = (fv or "").strip()
    m = re.match(r"^(\d{2})(\+?)$", fv)
    if not m:
        return None
    return float(m.group(1)) + (2.5 if m.group(2) else 0.0)


def _grades(row: dict, cols: list[str]) -> dict:
    out = {}
    for c in cols:
        val = (row.get(c) or "").strip()
        if val:
            out[c] = val
    return out


def _load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _load_crosswalk() -> dict:
    """fangraphs_id (str) -> mlbam_id (str) from the projections file."""
    try:
        ros = json.loads(ROS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    xwalk = {}
    for r in ros:
        md = r.get("metadata") or {}
        fid, mid = md.get("fangraphs_id"), md.get("mlbam_id")
        if fid and mid:
            xwalk[str(fid)] = str(mid)
    return xwalk


def _load_board_name_index() -> dict:
    """normalized_name -> (mlbam_id, team) for unambiguous fallback joins.
    Team rides along so the fallback can be corroborated — an unguarded
    name-only join can hang the wrong player's scouting grades on a card."""
    try:
        board = json.loads(RANK_PATH.read_text(encoding="utf-8")).get("board", [])
    except Exception:  # noqa: BLE001
        return {}
    idx: dict[str, list[tuple[str, str]]] = {}
    for row in board:
        mid = row.get("mlbam_id")
        if mid is None:
            continue
        key = _norm(row.get("normalized_name") or row.get("name", ""))
        team = str(row.get("mlb_team") or row.get("team") or "").strip().upper()
        idx.setdefault(key, []).append((str(mid), team))
    # keep only unambiguous names
    return {k: v[0] for k, v in idx.items() if len(v) == 1}


def build_snapshot() -> dict:
    hitters = _load_csv(HIT_CSV)
    pitchers = _load_csv(PIT_CSV)
    xwalk = _load_crosswalk()
    name_idx = _load_board_name_index()

    players: dict[str, dict] = {}

    def base(row: dict) -> dict:
        return {
            "fg_player_id": (row.get("PlayerId") or "").strip(),
            "name": (row.get("Name") or "").strip(),
            "pos": (row.get("Pos") or "").strip(),
            "org": (row.get("Org") or "").strip(),
            "fg_top100": _int_or_none(row.get("Top 100")),
            "fg_org_rank": _int_or_none(row.get("Org Rk")),
            "fv": (row.get("FV") or "").strip(),
            "fv_num": _fv_numeric(row.get("FV")),
            "hit_grades": {},
            "pitch_grades": {},
        }

    for row in hitters:
        pid = (row.get("PlayerId") or "").strip()
        if not pid:
            continue
        rec = players.setdefault(pid, base(row))
        rec["hit_grades"] = _grades(row, HIT_GRADE_COLS)
    for row in pitchers:
        pid = (row.get("PlayerId") or "").strip()
        if not pid:
            continue
        rec = players.setdefault(pid, base(row))
        rec["pitch_grades"] = _grades(row, PIT_GRADE_COLS)

    by_mlbam: dict[str, dict] = {}
    unmatched: list[dict] = []
    for pid, rec in players.items():
        mid = xwalk.get(pid)
        if not mid:
            # Name fallback only with org corroboration (7/2): same normalized
            # name AND same org, or no match at all — never a blind name join.
            candidate = name_idx.get(_norm(rec["name"]))
            if candidate:
                cand_mid, cand_team = candidate
                rec_org = str(rec.get("org") or "").strip().upper()
                if rec_org and cand_team and rec_org == cand_team:
                    mid = cand_mid
        if mid:
            rec["mlbam_id"] = mid
            # last write wins is fine (FV identical across files for a pid)
            by_mlbam[mid] = rec
        else:
            unmatched.append({"name": rec["name"], "fg_player_id": pid,
                              "fv": rec["fv"], "fg_top100": rec["fg_top100"]})

    return {
        "artifact": "fangraphs_fv_snapshot",
        "snapshot_version": "1.0.0",
        "source": "fangraphs_the_board_export",
        "usage": "scouting_reference_display_and_divergence_context_only",
        "source_policy": {
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "external_grades_used_for_display_only": True,
        },
        "counts": {
            "unique_players": len(players),
            "matched_to_mlbam": len(by_mlbam),
            "unmatched": len(unmatched),
        },
        "players_by_mlbam": by_mlbam,
        "unmatched": sorted(unmatched, key=lambda r: (r["fg_top100"] or 9999)),
    }


def write_snapshot() -> dict:
    payload = build_snapshot()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(OUT_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, OUT_PATH)
    return payload["counts"]


if __name__ == "__main__":
    payload = build_snapshot()
    c = payload["counts"]
    by_mlbam = payload["players_by_mlbam"]
    # Real coverage: snapshot players that land on a CURRENT prospect board row.
    try:
        board = json.loads(RANK_PATH.read_text(encoding="utf-8")).get("board", [])
    except Exception:  # noqa: BLE001
        board = []
    board_mids = {str(r.get("mlbam_id")) for r in board if r.get("mlbam_id") is not None}
    on_board = sum(1 for mid in by_mlbam if mid in board_mids)
    griffin = next((r for r in by_mlbam.values() if r["name"] == "Konnor Griffin"), None)

    print("unique_players :", c["unique_players"])
    print("matched_mlbam  :", c["matched_to_mlbam"])
    print("unmatched      :", c["unmatched"])
    print("on_board       :", on_board, "/", len(board_mids), "board rows gain FG FV")

    # Known-good shape from the 2026-06-23 export (ranges so a routine re-export
    # does not trip the guard).
    assert 1100 <= c["unique_players"] <= 1400, c
    assert c["matched_to_mlbam"] >= 700, c
    assert 600 <= on_board <= 1100, on_board
    # Griffin maps to an mlbam (complete map) but, having graduated, his mlbam is
    # NOT a current prospect board row -> he drops from the board join for free.
    assert griffin is not None and griffin["fv"] == "70", griffin
    assert griffin["mlbam_id"] not in board_mids, "graduated FG#1 must not be a board row"
    if "--write" in sys.argv:
        print("wrote", OUT_PATH, write_snapshot())
    else:
        print("(dry run; pass --write to emit", OUT_PATH.name, ")")
