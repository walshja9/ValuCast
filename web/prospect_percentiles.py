"""Percentile context, captions, movers, and scouting reads for prospect cards.

Pool = feed prospects with current MiLB stat context, combined across every
level. Hitter percentiles require 100+ PA; pitcher percentiles require 20+ IP.
Percentiles are not age- or level-adjusted. Pure functions over ranking rows;
no I/O. Built once at app startup.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from hashlib import blake2s

HITTER_METRICS = ("avg", "obp", "slg", "ops", "iso", "k_pct", "bb_pct")
PITCHER_METRICS = ("era", "whip", "k_per_9", "bb_per_9", "k_bb_pct")
METRICS = HITTER_METRICS + PITCHER_METRICS
LOWER_IS_BETTER = frozenset({"k_pct", "era", "whip", "bb_per_9"})
MIN_PA = 100
MIN_IP = 20
CAPTION_METRICS = ("ops", "k_pct", "iso", "k_per_9", "bb_per_9", "k_bb_pct")
HITTER_PROFILE_ORDER = ("ops", "iso", "bb_pct", "k_pct", "avg", "obp", "slg")
PITCHER_PROFILE_ORDER = ("k_per_9", "bb_per_9", "k_bb_pct", "era", "whip")
HITTER_SKILL_SPECS = (
    ("Hit", ("avg", "k_pct")),
    ("Power", ("iso", "slg")),
    ("Approach", ("bb_pct", "k_pct")),
    ("Production", ("ops",)),
)
PITCHER_SKILL_SPECS = (
    ("Miss", ("k_per_9",)),
    ("Command", ("bb_per_9",)),
    ("Dominance", ("k_bb_pct",)),
    ("Run Prevention", ("era", "whip")),
)
METRIC_LABELS = {
    "avg": "AVG",
    "obp": "OBP",
    "slg": "SLG",
    "ops": "OPS",
    "iso": "ISO",
    "k_pct": "K%",
    "bb_pct": "BB%",
    "era": "ERA",
    "whip": "WHIP",
    "k_per_9": "K/9",
    "bb_per_9": "BB/9",
    "k_bb_pct": "K-BB%",
}

# Percentile here is ALWAYS quality-direction: high percentile = good,
# so k_pct values are inverted before banding.
_CAPTIONS = {
    "ops": ((90, "Elite all-around production"), (75, "Strong all-around production"),
            (10, "Bottom-tier production in the qualified pool"),
            (25, "Production trails the qualified pool")),
    "k_pct": ((90, "Elite bat-to-ball — rarely strikes out"), (75, "Advanced contact skills"),
              (10, "Serious swing-and-miss risk"), (25, "Swing-and-miss concerns")),
    "iso": ((90, "Elite raw power output"), (75, "Real power in the profile"),
            (10, "Minimal power impact"), (25, "Light power so far")),
    "k_per_9": ((90, "Elite bat-missing"), (75, "Strong bat-missing"),
                (10, "Below-pool bat-missing"), (25, "Strikeout rate trails the pool")),
    "bb_per_9": ((90, "Elite strike throwing"), (75, "Strong strike throwing"),
                 (10, "Walk rate is a major risk"), (25, "Walk rate trails the pool")),
    "k_bb_pct": ((90, "Elite strikeout-to-walk profile"), (75, "Strong strikeout-to-walk profile"),
                 (10, "Strikeout-to-walk profile is a risk"), (25, "Strikeout-to-walk trails the pool")),
}

_LEVEL_NAMES = {
    "A": "Single-A",
    "A+": "High-A",
    "AA": "Double-A",
    "AAA": "Triple-A",
    "MLB": "the majors",
}
_YOUNG_FOR_LEVEL = {
    "A": 18,
    "A+": 19,
    "AA": 20,
    "AAA": 21,
    "MLB": 22,
}


def exceptionally_young_for_level(age, level):
    """Board-badge cut: a full year inside the young-for-level line. Rare by
    design (~7 of the top 300) so the chip stays a signal, not decoration —
    the plain <= threshold cut tagged 19 of the top 50 (7/3)."""
    if age is None or not level or str(level) == "MLB":
        return False
    threshold = _YOUNG_FOR_LEVEL.get(str(level))
    return threshold is not None and age <= threshold - 1


class CardLineSelection(tuple):
    """Three-value card_line result with source metadata for display labels."""

    def __new__(cls, line, level, is_best, *, is_combined: bool = False):
        obj = super().__new__(cls, (line, level, is_best))
        obj.is_combined = is_combined
        return obj

    @property
    def line(self):
        return self[0]

    @property
    def level(self):
        return self[1]

    @property
    def is_best(self):
        return self[2]

    @property
    def source_kind(self) -> str | None:
        if self.is_combined:
            return "combined_season_line"
        if self.is_best:
            return "best_single_level_stat_line"
        if self.line:
            return "current_minor_league_line"
        return None


def _stable_choice(row, family: str, options: tuple[str, ...]) -> str:
    """Player-stable copy variation without random or generated text."""
    key = f"{getattr(row, 'id', '')}|{getattr(row, 'name', '')}|{family}"
    index = int.from_bytes(blake2s(key.encode(), digest_size=2).digest(), "big") % len(options)
    return options[index]


def _number(line: dict, key: str) -> float | None:
    value = line.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _has_stat_values(line) -> bool:
    """True when the line carries at least one readable hitter/pitcher metric.

    A sample-only or empty dict is not a performance sample, so it must not block the
    honest no-sample read; a thin line with real rates is a small-sample read instead."""
    if not isinstance(line, dict) or not line:
        return False
    return any(isinstance(line.get(metric), (int, float)) for metric in METRICS)


def _performance_line(row) -> tuple[dict, bool]:
    """Best available performance line and whether it came from translation data.

    Prefers the card_line the bars/label use. When no line clears the percentile-pool
    floor but a real current stat_line exists, narrate THAT line as a small-sample read
    rather than the absolute "no evidence" template — being below the bar floor is not
    the same as having no performance sample (a scored top-200 prospect always has one).
    """
    selection = card_line(row)
    if selection.line:
        return selection.line, False
    if _has_stat_values(row.stat_line):
        return row.stat_line, False
    translated = row.stat_line_translated or {}
    line = {
        stat.get("key"): stat.get("milb")
        for stat in translated.get("stats", ())
        if isinstance(stat, dict) and isinstance(stat.get("milb"), (int, float))
    }
    return line, bool(line)


def _is_pitcher(row, line: dict) -> bool:
    if any(key in line for key in ("era", "whip", "k_per_9", "bb_per_9", "k_bb_pct")):
        return True
    if any(key in line for key in ("avg", "obp", "slg", "ops", "iso", "k_pct", "bb_pct")):
        return False
    return any(pos in {"P", "SP", "RP"} for pos in row.positions)


def _hitter_parts(row, line: dict) -> tuple[str, str, str]:
    k_pct = _number(line, "k_pct")
    bb_pct = _number(line, "bb_pct")
    iso = _number(line, "iso")
    ops = _number(line, "ops")

    if iso is not None and iso >= 0.250 and k_pct is not None and k_pct >= 27:
        skill = (
            "The damage is the carrying tool.",
            "He punishes mistakes often enough to carry the bat.",
            "The power is the reason to stay on him.",
        )
        risk = (
            "Too many at-bats still end without contact.",
            "Better pitching can keep the power in the dugout with empty swings.",
            "The failure point is contact frequency.",
        )
        role = (
            "Everyday middle-order ceiling. The current contact points to a low-average bench-power floor.",
            "Lean everyday power bat, but the miss rate keeps a bench outcome in play.",
        )
        family = "hitter-power-risk"
    elif iso is not None and iso >= 0.220 and bb_pct is not None and bb_pct >= 13:
        skill = (
            "He gets into damage counts without chasing his way out of them.",
            "Pitchers have to come into the zone, and he makes those pitches hurt.",
            "The power and patience reinforce each other.",
        )
        if k_pct is not None and k_pct >= 25:
            risk = (
                "The miss rate can still make the batting average volatile.",
                "Contact is the pressure point against better pitching.",
            )
        else:
            risk = (
                "Nothing in the current line gives pitchers an obvious way to attack him; upper-level translation is the remaining test.",
                "The current line has no clear weakness; the risk is that the power backs up against better pitching.",
            )
        role = (
            "Everyday middle-order regular. The walks give him a useful floor through a power dip.",
            "The current-performance ceiling scenario is an everyday run-producing bat, with on-base value protecting the floor.",
        )
        family = "hitter-power-patience"
    elif k_pct is not None and k_pct <= 17 and iso is not None and iso < 0.140:
        skill = (
            "He barely strikes out.",
            "The ball stays in play.",
            "He consistently finishes at-bats with contact.",
        )
        risk = (
            "Pitchers have little reason to avoid the zone.",
            "The current damage limits the profile's impact.",
        )
        role = (
            "Contact-first table-setter shape. The present damage still resembles a light-hitting reserve.",
            "Contact-first table-setter shape, with present damage that still looks reserve-level.",
        )
        family = "hitter-contact-light-power"
    elif k_pct is not None and k_pct <= 17:
        skill = (
            "He consistently finishes at-bats with contact.",
            "He barely strikes out.",
            "He does not give away many plate appearances.",
        )
        if bb_pct is not None and bb_pct < 8:
            risk = (
                "He rarely walks, leaving little margin when the contact quality backs up.",
                "The offensive value remains tied closely to the hit tool because he does not take many free passes.",
            )
        else:
            risk = (
                "The open question is damage against better pitching.",
                "The open question is damage.",
            )
        role = (
            "Everyday contact regular. High-contact bench floor.",
            "Everyday contact regular, with a useful reserve floor.",
        )
        family = "hitter-contact"
    elif iso is not None and iso >= 0.180 and k_pct is not None and k_pct >= 25:
        skill = (
            "He punishes mistakes when he gets the barrel there.",
            "The damage plays in games.",
            "There is enough power to keep pitchers honest.",
        )
        risk = (
            "The miss rate keeps that power from showing up consistently.",
            "Better pitching can still beat him with empty swings.",
        )
        role = (
            "Everyday power ceiling, with a volatile bench-bat floor until the contact improves.",
            "The contact points to a reserve today, but the damage leaves an everyday path open.",
        )
        family = "hitter-impact-contact-risk"
    elif bb_pct is not None and bb_pct >= 15 and k_pct is not None and k_pct >= 26:
        skill = (
            "He extends at-bats and forces pitchers into the zone.",
            "He reaches base without chasing his way out of counts.",
        )
        risk = (
            "He is not finishing enough of those at-bats with contact.",
            "The miss rate leaves the hit tool exposed despite the walks.",
        )
        role = (
            "On-base regular ceiling. The current miss rate leaves a walk-dependent bench floor.",
            "The walks keep an everyday path open, but the contact points to a narrow reserve role today.",
        )
        family = "hitter-patience-contact-risk"
    elif (
        iso is not None and iso < 0.150
        and k_pct is not None and k_pct <= 22
        and bb_pct is not None and bb_pct >= 9
    ):
        skill = (
            "He controls at-bats and keeps the ball in play.",
            "He rarely gives pitchers an easy plate appearance.",
        )
        risk = (
            "The lack of damage is the limiting factor.",
            "Pitchers do not have to change their plan for his power.",
        )
        role = (
            "Low-end everyday regular ceiling, but the current damage points to a low-impact bench floor.",
            "The approach fits a reserve role today; more damage is required for everyday work.",
        )
        family = "hitter-contact-approach-light-power"
    elif bb_pct is not None and bb_pct >= 13:
        skill = (
            "He works deep counts and gets on base.",
            "He forces pitchers into the zone and takes the free pass.",
        )
        if iso is not None and iso < 0.150:
            risk = (
                "The light damage makes the offensive outcome dependent on maintaining those walks.",
                "Pitchers may challenge him more often until the damage improves.",
            )
        else:
            risk = (
                "The line does not show a second offensive strength at the same level.",
                "The risk is that better pitching reduces the walks without another loud offensive result replacing them.",
            )
        role = (
            "Lower-order regular ceiling. The current floor is a bench bat without more damage.",
            "The walks create an everyday path, but the present outcome is a reserve.",
        )
        family = "hitter-patience"
    elif iso is not None and iso >= 0.220:
        skill = (
            "The bat has a clear source of damage.",
            "He is producing enough game power to matter.",
        )
        risk = (
            "The line does not show a second offensive strength to protect the power.",
            "Better pitching can leave him without a second way to contribute.",
        )
        role = (
            "Everyday power ceiling. The current floor is a bench bat used for damage.",
            "The power keeps a regular role open, but the present floor is a one-dimensional reserve.",
        )
        family = "hitter-power"
    elif k_pct is not None and k_pct >= 30:
        skill = (
            "No offensive result currently offsets the amount of swing-and-miss.",
            "The current line does not identify a dependable offensive strength.",
        )
        risk = (
            "The miss rate gives the bat very little margin.",
            "Too many plate appearances end without contact.",
        )
        role = (
            "He needs a major contact gain to reach an everyday role; the current floor is organizational depth.",
            "The present outcome is below an everyday bat. A bench role requires another offensive result to emerge.",
        )
        family = "hitter-contact-risk"
    elif (
        ops is not None and ops >= 0.820
        and iso is not None and bb_pct is not None and k_pct is not None
    ):
        skill = (
            "He is contributing across contact, walks and damage rather than leaning on one result.",
            "He controls at-bats and does damage without leaning on one result.",
        )
        risk = (
            "No single result is loud enough to carry the bat through regression elsewhere.",
            "The risk is a broad but ordinary offensive line without one result that forces an everyday role.",
        )
        role = (
            "The current-performance ceiling scenario is a low-end everyday regular who contributes across categories, with a useful bench-bat floor.",
            "This reads as a broad-based regular outcome, with enough across-the-board value to retain a reserve floor.",
        )
        family = "hitter-balanced"
    else:
        skill = (
            "No offensive result currently separates from the rest of the line.",
            "The current line does not identify a dependable offensive strength.",
        )
        risk = (
            "Without a clear source of contact, walks or damage, better pitching has multiple ways to attack him.",
            "The risk is that an ordinary offensive line leaves no path to regular playing time.",
        )
        role = (
            "The current line does not support an everyday outcome; the floor is organizational depth.",
            "The current outcome is below a regular role, with a bench path dependent on one offensive result separating.",
        )
        family = "hitter-developing"
    return (
        _stable_choice(row, f"{family}-skill", skill),
        _stable_choice(row, f"{family}-risk", risk),
        _stable_choice(row, f"{family}-role", role),
    )


def _pitcher_parts(row, line: dict) -> tuple[str, str, str]:
    k_per_9 = _number(line, "k_per_9")
    bb_per_9 = _number(line, "bb_per_9")
    era = _number(line, "era")
    whip = _number(line, "whip")
    k_bb_pct = _number(line, "k_bb_pct")

    if k_per_9 is not None and k_per_9 >= 12.5 and bb_per_9 is not None and bb_per_9 <= 2.5:
        skill = (
            "He misses bats without giving away counts.",
            "Hitters have to earn their way on, and he can finish them.",
        )
        risk = (
            "Nothing in the current line argues against starting; the remaining risk is upper-level translation.",
            "Nothing in the line points to a weakness yet; the next level is the real test.",
        )
        role = (
            "Mid-rotation lean, with a back-end starter floor.",
            "Current-performance ceiling scenario: mid-rotation starter.",
        )
        family = "pitcher-dominant-control"
    elif k_per_9 is not None and k_per_9 >= 12 and bb_per_9 is not None and bb_per_9 >= 4.5:
        skill = (
            "The bat-missing is starter-caliber.",
            "The swing-and-miss is real enough to keep a rotation path open.",
        )
        risk = (
            "The walks are the separator, not the stuff.",
            "The stuff is ahead of the strike throwing right now.",
        )
        role = (
            "Starter upside is still alive, but the current command creates real bullpen risk.",
            "Keep the starter path open, but the walk rate has to move before the bullpen risk fades.",
        )
        family = "pitcher-stuff-control-risk"
    elif k_per_9 is not None and k_per_9 >= 11.5:
        skill = (
            "He misses enough bats to keep a rotation outcome open.",
            "He has a dependable way to finish hitters.",
        )
        if bb_per_9 is not None and bb_per_9 >= 3.5:
            risk = (
                "The walks keep the starter projection from firming up.",
                "He still gives away too many counts.",
            )
        else:
            risk = (
                "The strike throwing is adequate now; upper-level translation is the remaining test.",
                "The main risk is whether the bat-missing holds against better hitters.",
            )
        role = (
            "Rotation lean. The strike throwing decides whether it holds.",
            "Keep developing him as a starter, with the bullpen as the fallback.",
        )
        family = "pitcher-bat-missing"
    elif bb_per_9 is not None and bb_per_9 <= 2.5 and k_per_9 is not None:
        skill = (
            "He limits free passes and consistently forces hitters to earn contact.",
            "The strike throwing is the reason to keep him on a starter track.",
        )
        risk = (
            "The lack of misses leaves little margin when hitters square the ball.",
            "He does not finish enough hitters to own the middle of a rotation.",
        )
        role = (
            "Back-end starter lean, with a swingman or low-leverage bullpen floor.",
            "The control supports a starter look. The lack of misses keeps the bullpen in play.",
        )
        family = "pitcher-control"
    elif era is not None and era <= 3.00 and whip is not None and whip <= 1.15:
        skill = (
            "He is preventing runs and keeping traffic off the bases.",
            "The current results are clean.",
        )
        if k_per_9 is not None:
            risk = (
                "The current line does not show dominant bat-missing, making the next level the key test.",
                "The results are ahead of the bat-missing, leaving less margin against better hitters.",
            )
        else:
            risk = (
                "The current line does not include a bat-missing result, making the next level the key test.",
                "The available line leaves the bat-missing unverified, so the run prevention carries most of the projection.",
            )
        role = (
            "Back-end rotation path, with a multi-inning bullpen floor.",
            "The present outcome is a back-end starter. The bullpen is the fallback.",
        )
        family = "pitcher-results"
    else:
        skill = (
            "Nothing in the profile gives him a dependable way through a lineup yet.",
            "There's no repeatable way to retire hitters in the line yet.",
        )
        rate_detail = "the strikeout-to-walk result" if k_bb_pct is not None else "the current strikeout and walk results"
        risk = (
            f"The failure point is {rate_detail}, which does not support a firm starter projection.",
            f"Neither misses nor strikes separate in {rate_detail}.",
        )
        role = (
            "A rotation role is not supported by the current line; the floor is organizational depth or a low-leverage bullpen assignment.",
            "The role remains unsettled, with a bullpen outcome more likely until either strikes or misses improve.",
        )
        family = "pitcher-developing"
    return (
        _stable_choice(row, f"{family}-skill", skill),
        _stable_choice(row, f"{family}-risk", risk),
        _stable_choice(row, f"{family}-role", role),
    )


def _row_context(row) -> dict:
    context = getattr(row, "context", None)
    if isinstance(context, dict):
        return context
    metadata = getattr(row, "metadata", None)
    if isinstance(metadata, dict) and isinstance(metadata.get("context"), dict):
        return metadata["context"]
    return {}


def _availability_context(row) -> dict:
    context = getattr(row, "availability_context", None)
    if isinstance(context, dict):
        return context
    if callable(context):
        value = context()
        return value if isinstance(value, dict) else {}
    return {}


def _updated_year(row) -> int | None:
    metadata = getattr(row, "metadata", None)
    candidates = []
    if isinstance(metadata, dict):
        candidates.extend([metadata.get("last_updated"), metadata.get("updated_at")])
    candidates.append(getattr(row, "updated_at", None))
    for candidate in candidates:
        text = str(candidate or "")[:4]
        if text.isdigit():
            return int(text)
    return None


def _sample_season(row, translated: dict) -> int | None:
    season = translated.get("season") or _row_context(row).get("stat_line_sample_season")
    try:
        return int(float(season))
    except (TypeError, ValueError):
        return None


def _sample_context(row, line: dict, from_translation: bool) -> str:
    translated = row.stat_line_translated or {}
    pitcher = _is_pitcher(row, line)
    sample = _number(line, "ip" if pitcher else "pa")
    if sample is None:
        sample = _number(line, "sample")
    if sample is None:
        raw_sample = translated.get("sample")
        sample = float(raw_sample) if isinstance(raw_sample, (int, float)) else None
    unit = str(line.get("sample_unit") or ("IP" if pitcher else "PA"))
    season = translated.get("season")
    updated_year = str(row.metadata.get("last_updated") or "")[:4]
    old = (
        from_translation
        and isinstance(season, int)
        and updated_year.isdigit()
        and season < int(updated_year)
    )
    low_sample = bool(translated.get("low_sample"))
    if sample is not None and not translated:
        low_sample = sample < (30 if pitcher else 100)
    confidence = str(translated.get("confidence") or "moderate").lower()
    if confidence not in {"high", "moderate", "low"}:
        confidence = "moderate"
    context = _row_context(row)
    source_kind = str(context.get("stat_line_source_kind") or "")
    season = _sample_season(row, translated)
    updated_year = _updated_year(row)
    stale_direct_sample = (
        source_kind == "latest_milb_history"
        or (
            season is not None
            and updated_year is not None
            and season < updated_year
        )
    )
    old = old or stale_direct_sample
    availability = _availability_context(row)
    status = str(availability.get("status") or "").lower()
    if old or low_sample or status == "injured":
        confidence = "low"

    line_level = line.get("level")
    display_level = line_level if isinstance(line_level, str) and line_level else row.level
    # A combined multi-level line's sample spans EVERY level it pooled. Label it with all
    # of them, not just the highest -- otherwise "235 PA" (133 AAA + 102 AA) reads as
    # "235 PA in Triple-A" when only 133 were at Triple-A.
    sample_levels = line.get("levels")
    if not (isinstance(sample_levels, list) and sample_levels):
        sample_levels = translated.get("levels")
    named_levels = (
        [_LEVEL_NAMES.get(lv, lv) for lv in sample_levels if lv]
        if isinstance(sample_levels, list) else []
    )
    if len(named_levels) > 1:
        level = (
            " and ".join(named_levels)
            if len(named_levels) == 2
            else ", ".join(named_levels[:-1]) + f", and {named_levels[-1]}"
        )
    else:
        level = _LEVEL_NAMES.get(display_level, display_level)
    sample_text = f"{sample:g} {unit}" if sample is not None else "the available sample"
    if status == "injured":
        if old and season:
            return f"He is currently injured; the latest meaningful sample is from {season}, so confidence is low."
        return "He is currently injured, so availability risk is priced into the score and confidence is low."
    if old:
        if season:
            return f"The latest meaningful sample is from {season}, so confidence is low."
        return "The latest meaningful sample is prior-season context, so confidence is low."
    if low_sample:
        location = " in the latest MiLB sample" if display_level == "MLB" else (f" in {level}" if level else "")
        return f"Only {sample_text}{location}, so confidence is low."
    if display_level == "MLB":
        return f"The latest MiLB sample covers {sample_text}, so confidence is {confidence}."
    if (
        row.age is not None
        and display_level
        and display_level != "MLB"
        and row.age <= _YOUNG_FOR_LEVEL.get(display_level, -1)
    ):
        return f"He is {row.age} in {level} over {sample_text}, so confidence is {confidence}."
    return f"The sample covers {sample_text}{f' in {level}' if level else ''}, so confidence is {confidence}."


def _dict_context(row, attr: str, *metadata_keys: str) -> dict:
    raw = getattr(row, attr, None)
    if isinstance(raw, dict):
        return raw
    if callable(raw):
        raw = raw()
        if isinstance(raw, dict):
            return raw
    metadata = getattr(row, "metadata", None)
    if isinstance(metadata, dict):
        for key in metadata_keys:
            raw = metadata.get(key)
            if isinstance(raw, dict):
                return raw
    return {}


def _float_value(raw) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _display_number(raw) -> str:
    value = _float_value(raw)
    return f"{value:g}" if value is not None else str(raw)


_SHORTENED_GAMES_MAX = 90
_SHORTENED_MIN_PA = 200
_SHORTENED_MIN_IP = 50


def _shortened_recent_season(exposure) -> dict | None:
    """The model penalizes age-for-level but can't see WHY a prospect is old for it.
    Given a player's season exposure ({draft_year, seasons:[{season,games,unit,sample}]}),
    return the most recent COMPLETED season that ran short of a full slate despite a real
    workload -- lost development time, not a stall -- else None. Conservative: the season
    must be after the draft year (not a normal draft-summer debut) and recent enough to
    explain the current age/level."""
    if not isinstance(exposure, dict):
        return None
    seasons = [e for e in (exposure.get("seasons") or []) if isinstance(e, dict)]
    if not seasons:
        return None
    current = max(e["season"] for e in seasons)
    completed = [e for e in seasons if e["season"] < current]
    if not completed:
        return None
    target = max(completed, key=lambda e: e["season"])
    if current - target["season"] > 2:
        return None
    draft_year = exposure.get("draft_year")
    if draft_year is not None:
        if target["season"] <= draft_year:  # the draft summer is a normal partial season
            return None
    elif not any(e["season"] < target["season"] for e in seasons):
        return None  # no draft year and target is the debut -> can't tell
    games = target.get("games") or 0
    sample = target.get("sample") or 0
    floor = _SHORTENED_MIN_PA if target.get("unit") == "PA" else _SHORTENED_MIN_IP
    if games < _SHORTENED_GAMES_MAX and sample >= floor:
        return {"season": target["season"], "games": games}
    return None


def value_suppressor_note(row, percentiles, exposure=None) -> str | None:
    peaks = [
        p
        for p in (percentiles.values() if isinstance(percentiles, dict) else ())
        if isinstance(p, int)
    ]
    elite_skill = any(p >= 90 for p in peaks) and sum(1 for p in peaks if p >= 75) >= 2

    value = _float_value(getattr(row, "dynasty_value", None))
    if value is None:
        value = 0.0
    prospect_rank = getattr(row, "prospect_rank", None)
    rank_value = _float_value(prospect_rank)
    low_rank = rank_value is not None and rank_value >= 250
    low_value = value <= 8.0 or low_rank

    peak = _dict_context(row, "peak_projection_context", "peak_projection_context", "peak_projection")
    peak_role = str(peak.get("peak_role") or "")
    capped = (
        str(peak.get("peak_role") or peak.get("ceiling_band") or "")
        in {
            "depth_arm",
            "organizational_depth",
            "multi_inning_or_setup_arm",
            "bench_or_platoon_bat",
        }
        or str(peak.get("risk_band")) == "high"
    )
    if not (elite_skill and low_value and capped):
        return None

    reasons = []
    age = getattr(row, "age", None)
    age_value = _float_value(age)
    level = getattr(row, "level", None)
    if age_value is not None and level in _YOUNG_FOR_LEVEL and age_value >= _YOUNG_FOR_LEVEL[level] + 2:
        level_name = _LEVEL_NAMES.get(level, level)
        reasons.append(f"he's old for {level_name} ({_display_number(age)})")

    components = _dict_context(row, "prospect_components", "components")
    factual_current = _dict_context(row, "factual_current_context")
    sample = factual_current.get("sample")
    sample_number = _float_value(sample)
    unit = factual_current.get("sample_unit")
    skill_band = factual_current.get("skill_band")
    reliability = _float_value(components.get("sample_reliability"))
    thin = (
        sample_number is not None
        and ((unit == "IP" and sample_number < 40) or (unit == "PA" and sample_number < 120))
    ) or str(skill_band) in {"thin", "limited"} or (
        reliability is not None and reliability < 45
    )
    if thin:
        if sample_number is not None and unit:
            reasons.append(f"the sample is still thin ({sample_number:g} {unit})")
        else:
            reasons.append("the sample is still thin")

    modest_ceiling = peak_role in {
        "depth_arm",
        "organizational_depth",
        "multi_inning_or_setup_arm",
        "bench_or_platoon_bat",
    }
    role_from_context = str(factual_current.get("role") or "")
    is_pitcher = role_from_context == "pitcher" or (
        not role_from_context and _is_pitcher(row, getattr(row, "stat_line", None) or {})
    )
    if modest_ceiling:
        if is_pitcher:
            reasons.append("the profile projects as a depth/relief arm rather than a rotation piece")
        else:
            reasons.append("the projection caps at a bench/depth role")

    investment = components.get("factual_investment_context")
    score = investment.get("score") if isinstance(investment, dict) else None
    score = _float_value(score)
    if score is not None and score < 30:
        reasons.append("the draft pedigree is modest")

    reasons = reasons[:2]
    if not reasons:
        return None
    why = reasons[0] if len(reasons) == 1 else f"{reasons[0]} and {reasons[1]}"
    note = f"The current skills grade out loud, but the dynasty value stays low because {why}."
    if any(reason.startswith("he's old for") for reason in reasons):
        short = _shortened_recent_season(exposure)
        if short:
            note = (
                f"{note} That said, his {short['season']} season ran just {short['games']} "
                "games, so the age reflects lost development time more than a stall."
            )
    return note


def _report_order(row) -> int:
    if isinstance(row.prospect_rank, int):
        return (row.prospect_rank - 1) % 4
    return int.from_bytes(
        blake2s(f"{row.id}|order".encode(), digest_size=1).digest(), "big"
    ) % 4


def _report_shape(row) -> int:
    """Return a stable 2-4 sentence shape with deliberate length variance."""
    if isinstance(row.prospect_rank, int):
        bucket = (row.prospect_rank - 1) % 10
    else:
        bucket = int.from_bytes(
            blake2s(f"{row.id}|shape".encode(), digest_size=1).digest(), "big"
        ) % 10
    if bucket in {0, 4, 8}:
        return 2
    if bucket in {1, 2, 5, 6}:
        return 3
    return 4


def _clause(text: str, *, lower: bool = False) -> str:
    pieces = text.strip().rstrip(".").split(". ")
    text = "; ".join(
        piece if index == 0 else piece[0].lower() + piece[1:]
        for index, piece in enumerate(pieces)
        if piece
    )
    if lower and text:
        text = text[0].lower() + text[1:]
    return text


def _sentence(*parts: str) -> str:
    return "; ".join(
        _clause(part, lower=index > 0)
        for index, part in enumerate(parts)
        if part
    ) + "."


def _assemble_parts(parts: tuple[str, str, str, str], shape: int) -> str:
    if shape == 2:
        return f"{_sentence(*parts[:2])} {_sentence(*parts[2:])}"
    if shape == 3:
        return f"{_sentence(*parts[:2])} {_sentence(parts[2])} {_sentence(parts[3])}"
    return " ".join(_sentence(part) for part in parts)


def _assemble_report(row, skill: str, risk: str, role: str, context: str) -> str:
    orders = (
        (skill, risk, role, context),
        (risk, skill, role, context),
        (role, skill, risk, context),
        (context, skill, risk, role),
    )
    return _assemble_parts(orders[_report_order(row)], _report_shape(row))


def _no_sample_report(row) -> str:
    pos = row.positions[0] if row.positions else "prospect"
    descriptor = f"{row.age}-year-old {pos}" if row.age is not None else f"{pos} prospect"
    if any(position in {"P", "SP", "RP"} for position in row.positions):
        unknown = _stable_choice(row, "no-sample-pitcher-risk", (
            "The bat-missing and strike-throwing are unverified.",
            "We cannot verify either the misses or the strikes.",
            "There is no current evidence for how he gets hitters out.",
        ))
        role = _stable_choice(row, "no-sample-pitcher-role", (
            "No rotation call is supported; the floor is organizational depth until there is a current sample to read.",
            "There is no basis for a rotation call; treat him as organizational depth until current results arrive.",
            "Hold the role call. The only supported floor today is organizational depth.",
        ))
        return _assemble_parts(
            (
                f"No current performance sample is available for this {descriptor}.",
                unknown,
                role,
                "Anything stronger is projection. Confidence: low.",
            ),
            _report_shape(row),
        )
    unknown = _stable_choice(row, "no-sample-hitter-risk", (
        "The offensive strength and primary failure point are unverified.",
        "We cannot identify either the offensive driver or the failure point.",
        "There is no current evidence for how the bat produces.",
    ))
    role = _stable_choice(row, "no-sample-hitter-role", (
        "No everyday call is supported; the floor is organizational depth until there is a current sample to read.",
        "There is no basis for an everyday call; treat him as organizational depth until current results arrive.",
        "Hold the role call. The only supported floor today is organizational depth.",
    ))
    return _assemble_parts(
        (
            f"No current performance sample is available for this {descriptor}.",
            unknown,
            role,
            "Anything stronger is projection. Confidence: low.",
        ),
        _report_shape(row),
    )


def _line_sample_for_role(line: dict, role_is_pitcher: bool) -> float | None:
    sample = line.get("ip" if role_is_pitcher else "pa")
    if sample is None:
        sample = line.get("sample")
    return float(sample) if isinstance(sample, (int, float)) else None


def _clears_sample_floor(line: dict, role_is_pitcher: bool) -> bool:
    sample = _line_sample_for_role(line, role_is_pitcher)
    floor = MIN_IP if role_is_pitcher else MIN_PA
    return sample is not None and sample >= floor


def build_pool(rows) -> dict[str, list[float]]:
    """Sorted per-metric value arrays over eligible prospects, ranked on each
    player's CARD LINE (combined season line when present, else current-level or
    best-single line) so the pool and the displayed bars draw from one source.
    Falling back through card_line keeps the pool populated before the snapshot
    rebuild attaches combined lines (otherwise the bars would have no pool)."""
    pool: dict[str, list[float]] = {m: [] for m in METRICS}
    for row in rows:
        line = card_line(row).line
        if line is None:
            continue
        metrics = PITCHER_METRICS if _is_pitcher(row, line) else HITTER_METRICS
        for m in metrics:
            v = line.get(m)
            if isinstance(v, (int, float)):
                pool[m].append(float(v))
    return {m: sorted(vs) for m, vs in pool.items() if vs}


def percentile_for(pool: dict, metric: str, value) -> int | None:
    """Midrank percentile of value within the pool, quality-direction, clamped 1..99."""
    values = pool.get(metric)
    if not values or not isinstance(value, (int, float)):
        return None
    v = float(value)
    below = bisect_left(values, v)
    ties = bisect_right(values, v) - below
    pct = 100.0 * (below + 0.5 * ties) / len(values)
    if metric in LOWER_IS_BETTER:
        pct = 100.0 - pct
    return max(1, min(99, round(pct)))


def card_line(row) -> CardLineSelection:
    """The stat line the card reads percentiles/skill-shape from, its level label, and
    whether it is the best-single-level fallback. Combined season line if it clears the
    sample threshold; else current-level line; else best single-level line; else (None,
    None, False). The selected line is raw MiLB data, so it ranks
    against the same raw pool — only labeled with its own level, not the current one."""
    if not getattr(row, "is_prospect", False):
        return CardLineSelection(None, None, False)
    combined = getattr(row, "combined_season_stat_line", None)
    if isinstance(combined, dict) and combined:
        role_is_pitcher = _is_pitcher(row, combined)
        if _clears_sample_floor(combined, role_is_pitcher):
            return CardLineSelection(
                combined,
                combined.get("level_label") or combined.get("level"),
                False,
                is_combined=True,
            )
    line = row.stat_line or {}
    role_is_pitcher = _is_pitcher(row, line)
    if line and _clears_sample_floor(line, role_is_pitcher):
        return CardLineSelection(line, None, False)
    best = getattr(row, "best_single_level_stat_line", None)
    if isinstance(best, dict) and best:
        if _clears_sample_floor(best, role_is_pitcher):
            return CardLineSelection(best, best.get("level"), True)
    return CardLineSelection(None, None, False)


def card_percentiles(pool: dict, row) -> dict[str, int]:
    """{metric: percentile} for the card's selected line; {} when no line clears."""
    selection = card_line(row)
    line = selection.line
    if line is None:
        return {}
    metrics = PITCHER_METRICS if _is_pitcher(row, line) else HITTER_METRICS
    out = {}
    for m in metrics:
        pct = percentile_for(pool, m, line.get(m))
        if pct is not None:
            out[m] = pct
    return out


