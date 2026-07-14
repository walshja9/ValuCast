"""Build a network-free ProspectsLive "Live Rankings" consensus snapshot.

Input (committed, replaced by re-exporting from ProspectsLive when they re-rank):
  data/prospectslive/prospectslive_top600.csv
This file arrives MANUALLY (operator drops in a fresh export); there is no fetch.
Header: Rk,Player,Pos,Team,Level,Age,Min,Max,App,Var,High,Low,Greg,Kyle,PJ,Tom.

ProspectsLive publishes a continuously-updated board with a composite consensus
rank `Rk` (its own blend of rankers). We take that one composite `Rk` as
ProspectsLive's single vote -- treated as ONE source (like STS, itself a 7-system
consensus), NOT five. We NEVER read or persist the per-ranker columns
(Greg/Kyle/PJ/Tom) or the spread columns (Min/Max/App/Var/High/Low): rank aggregate
only, a ToS posture. Join is name-based (PL carries no mlbam), gated on role + org +
age against the current prospect board.

Output: data/prospectslive/prospectslive_consensus_snapshot.json keyed by mlbam_id (str).

PL ranks are CONSENSUS REFERENCE only -- they feed the "ahead of consensus"
divergence + display, never the ValuCast score (independence policy).

ponytail: deterministic, stdlib only, no network. Re-run after re-exporting the
CSV. Self-check in __main__ asserts the known-good shape.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.consensus_join_util import (  # noqa: E402
    build_candidate_index,
    normalize_org,
    parse_age,
    resolve_mlbam,
)

PL_CSV = ROOT / "data" / "prospectslive" / "prospectslive_top600.csv"
RANK_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
OUT_PATH = ROOT / "data" / "prospectslive" / "prospectslive_consensus_snapshot.json"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    # hyphen/dot/slash -> space to match the board's normalized_name (Fitz-Gerald,
    # K.C. Hunt, Watts-Brown); the board normalizes those with a space, not deletion.
    s = re.sub(r"[-./]", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", s.lower())).strip()


def _role_from_pos(pos: str) -> str:
    """PL lists pitchers as bare 'P'; hitters carry a fielding position. First token
    wins for two-way guys listed bat-position-first (e.g. 'OF,P' -> hitter)."""
    first = (pos or "").split(",")[0].strip().upper()
    return "pitcher" if first in {"P", "SP", "RP"} else "hitter"


def _board_name_index() -> dict:
    """normalized_name -> [candidate identities] for role/org/age-gated joins."""
    try:
        board = json.loads(RANK_PATH.read_text(encoding="utf-8")).get("board", [])
    except Exception:  # noqa: BLE001
        return {}
    return build_candidate_index(board, _norm)


def _source_as_of() -> str:
    """Operator-supplied export date: the raw CSV file mtime (manual export, not a
    fetch). Date only, UTC, labeled honestly by the caller."""
    return datetime.fromtimestamp(PL_CSV.stat().st_mtime, timezone.utc).date().isoformat()


def build_snapshot() -> dict:
    with PL_CSV.open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    name_idx = _board_name_index()

    by_mlbam: dict[str, dict] = {}
    unmatched: list[dict] = []
    total = 0
    for r in rows:
        rk = (r.get("Rk") or "").strip()
        if not rk.isdigit():
            continue
        total += 1
        pl_rank = int(rk)
        name = (r.get("Player") or "").strip()
        role = _role_from_pos(r.get("Pos", ""))
        # PL carries Team + Age + role: keep the role gate, then require org equality
        # AND age +/-1. A row missing team/age falls back to unique-name resolution.
        mid = resolve_mlbam(
            name_idx.get(_norm(name), []),
            ext_org=normalize_org(r.get("Team")),
            ext_age=parse_age(r.get("Age")),
            ext_role=role,
            require_org=True,
            require_age=True,
            require_role=True,
        )
        if not mid:
            unmatched.append({"name": name, "role": role, "pl_rank": pl_rank})
            continue
        record = {"name": name, "role": role, "pl_rank": pl_rank, "mlbam_id": mid}
        # best (lowest) rank wins if two CSV rows collide on one mlbam (name-index dup/twin)
        if mid not in by_mlbam or pl_rank < by_mlbam[mid]["pl_rank"]:
            by_mlbam[mid] = record

    return {
        "artifact": "prospectslive_consensus_snapshot",
        "snapshot_version": "1.0.0",
        "source": "prospectslive_top600_fantasy",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_as_of": _source_as_of(),
        "usage": "consensus_reference_for_divergence_display_only",
        "source_policy": {
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "external_consensus_used_for_divergence_display_only": True,
        },
        "counts": {
            "total_rows": total,
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
    top = sorted(payload["players_by_mlbam"].values(), key=lambda r: r["pl_rank"])[:5]
    for r in top:
        print(f"  pl#{r['pl_rank']:<3} {r['name']:<20} {r['role']}")
    # Tuned to the July-2026 Live Rankings export (~60 rows). Re-tune if PL changes depth.
    assert 30 <= c["total_rows"] <= 800, c
    assert c["matched_to_mlbam"] >= 20, c
    if "--write" in sys.argv:
        print("wrote", OUT_PATH, write_snapshot())
    else:
        print("(dry run; pass --write to emit", OUT_PATH.name, ")")
