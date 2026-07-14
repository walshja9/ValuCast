"""Shared name -> mlbam_id join helpers for the external-consensus snapshot builders
(HKB / Pipeline / ProspectsLive / STS).

The four builders resolve name-keyed external ranks to ValuCast's mlbam-keyed board.
Name alone collides: e.g. a 17.6yo SFG shortstop "Luis Hernandez" and the board's
23yo MIN catcher "Luis Hernandez" (mlbam 801346) normalize identically, and a
first-writer-wins name index silently re-routed the young one onto the wrong id.

This module keys joins on normalized_name + org + age (and, where the source carries
it, role), with an unmatched fallback so a bad/absent attribute never re-routes to the
wrong identity. Org codes are normalized on BOTH sides before equality because the
board and each source spell a handful of teams differently (SF vs SFG, OAK vs ATH...).
"""
from __future__ import annotations

# Source spellings -> the board's canonical org code (board uses ATH/SFG/SDP/TBR/
# WSN/CHW/KC/ARI). Applied to both sides before equality; canonical -> canonical is
# a no-op, so mapping both sides is safe.
_ORG_ALIASES = {
    "KCR": "KC", "KCA": "KC",
    "SF": "SFG", "SFN": "SFG",
    "OAK": "ATH",
    "SD": "SDP", "SDN": "SDP",
    "TB": "TBR", "TBA": "TBR",
    "WSH": "WSN", "WAS": "WSN",
    "CWS": "CHW", "CHA": "CHW",
    "AZ": "ARI", "ARZ": "ARI",
}


def normalize_org(code) -> str:
    """Canonical org code, or '' when absent/unparseable."""
    c = str(code or "").strip().upper()
    return _ORG_ALIASES.get(c, c)


def parse_age(value):
    """External ages arrive as '19.2'/'23'/23; round to a whole year, or None."""
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def build_candidate_index(rows, normalize_name):
    """normalized_name -> list of candidate identities, deduped by mlbam_id (first
    writer per id wins, so board rows layered before universe keep priority).

    Each candidate: {"mlbam_id": str, "org": canonical str, "age": int|None,
    "role": str|None}. Uses each row's own normalized_name when present, else the
    passed normalize_name() on the display name.
    """
    index: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        mlbam = row.get("mlbam_id")
        if mlbam in (None, ""):
            continue
        key = row.get("normalized_name") or normalize_name(row.get("name"))
        if not key:
            continue
        bucket = index.setdefault(key, [])
        mid = str(mlbam)
        if any(c["mlbam_id"] == mid for c in bucket):
            continue  # first writer per id wins (board before universe)
        bucket.append({
            "mlbam_id": mid,
            "org": normalize_org(row.get("mlb_team")),
            "age": parse_age(row.get("age")),
            "role": row.get("role"),
        })
    return index


def resolve_mlbam(
    candidates,
    *,
    ext_org=None,
    ext_age=None,
    ext_role=None,
    require_org=False,
    require_age=False,
    require_role=False,
):
    """Accept/reject predicate shared by the four builders. Returns a single mlbam_id
    str or None (unmatched).

    Gating rules (all honest -- a missing attribute never re-routes):
      * role: when require_role and ext_role is given, keep candidates of that role;
        if none share the role but exactly one candidate exists, fall back to it
        (matches the pre-existing single-candidate any-role behaviour).
      * org / age: when required AND the source row carries the attribute, keep only
        candidates whose org matches (post-normalization) / whose age is within +/-1.
        When the source row LACKS the attribute, that gate is skipped and the join
        falls back to requiring a unique surviving identity (like the name-only
        Pipeline source) -- so an absent attribute can never silently pick a twin.
      * A match is returned only when exactly one identity survives the applied gates.
    """
    if not candidates:
        return None

    pool = list(candidates)

    if require_role and ext_role:
        role_hits = [c for c in pool if c.get("role") == ext_role]
        if role_hits:
            pool = role_hits
        elif len(pool) != 1:
            return None  # role given but ambiguous across roles

    if require_org and ext_org:
        pool = [c for c in pool if c.get("org") and c["org"] == ext_org]

    if require_age and ext_age is not None:
        pool = [c for c in pool if c.get("age") is not None and abs(c["age"] - ext_age) <= 1]

    ids = {c["mlbam_id"] for c in pool}
    if len(ids) == 1:
        return pool[0]["mlbam_id"]
    return None
