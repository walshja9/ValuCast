"""Buy score for the /buys prospect board.

Pure functions in the value_spark.py mold: feed rows in, plain dicts out,
no Flask imports. Composite and term semantics per
docs/superpowers/specs/2026-06-12-prospect-buys-design.md (incl. the
post-critique resolutions section).
"""
from __future__ import annotations

import math
from datetime import date

# Operator controls. EXCLUDE_IDS is the manual guard for the public graphic
# (injury news the data hasn't caught up to, identity doubts) — the feed has
# no injury signal, so this is the only brake.
EXCLUDE_IDS: frozenset = frozenset()
INCLUDE_MLB_LEVEL = False  # call-ups' buy window closed at debut

WEIGHTS = {"momentum": 0.35, "breakout": 0.30, "gap": 0.20, "runway": 0.15}

# Momentum. Steps are 10-17 pts vs <=~1 pt real daily moves; the threshold
# applies to consecutive-point deltas REGARDLESS of calendar gap, because the
# producer's denylist removes days adjacent to real steps (6/3's 10.6-pt step
# sits across the removed 6/2 — a per-day rate would slip under it).
STEP_THRESHOLD = 6.0
MAX_POINT_GAP_DAYS = 3      # sparser than this = stale/broken series, stop
MOMENTUM_WINDOW_DAYS = 14   # anchored at the latest point
# Tuned 6/12 against the live feed: the spec's (-0.08, 0.12)/20 left 24% of
# the eligible pool pinned at m=1.0 (no rank discrimination up top); this
# pairing cuts that to 10% with the same top-10 names. Zero raw move still
# maps to exactly NEUTRAL_MOMENTUM.
MOMENTUM_CLAMP = (-0.10, 0.15)
MOMENTUM_DENOM_FLOOR = 30.0  # rel-change on tiny values saturates on noise
NEUTRAL_MOMENTUM = 0.4

BREAKOUT_TIERS = {
    "major_breakout": 1.0, "breakout": 0.75, "rising": 0.5,
    "steady": 0.15, "": 0.10, None: 0.10, "slipping": -0.15, "falling": -0.30,
}

PIPELINE_UNRANKED = 150
_GAP_LOG_DENOM = math.log10(PIPELINE_UNRANKED)

AGE_RUNWAY = {18: 1.0, 19: 0.9, 20: 0.75, 21: 0.6, 22: 0.45, 23: 0.3}
LEVEL_RUNWAY = {"A": 1.0, "A+": 0.85, "AA": 0.6, "AAA": 0.35}

BOARD_SIZE = 40
N_BOUNDS = (10, 60)

# Graphic assets. PNG spots, not team-logos/*.svg — external SVG <img> is
# html2canvas's known silent-blank path. mlbstatic serves ACAO:* on both.
TEAM_IDS = {
    "ARI": 109, "ATH": 133, "ATL": 144, "BAL": 110, "BOS": 111, "CHC": 112,
    "CHW": 145, "CIN": 113, "CLE": 114, "COL": 115, "DET": 116, "HOU": 117,
    "KC": 118, "LAA": 108, "LAD": 119, "MIA": 146, "MIL": 158, "MIN": 142,
    "NYM": 121, "NYY": 147, "PHI": 143, "PIT": 134, "SD": 135, "SEA": 136,
    "SF": 137, "STL": 138, "TB": 139, "TEX": 140, "TOR": 141, "WSH": 120,
}

HEADSHOT_URL = ("https://img.mlbstatic.com/mlb-photos/image/upload/"
                "d_people:generic:headshot:67:current.png/w_120,q_auto:best/"
                "v1/people/{mlbam_id}/headshot/67/current")
LOGO_URL = "https://midfield.mlbstatic.com/v1/team/{team_id}/spots/64"


def _day_ordinal(date_str):
    """ISO date -> proleptic ordinal. None for malformed dates."""
    try:
        y, m, d = (int(p) for p in str(date_str).split("-"))
        return date(y, m, d).toordinal()
    except (TypeError, ValueError):
        return None


def clean_tail(value_history):
    """Walk back from the latest point; stop at an epoch step, a stale gap,
    or the window edge. Returns chronological [(date, value), ...]."""
    pts = [(d, float(v)) for d, v in (value_history or ()) if d is not None]
    if not pts:
        return []
    tail = [pts[-1]]
    last_ord = _day_ordinal(pts[-1][0])
    for date_str, value in reversed(pts[:-1]):
        cur_ord = _day_ordinal(date_str)
        prev_ord = _day_ordinal(tail[0][0])
        if cur_ord is None or prev_ord is None:
            break
        if abs(tail[0][1] - value) > STEP_THRESHOLD:
            break  # epoch step — regardless of how many calendar days it spans
        if prev_ord - cur_ord > MAX_POINT_GAP_DAYS:
            break
        if last_ord - cur_ord > MOMENTUM_WINDOW_DAYS:
            break
        tail.insert(0, (date_str, value))
    return tail


def momentum_score(value_history):
    tail = clean_tail(value_history)
    if len(tail) < 2:
        return NEUTRAL_MOMENTUM
    first, last = tail[0][1], tail[-1][1]
    raw = (last - first) / max(first, MOMENTUM_DENOM_FLOOR)
    lo, hi = MOMENTUM_CLAMP
    raw = max(lo, min(hi, raw))
    return (raw - lo) / (hi - lo)


