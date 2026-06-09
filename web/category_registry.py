from __future__ import annotations

from league_values.models import CategorySpec, Direction, PlayerPool, PointRule


# --- Hitting Categories (pool=HITTER) ---

HITTING_CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec(id="R", label="Runs", pool=PlayerPool.HITTER, stat="R"),
    CategorySpec(id="HR", label="Home Runs", pool=PlayerPool.HITTER, stat="HR"),
    CategorySpec(id="RBI", label="RBI", pool=PlayerPool.HITTER, stat="RBI"),
    CategorySpec(id="SB", label="Stolen Bases", pool=PlayerPool.HITTER, stat="SB"),
    CategorySpec(
        id="AVG", label="Batting Average", pool=PlayerPool.HITTER,
        numerator_stats=("H",), denominator_stats=("AB",), min_denominator=30.0,
    ),
    CategorySpec(
        id="OBP", label="On-Base Pct", pool=PlayerPool.HITTER,
        numerator_stats=("H", "BB", "HBP"), denominator_stats=("AB", "BB", "HBP", "SF"),
        min_denominator=30.0,
    ),
    CategorySpec(id="OPS", label="OPS", pool=PlayerPool.HITTER, stat="OPS"),
    CategorySpec(
        id="SLG", label="Slugging", pool=PlayerPool.HITTER,
        numerator_stats=("TB",), denominator_stats=("AB",), min_denominator=30.0,
    ),
    CategorySpec(id="H", label="Hits", pool=PlayerPool.HITTER, stat="H"),
    CategorySpec(id="BB", label="Walks", pool=PlayerPool.HITTER, stat="BB"),
    CategorySpec(
        id="SO", label="Strikeouts", pool=PlayerPool.HITTER, stat="SO",
        direction=Direction.LOWER_IS_BETTER,
    ),
    CategorySpec(id="TB", label="Total Bases", pool=PlayerPool.HITTER, stat="TB"),
    CategorySpec(id="NSB", label="Net Steals", pool=PlayerPool.HITTER, stat="NSB"),
)


# --- Pitching Categories (pool=PITCHER, applies to both SP and RP) ---

PITCHING_CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec(id="W", label="Wins", pool=PlayerPool.PITCHER, stat="W"),
    CategorySpec(
        id="L", label="Losses", pool=PlayerPool.PITCHER, stat="L",
        direction=Direction.LOWER_IS_BETTER,
    ),
    CategorySpec(id="K", label="Strikeouts", pool=PlayerPool.PITCHER, stat="K"),
    CategorySpec(id="QS", label="Quality Starts", pool=PlayerPool.PITCHER, stat="QS"),
    CategorySpec(id="SV", label="Saves", pool=PlayerPool.PITCHER, stat="SV"),
    CategorySpec(id="HLD", label="Holds", pool=PlayerPool.PITCHER, stat="HLD"),
    CategorySpec(id="SV_HLD", label="SV+HLD", pool=PlayerPool.PITCHER, stat="SV_HLD"),
    CategorySpec(
        id="ERA", label="ERA", pool=PlayerPool.PITCHER,
        numerator_stats=("ER",), denominator_stats=("IP",),
        direction=Direction.LOWER_IS_BETTER, ratio_multiplier=9.0, min_denominator=10.0,
    ),
    CategorySpec(
        id="WHIP", label="WHIP", pool=PlayerPool.PITCHER,
        numerator_stats=("BB", "H_ALLOWED"), denominator_stats=("IP",),
        direction=Direction.LOWER_IS_BETTER, min_denominator=10.0,
    ),
    CategorySpec(id="K_BB", label="K/BB", pool=PlayerPool.PITCHER, stat="K_BB"),
    CategorySpec(id="IP", label="Innings Pitched", pool=PlayerPool.PITCHER, stat="IP"),
    CategorySpec(
        id="K_9", label="K/9", pool=PlayerPool.PITCHER,
        numerator_stats=("K",), denominator_stats=("IP",),
        ratio_multiplier=9.0, min_denominator=10.0,
    ),
    CategorySpec(
        id="BB_9", label="BB/9", pool=PlayerPool.PITCHER,
        numerator_stats=("BB",), denominator_stats=("IP",),
        direction=Direction.LOWER_IS_BETTER, ratio_multiplier=9.0, min_denominator=10.0,
    ),
)


# Index by ID for fast lookup
_ALL_CATEGORIES: dict[str, CategorySpec] = {
    c.id: c for c in HITTING_CATEGORIES + PITCHING_CATEGORIES
}


