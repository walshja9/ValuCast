from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


_ADAPTER_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "models"
    / "valucast_prospect_league_adapters.json"
)
_PRESETS = (("dd_7x7", "7x7"), ("roto_5x5", "5x5"))


def format_ranks_for(mlbam_id, role=None):
    """Format ranks for a player. role is optional -- a prospect appears under one
    role in the adapter, so we resolve it from the adapter when the caller (e.g. the
    card row, which doesn't expose role) doesn't supply one."""
    if mlbam_id is None:
        return []
    lookup, roles_by_mlbam = _lookup_for(str(_ADAPTER_PATH), _mtime(_ADAPTER_PATH))
    mid = str(mlbam_id)
    resolved_role = str(role) if role else roles_by_mlbam.get(mid)
    if not resolved_role:
        return []
    return list(lookup.get((mid, resolved_role), ()))


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


@lru_cache(maxsize=8)
def _lookup_for(path_text, mtime):
    try:
        payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}

    lookup = {}
    roles_by_mlbam = {}
    presets = payload.get("presets") or {}
    for preset_key, label in _PRESETS:
        roles = (presets.get(preset_key) or {}).get("roles") or {}
        for role, role_payload in roles.items():
            players = role_payload.get("players") or []
            total = len(players)
            total_label = f"{total:,}"
            for player in players:
                rank = player.get("adapter_rank")
                if rank is None:
                    continue
                mlbam_id = player.get("mlbam_id")
                if mlbam_id is None:
                    continue
                mid = str(mlbam_id)
                lookup.setdefault((mid, str(role)), []).append({
                    "label": label,
                    "rank": rank,
                    "total": total,
                    "total_label": total_label,
                })
                roles_by_mlbam.setdefault(mid, str(role))
    return lookup, roles_by_mlbam