def breakout_score(label):
    return BREAKOUT_TIERS.get(label, 0.10)


def consensus_gap_score(source_ranks):
    ranks = source_ranks or {}
    perf_candidates = [ranks[k] for k in ("hkb", "milb_perf")
                       if isinstance(ranks.get(k), (int, float))]
    if not perf_candidates:
        return 0.0
    perf = min(perf_candidates)
    pipeline = ranks.get("pipeline")
    if not isinstance(pipeline, (int, float)):
        pipeline = PIPELINE_UNRANKED
    gap = pipeline - perf
    if gap <= 0:
        return 0.0
    return min(1.0, math.log10(max(gap, 1)) / _GAP_LOG_DENOM)


def runway_score(age, level):
    if age is None:
        age_term = 0.5
    else:
        age_i = int(age)
        if age_i <= 18:
            age_term = 1.0
        elif age_i >= 24:
            age_term = 0.15
        else:
            age_term = AGE_RUNWAY[age_i]
    level_term = LEVEL_RUNWAY.get(level, 0.5)  # None/unknown codes -> neutral
    return (age_term + level_term) / 2


def score_row(row):
    terms = {
        "momentum": momentum_score(row.value_history),
        "breakout": breakout_score(row.breakout_label),
        "gap": consensus_gap_score(row.source_ranks),
        "runway": runway_score(row.age, row.level),
    }
    composite = sum(WEIGHTS[k] * v for k, v in terms.items())
    return composite, terms


def eligible(row):
    if not row.is_prospect or row.id in EXCLUDE_IDS:
        return False
    return INCLUDE_MLB_LEVEL or row.level != "MLB"


def clamp_n(raw):
    lo, hi = N_BOUNDS
    try:
        return max(lo, min(hi, int(raw)))
    except (TypeError, ValueError):
        return BOARD_SIZE


def graphic_initials(name):
    """At most two initials for the graphic's intentional photo fallback."""
    return "".join(part[0] for part in str(name or "").split()[:2]).upper() or "VC"


def graphic_reason(terms, label):
    """Short, controlled explanation that fits a featured graphic card."""
    if terms["gap"] >= 0.9:
        return "Rank gap"
    if terms["momentum"] >= 0.95:
        return "14-day surge"
    if label in {"major_breakout", "breakout"}:
        return "Breakout"
    return "Young runway"


def build_board(rows, n=BOARD_SIZE):
    """Ranked buy list, top n. Plain dicts ready for the template."""
    scored = []
    for row in rows:
        if not eligible(row):
            continue
        composite, terms = score_row(row)
        scored.append((composite, row, terms))
    scored.sort(key=lambda t: (-t[0], -(t[1].dynasty_value or 0.0),
                               t[1].name or ""))
    board = []
    for rank, (composite, row, terms) in enumerate(scored[:n], start=1):
        positions = list(row.positions or ())
        team_id = TEAM_IDS.get(row.team)
        mlbam = row.mlbam_id if row.mlbam_id else 0  # 0 forces the silhouette
        board.append({
            "rank": rank,
            "id": row.id,
            "name": row.name,
            "team": row.team or "",
            "pos": "/".join(positions[:2]) or "—",
            "level": row.level or "—",
            "age": row.age,
            "score": round(max(composite, 0.0) * 100, 1),
            "label": row.breakout_label or "",
            "terms": terms,
            "initials": graphic_initials(row.name),
            "reason": graphic_reason(terms, row.breakout_label),
            "headshot_url": HEADSHOT_URL.format(mlbam_id=mlbam),
            "logo_url": LOGO_URL.format(team_id=team_id) if team_id else None,
            "value_history": row.value_history,
        })
    return board


def build_valucast_board(rows, n=BOARD_SIZE):
    """Format ValuCast-owned buy signal rows for the existing `/buys` template.

    The live route only consumes this when the ValuCast buy artifact is promoted.
    """
    board = []
    for row in list(rows)[:n]:
        positions = list(row.get("positions") or ())
        team_id = TEAM_IDS.get(row.get("team"))
        mlbam = row.get("mlbam_id") if row.get("mlbam_id") else 0
        valucast_terms = row.get("terms") or {}
        display_terms = {
            "momentum": valucast_terms.get("momentum", NEUTRAL_MOMENTUM),
            "breakout": valucast_terms.get("model_strength", 0.0),
            "gap": valucast_terms.get("buy_window", 0.0),
            "runway": valucast_terms.get("runway", 0.0),
        }
        board.append({
            "rank": row.get("rank"),
            "id": row.get("player_id") or row.get("id"),
            "name": row.get("name"),
            "team": row.get("team") or "",
            "pos": "/".join(positions[:2]) or "-",
            "level": row.get("level") or "-",
            "age": row.get("age"),
            "score": row.get("score"),
            "label": row.get("reason") or "",
            "terms": display_terms,
            "valucast_terms": valucast_terms,
            "initials": graphic_initials(row.get("name")),
            "reason": row.get("reason") or "ValuCast signal",
            "headshot_url": HEADSHOT_URL.format(mlbam_id=mlbam),
            "logo_url": LOGO_URL.format(team_id=team_id) if team_id else None,
            "value_history": row.get("score_history") or (),
        })
    return board
