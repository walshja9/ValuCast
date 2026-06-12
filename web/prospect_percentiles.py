"""Percentile context, captions, movers, and scouting reads for prospect cards.

Pool = feed hitter prospects with a batting stat_line and pa >= MIN_PA, combined
across every level. Percentiles are not age- or level-adjusted. Pure functions
over DynastyRankingRow; no I/O. Built once at app startup.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from hashlib import blake2s

METRICS = ("avg", "obp", "slg", "ops", "iso", "k_pct", "bb_pct")
LOWER_IS_BETTER = frozenset({"k_pct"})
MIN_PA = 100
CAPTION_METRICS = ("ops", "k_pct", "iso")

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


def _stable_choice(row, family: str, options: tuple[str, ...]) -> str:
    """Player-stable copy variation without random or generated text."""
    key = f"{getattr(row, 'id', '')}|{getattr(row, 'name', '')}|{family}"
    index = int.from_bytes(blake2s(key.encode(), digest_size=2).digest(), "big") % len(options)
    return options[index]


def _number(line: dict, key: str) -> float | None:
    value = line.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _performance_line(row) -> tuple[dict, bool]:
    """Best available performance line and whether it came from translation data."""
    if row.stat_line:
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
            "The damage changes games.",
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
            "The likely outcome is an everyday run-producing bat, with on-base value protecting the floor.",
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
            "The current damage limits the offensive ceiling.",
        )
        role = (
            "Table-setter ceiling. The present floor is a light-hitting reserve.",
            "The contact gives him an everyday path, but the current damage points to a bench floor.",
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
            "Second-division regular ceiling, but the current damage points to a low-impact bench floor.",
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
            f"He is contributing across contact, walks and damage rather than leaning on one result.",
            "He controls at-bats and does damage without leaning on one result.",
        )
        risk = (
            "No single result is loud enough to carry the bat through regression elsewhere.",
            "The risk is a broad but ordinary offensive line without one result that forces an everyday role.",
        )
        role = (
            "The likely outcome is a second-division regular who contributes across categories, with a useful bench-bat floor.",
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
            "No current rate identifies a weakness, so the next level is the meaningful test.",
        )
        role = (
            "Mid-rotation lean, with a back-end starter floor on the current evidence.",
            "This is a mid-rotation starter on the current evidence.",
        )
        family = "pitcher-dominant-control"
    elif k_per_9 is not None and k_per_9 >= 12 and bb_per_9 is not None and bb_per_9 >= 4.5:
        skill = (
            "He can finish hitters.",
            "The bat-missing is strong enough to keep a rotation look alive.",
        )
        risk = (
            "The walks create too many self-inflicted innings.",
            "Strike throwing is the failure point.",
        )
        role = (
            "Bullpen lean until the walks come down. The misses keep a rotation ceiling open.",
            "The current strike throwing points to the bullpen, with starter upside still alive.",
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
            "No current pitching rate gives him a dependable way through a lineup.",
            "The current line does not identify a repeatable method for retiring hitters.",
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


def _sample_context(row, line: dict, from_translation: bool) -> str:
    translated = row.stat_line_translated or {}
    pitcher = _is_pitcher(row, line)
    sample = _number(line, "ip" if pitcher else "pa")
    if sample is None:
        raw_sample = translated.get("sample")
        sample = float(raw_sample) if isinstance(raw_sample, (int, float)) else None
    unit = "IP" if pitcher else "PA"
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
    if old or low_sample:
        confidence = "low"

    level = _LEVEL_NAMES.get(row.level, row.level)
    sample_text = f"{sample:g} {unit}" if sample is not None else "the available sample"
    if old:
        return f"The latest meaningful sample is from {season}, so confidence is low."
    if low_sample:
        location = " in the latest MiLB sample" if row.level == "MLB" else (f" in {level}" if level else "")
        return f"Only {sample_text}{location}, so confidence is low."
    if row.level == "MLB":
        return f"The latest MiLB sample covers {sample_text}, so confidence is {confidence}."
    if row.age is not None and row.level and row.level != "MLB" and row.age <= _YOUNG_FOR_LEVEL.get(row.level, -1):
        return f"He is {row.age} in {level} over {sample_text}, so confidence is {confidence}."
    return f"The sample covers {sample_text}{f' in {level}' if level else ''}, so confidence is {confidence}."


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
            "No rotation call is supported; the floor is organizational depth until he gives us something current to evaluate.",
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
        "No everyday call is supported; the floor is organizational depth until he gives us something current to evaluate.",
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


def _eligible(row) -> bool:
    line = row.stat_line or {}
    pa = line.get("pa")
    return bool(row.is_prospect and line and isinstance(pa, (int, float)) and pa >= MIN_PA)


def build_pool(rows) -> dict[str, list[float]]:
    """Sorted per-metric value arrays over eligible prospects."""
    pool: dict[str, list[float]] = {m: [] for m in METRICS}
    for row in rows:
        if not _eligible(row):
            continue
        for m in METRICS:
            v = (row.stat_line or {}).get(m)
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


def card_percentiles(pool: dict, row) -> dict[str, int]:
    """{metric: percentile} for an eligible prospect; {} otherwise."""
    if not _eligible(row):
        return {}
    out = {}
    for m in METRICS:
        pct = percentile_for(pool, m, (row.stat_line or {}).get(m))
        if pct is not None:
            out[m] = pct
    return out


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


def top_movers(rows, limit: int = 5, min_change: int = 5, max_rank: int = 200) -> list[dict]:
    """Largest |breakout_rank_change| among visible-board prospects. [] when quiet."""
    candidates = [
        r for r in rows
        if r.is_prospect
        and isinstance(r.breakout_rank_change, int)
        and abs(r.breakout_rank_change) >= min_change
        and r.prospect_rank is not None
        and r.prospect_rank <= max_rank
    ]
    candidates.sort(key=lambda r: (-abs(r.breakout_rank_change), r.prospect_rank))
    return [
        {"id": r.id, "name": r.name, "prospect_rank": r.prospect_rank,
         "change": r.breakout_rank_change}
        for r in candidates[:limit]
    ]


def identity_line(row, _percentiles: dict) -> str | None:
    """Deterministic scouting-style card summary. None for non-prospects."""
    if not row.is_prospect:
        return None
    line, from_translation = _performance_line(row)
    if not line:
        return _no_sample_report(row)
    skill, risk, role = (
        _pitcher_parts(row, line) if _is_pitcher(row, line) else _hitter_parts(row, line)
    )
    return _assemble_report(row, skill, risk, role, _sample_context(row, line, from_translation))