def pool_label(row) -> str:
    """Display label for the percentile comparison pool."""
    selection = card_line(row)
    line = selection.line
    role_is_pitcher = _is_pitcher(row, line if line is not None else (row.stat_line or {}))
    base = (
        f"pitcher pool - {MIN_IP}+ IP"
        if role_is_pitcher
        else f"hitter pool - {MIN_PA}+ PA"
    )
    if selection.is_combined and isinstance(line, dict):
        season = line.get("season")
        if season:
            return f"{base} - combined {season} line"
        return f"{base} - combined season line"
    if selection.is_best and selection.level:
        return f"{base} - best {selection.level} read"
    return base


def profile_bars(row, percentiles: dict) -> tuple[dict, ...]:
    """Ordered profile bars for the expanded player card."""
    # Read the SAME line card_percentiles/pool_label use, so the displayed value
    # matches the percentile fill and label.
    selection = card_line(row)
    line = selection.line
    if not line or not percentiles:
        return ()
    order = PITCHER_PROFILE_ORDER if _is_pitcher(row, line) else HITTER_PROFILE_ORDER
    bars = []
    for metric in order:
        value = line.get(metric)
        pct = percentiles.get(metric)
        if not isinstance(value, (int, float)) or pct is None:
            continue
        bars.append({
            "key": metric,
            "label": METRIC_LABELS.get(metric, metric.upper()),
            "value": value,
            "percentile": pct,
            "caption": caption_for(metric, pct),
        })
    return tuple(bars)


