"""Build a network-free Scout-the-Statline Formulated-Consensus snapshot.

Inputs (committed, refreshed by re-exporting from STS with "Show low-coverage" OFF):
  data/sts/sts_consensus_hitters.csv
  data/sts/sts_consensus_pitchers.csv

STS publishes hitters and pitchers as separate lists, each with an "Avg Rank"
(mean rank across its 7 source systems: BaGS/DIGS, FScore, PG+, Prospect
Larceny, OOPSY, PARS, Prospect Tilt). We combine both, sort by Avg Rank, and
assign a single COMBINED ordinal so it's comparable to the other combined
prospect boards (pipeline/hkb/FG). Join is name-based (STS carries no mlbam),
role-disambiguated against the current prospect board.

Output: data/sts/sts_consensus_snapshot.json keyed by mlbam_id (str).

STS ranks are CONSENSUS REFERENCE only -- they feed the "ahead of consensus"
divergence + display, never the ValuCast score (independence policy).

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
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HIT_CSV = ROOT / "data" / "sts" / "sts_consensus_hitters.csv"
PIT_CSV = ROOT / "data" / "sts" / "sts_consensus_pitchers.csv"
RANK_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
OUT_PATH = ROOT / "data" / "sts" / "sts_consensus_snapshot.json"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", s.lower())).strip()


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load_csv(path: Path, role: str) -> list[dict]:
    with path.open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        row["_role"] = role
    return rows


def _board_name_index() -> dict:
    """normalized_name -> {role: mlbam_id} for role-disambiguated joins."""
    try:
        board = json.loads(RANK_PATH.read_text(encoding="utf-8")).get("board", [])
    except Exception:  # noqa: BLE001
        return {}
    idx: dict[str, dict[str, str]] = defaultdict(dict)
    for row in board:
        mid = row.get("mlbam_id")
        role = row.get("role")
        if mid is None or role not in {"hitter", "pitcher"}:
            continue
        idx[_norm(row.get("normalized_name") or row.get("name", ""))][role] = str(mid)
    return idx


def build_snapshot() -> dict:
    rows = (
        [r for r in _load_csv(HIT_CSV, "hitter") if _float(r.get("Avg Rank")) is not None]
        + [r for r in _load_csv(PIT_CSV, "pitcher") if _float(r.get("Avg Rank")) is not None]
    )
    rows.sort(key=lambda r: _float(r.get("Avg Rank")))  # combined order, best first
    name_idx = _board_name_index()

    by_mlbam: dict[str, dict] = {}
    unmatched: list[dict] = []
    for combined_rank, r in enumerate(rows, 1):
        name = (r.get("Name") or "").strip()
        candidates = name_idx.get(_norm(name), {})
        mid = candidates.get(r["_role"]) or (
            next(iter(candidates.values())) if len(candidates) == 1 else None
        )
        record = {
            "name": name,
            "role": r["_role"],
            "sts_rank": combined_rank,
            "avg_rank": _float(r.get("Avg Rank")),
            "coverage": _float(r.get("Coverage")),
        }
        if mid:
            record["mlbam_id"] = mid
            by_mlbam[mid] = record  # first (best) wins on dup mlbam
        else:
            unmatched.append({"name": name, "role": r["_role"], "sts_rank": combined_rank})

    return {
        "artifact": "sts_formulated_consensus_snapshot",
        "snapshot_version": "1.0.0",
        "source": "scout_the_statline_formulated_consensus",
        "usage": "consensus_reference_for_divergence_display_only",
        "source_policy": {
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "external_consensus_used_for_divergence_display_only": True,
        },
        "counts": {
            "total_rows": len(rows),
            "matched_to_mlbam": len(by_mlbam),
            "unmatched": len(unmatched),
        },
        "players_by_mlbam": by_mlbam,
        "unmatched": unmatched[:200],
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
    print("total_rows    :", c["total_rows"])
    print("matched_mlbam :", c["matched_to_mlbam"])
    print("unmatched     :", c["unmatched"])
    top = sorted(payload["players_by_mlbam"].values(), key=lambda r: r["sts_rank"])[:5]
    for r in top:
        print(f"  sts#{r['sts_rank']:<3} {r['name']:<20} {r['role']} avg{r['avg_rank']}")
    assert 2500 <= c["total_rows"] <= 4000, c
    assert c["matched_to_mlbam"] >= 1800, c
    if "--write" in sys.argv:
        print("wrote", OUT_PATH, write_snapshot())
    else:
        print("(dry run; pass --write to emit", OUT_PATH.name, ")")