# Canonical ordering = registry declaration order (hitting then pitching).
_CANONICAL_ORDER: dict[str, int] = {
    c.id: i for i, c in enumerate(HITTING_CATEGORIES + PITCHING_CATEGORIES)
}


def canonicalize_cats(ids: list[str]) -> list[str]:
    """Return the given category ids sorted into canonical registry order,
    dropping unknowns and duplicates (first occurrence wins). Makes column order
    and preset matching independent of form-serialization order."""
    seen = set()
    deduped = []
    for cid in ids:
        if cid in _CANONICAL_ORDER and cid not in seen:
            seen.add(cid)
            deduped.append(cid)
    return sorted(deduped, key=lambda c: _CANONICAL_ORDER[c])


# --- Category Presets ---

CATEGORY_PRESETS: dict[str, dict[str, list[str]]] = {
    "5x5": {
        "cats": ["R", "HR", "RBI", "SB", "AVG"],
        "pcats": ["W", "SV", "K", "ERA", "WHIP"],
    },
    "6x6": {
        "cats": ["R", "HR", "RBI", "SB", "AVG", "OBP"],
        "pcats": ["W", "QS", "SV", "K", "ERA", "WHIP"],
    },
}

DEFAULT_CATS = CATEGORY_PRESETS["5x5"]["cats"]
DEFAULT_PCATS = CATEGORY_PRESETS["5x5"]["pcats"]


# --- Points Presets ---

POINTS_PRESETS: dict[str, tuple[PointRule, ...]] = {
    "default": (
        PointRule(stat="R", points=1.0, pool=PlayerPool.HITTER),
        PointRule(stat="RBI", points=1.0, pool=PlayerPool.HITTER),
        PointRule(stat="1B", points=1.0, pool=PlayerPool.HITTER),
        PointRule(stat="2B", points=2.0, pool=PlayerPool.HITTER),
        PointRule(stat="3B", points=3.0, pool=PlayerPool.HITTER),
        PointRule(stat="HR", points=4.0, pool=PlayerPool.HITTER),
        PointRule(stat="BB", points=1.0, pool=PlayerPool.HITTER),
        PointRule(stat="SB", points=2.0, pool=PlayerPool.HITTER),
        PointRule(stat="CS", points=-1.0, pool=PlayerPool.HITTER),
        PointRule(stat="IP", points=3.0, pool=PlayerPool.PITCHER),
        PointRule(stat="K", points=1.0, pool=PlayerPool.PITCHER),
        PointRule(stat="W", points=5.0, pool=PlayerPool.PITCHER),
        PointRule(stat="SV", points=5.0, pool=PlayerPool.PITCHER),
        PointRule(stat="ER", points=-2.0, pool=PlayerPool.PITCHER),
        PointRule(stat="BB", points=-0.5, pool=PlayerPool.PITCHER),
        PointRule(stat="H_ALLOWED", points=-0.5, pool=PlayerPool.PITCHER),
    ),
}


# --- Lookup Functions ---

def get_categories(ids: list[str]) -> list[CategorySpec]:
    """Look up CategorySpec objects by their IDs. Unknown IDs are skipped."""
    return [_ALL_CATEGORIES[cat_id] for cat_id in ids if cat_id in _ALL_CATEGORIES]


def get_split_pitching_categories(ids: list[str]) -> list[CategorySpec]:
    """For each pitching category ID, return two versions: one for STARTER, one for RELIEVER."""
    from dataclasses import replace as dc_replace
    result = []
    for cat_id in ids:
        if cat_id not in _ALL_CATEGORIES:
            continue
        cat = _ALL_CATEGORIES[cat_id]
        if cat.pool != PlayerPool.PITCHER:
            continue
        # Create SP version
        sp_cat = dc_replace(cat, id=f"SP_{cat_id}", label=f"{cat.label} (SP)", pool=PlayerPool.STARTER)
        # Create RP version
        rp_cat = dc_replace(cat, id=f"RP_{cat_id}", label=f"{cat.label} (RP)", pool=PlayerPool.RELIEVER)
        result.extend([sp_cat, rp_cat])
    return result


def get_point_rules(rules_str: str) -> list[PointRule]:
    """Parse 'HR:4,K:1,ER:-2' into PointRule objects."""
    if not rules_str.strip():
        return []
    rules = []
    for pair in rules_str.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        stat, points = pair.rsplit(":", 1)
        rules.append(PointRule(stat=stat.strip(), points=float(points.strip())))
    return rules