def _grade_from_pcts(pcts: list[int]) -> int | None:
    if not pcts:
        return None
    avg = sum(pcts) / len(pcts)
    return round(max(20.0, min(80.0, 20.0 + avg * 0.6)))


def skill_grades(row, percentiles: dict) -> tuple[dict, ...]:
    """20-80-style current skill shape derived from ValuCast percentiles."""
    selection = card_line(row)
    line = selection.line
    if not line or not percentiles:
        return ()
    specs = PITCHER_SKILL_SPECS if _is_pitcher(row, line) else HITTER_SKILL_SPECS
    grades = []
    for label, keys in specs:
        pcts = [
            int(percentiles[key])
            for key in keys
            if isinstance(percentiles.get(key), int)
        ]
        grade = _grade_from_pcts(pcts)
        if grade is None:
            continue
        grades.append({
            "label": label,
            "grade": grade,
            "metrics": " / ".join(METRIC_LABELS.get(key, key.upper()) for key in keys),
        })
    return tuple(grades)


_PEAK_LABEL_ALIASES = {"Production": "Impact"}


def _grade_to_pct(grade) -> float | None:
    if grade is None:
        return None
    return max(0.0, min(100.0, (float(grade) - 20.0) / 60.0 * 100.0))


def skill_shape_compare(grades, peak_items) -> tuple[dict, ...]:
    """One row per skill: current 20-80 grade alongside its projected peak.

    Pairs current grades to peak-shape items by label (with the hitter
    Production<->Impact alias). ``peak`` is None when no peak projection
    covers that skill. ``*_pct`` are 0-100 bar widths for the template.
    """
    peak_by_label = {p.get("label"): p for p in (peak_items or [])}
    merged = []
    for grade in grades:
        label = grade.get("label")
        peak = peak_by_label.get(label) or peak_by_label.get(
            _PEAK_LABEL_ALIASES.get(label)
        )
        current = grade.get("grade")
        peak_grade = peak.get("grade") if peak else None
        merged.append({
            "label": label,
            "metrics": grade.get("metrics"),
            "current": current,
            "peak": peak_grade,
            "current_pct": _grade_to_pct(current),
            "peak_pct": _grade_to_pct(peak_grade),
        })
    return tuple(merged)


def caption_for(metric: str, pct: int | None) -> str | None:
    """Threshold-banded caption; None in the neutral band or for non-headline metrics."""
    if pct is None or metric not in _CAPTIONS:
        return None
    bands = _CAPTIONS[metric]
    if pct >= bands[0][0]:
        return bands[0][1]
    if pct >= bands[1][0]:
        return bands[1][1]
    if pct <= bands[2][0]:
        return bands[2][1]
    if pct <= bands[3][0]:
        return bands[3][1]
    return None


def identity_line(row, percentiles: dict) -> str | None:
    """Deterministic scouting-style card summary. None for non-prospects."""
    if not row.is_prospect:
        return None
    line, from_translation = _performance_line(row)
    if not line:
        return _no_sample_report(row)
    skill, risk, role = (
        _pitcher_parts(row, line) if _is_pitcher(row, line) else _hitter_parts(row, line)
    )
    report = _assemble_report(row, skill, risk, role, _sample_context(row, line, from_translation))
    note = value_suppressor_note(row, percentiles)
    return f"{report} {note}" if note else report
