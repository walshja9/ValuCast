from __future__ import annotations

from urllib.parse import urlencode

from league_values.models import LeagueConfig, ScoringMode, PointRule

from .category_registry import (
    DEFAULT_CATS,
    DEFAULT_PCATS,
    POINTS_PRESETS,
    get_categories,
    get_point_rules,
    get_split_pitching_categories,
)


def parse_list(values: list[str]) -> list[str]:
    """Parse query param values that may be comma-separated or repeated.

    ['R,HR,RBI'] → ['R', 'HR', 'RBI']
    ['R', 'HR', 'RBI'] → ['R', 'HR', 'RBI']
    """
    if not values:
        return []
    if len(values) == 1 and "," in values[0]:
        return [v.strip() for v in values[0].split(",") if v.strip()]
    return values


def build_config(
    mode: str = "categories",
    cats: list[str] | None = None,
    pcats: list[str] | None = None,
    rules_str: str | None = None,
    pt_params: dict[str, str] | None = None,
    split_rp: bool = False,
    weights: dict[str, float] | None = None,
) -> LeagueConfig:
    """Build a LeagueConfig from URL query parameters."""
    from dataclasses import replace as dc_replace

    try:
        scoring_mode = ScoringMode(mode)
    except ValueError:
        scoring_mode = ScoringMode.CATEGORIES  # unknown mode -> default board, not a 500

    if scoring_mode is ScoringMode.POINTS:
        if pt_params:
            point_rules = tuple(
                PointRule(stat=stat, points=float(pts))
                for stat, pts in pt_params.items()
                if pts
            )
        elif rules_str:
            point_rules = tuple(get_point_rules(rules_str))
        else:
            point_rules = POINTS_PRESETS["default"]

        return LeagueConfig(
            name="Custom Points",
            scoring_mode=scoring_mode,
            point_rules=point_rules,
        )

    # Categories or Roto mode
    cat_ids = cats if cats else DEFAULT_CATS
    pcat_ids = pcats if pcats else DEFAULT_PCATS

    hitting_categories = get_categories(cat_ids)
    if split_rp:
        pitching_categories = get_split_pitching_categories(pcat_ids)
    else:
        pitching_categories = get_categories(pcat_ids)
    categories = list(hitting_categories + pitching_categories)

    # Apply weights
    if weights:
        weighted = []
        for cat in categories:
            # For split categories (SP_K, RP_K), check base ID too
            if cat.id.startswith("SP_") or cat.id.startswith("RP_"):
                base_id = cat.id[3:]
                w = weights.get(base_id, 1.0)
            else:
                w = weights.get(cat.id, 1.0)
            if w != 1.0:
                cat = dc_replace(cat, weight=w)
            weighted.append(cat)
        categories = weighted

    return LeagueConfig(
        name="Custom",
        scoring_mode=scoring_mode,
        categories=tuple(categories),
    )


def build_url_params(
    mode: str = "categories",
    cats: list[str] | None = None,
    pcats: list[str] | None = None,
    pool: str = "",
    position: str = "",
    search: str = "",
    rules_str: str = "",
    split_rp: bool = False,
    weights: dict[str, float] | None = None,
) -> str:
    """Build URL query string from current state. Returns '' for defaults."""
    params: dict[str, str] = {}

    is_default = (
        mode == "categories"
        and (not cats or cats == DEFAULT_CATS)
        and (not pcats or pcats == DEFAULT_PCATS)
        and not pool
        and not position
        and not search
        and not split_rp
        and not weights
    )
    if is_default:
        return ""

    if mode != "categories":
        params["mode"] = mode

    if mode == "points":
        if rules_str:
            params["rules"] = rules_str
    else:
        if cats and cats != DEFAULT_CATS:
            params["cats"] = ",".join(cats)
        if pcats and pcats != DEFAULT_PCATS:
            params["pcats"] = ",".join(pcats)

    if pool:
        params["pool"] = pool
    if position:
        params["position"] = position
    if search:
        params["search"] = search
    if split_rp:
        params["split_rp"] = "on"
    if weights:
        for cat_id, w in weights.items():
            if w != 1.0:
                params[f"w_{cat_id}"] = str(w)

    return urlencode(params) if params else ""
