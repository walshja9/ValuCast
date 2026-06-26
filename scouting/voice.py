"""ValuCast scouting voice — the single source the LLM prompt AND the post-gen
validator both import. Pure data + checks; no I/O, no API, no DD imports.

The voice standard is enforced two ways: (1) as the system prompt foundation for
the LLM writer, and (2) as a deterministic post-gen guard (banned phrases + any
number not present in the supplied grounding). ValuCast-owned; intentionally NOT
shared with DD's scouting_voice.py / scouting_validator.py.
"""
from __future__ import annotations

import re

VOICE_PROMPT = """You write one short ValuCast scouting read for a single baseball player — a prospect or an established MLB player.

Voice (the spine, in order, but order is flexible):
1. Lead with the baseball read — what kind of player this is, behaviorally, not a label.
2. Name one or two stat signals that support the read, using the numbers you are given.
3. Be direct about the main flaw or risk. No fake balance, no hedging both ways.
4. Optionally close with one plain sentence about confidence given the sample.

Hard rules:
- Use ONLY the data provided below. Never state a number that is not in the data.
- When citing AVG/OBP/SLG/OPS/ISO, use decimal form exactly like .252, not 25.2%.
  Only BB%, K%, K-BB%, percentiles, and similar percentage stats use percent wording.
- If a pitcher's throws hand is provided, use it exactly. If it is missing, do
  not mention pitcher handedness.
- Each stat is tagged with its source (current MLB line vs MiLB-equivalent translation
  vs minor-league line vs projection). Never blend samples or present one as another.
- Never invent velocity, pitch shapes, mechanics, defense, makeup, or any scouting
  texture that is not in the data. If the data does not show it, do not name it.
- If a peak projection (role/ceiling, floor, trajectory, or skill shape) is provided, you may
  describe the ceiling and floor in plain words, clearly as a projection — never as current production.
- If a ValuCast ranking-movement note is provided, you may add one sentence noting the player is
  rising or cooling in ValuCast's rankings — label it as ranking movement, never as a change in his stats.
- When a Statcast percentile card is provided (established MLB players), make it the spine
  of the read — what the percentile profile says about the player's actual skills — with the
  projection line as supporting context.
- Thin / stale / injured samples: say so in one honest confidence sentence; never paper
  over a small sample with a confident read. But for a full-season projection or an
  established Statcast profile, do not manufacture a small-sample caveat.
- Never claim ValuCast beats Steamer/ZiPS or is "the most accurate." State the read, not a
  comparison to other systems.
- Plain, professional, specific. No hype, no generic-AI filler, no fantasy clichés.
- 2 to 4 sentences. No headings, no bullet points, no preamble — just the read."""

# Lowercased substrings that must never appear. Single source for prompt + validator.
BANNED_PHRASES = (
    # generic-AI filler
    "game-changer", "game changer", "it's important to note", "important to note",
    "unlock", "robust", "nuanced", "moving forward", "worth monitoring",
    # fantasy clichés
    "intriguing", "tantalizing", "sturdy foundation", "upside is evident",
    "high-floor", "high floor", "high-ceiling", "high ceiling", "carrying skill",
    # leaked internal / boundary terms
    "display-only", "artifact", "dd-backed", "adapter",
    # accuracy/hype claims
    "beats steamer", "most accurate", "best projection",
)

# Leading-dot decimals (".28", ".070") are captured AS decimals (0.28, 0.07) — the
# alternative is ordered first so a rate written without a leading zero is read at its
# true value instead of tokenizing ".28" -> 28 (which never matched grounding's 0.28).
_NUMBER_RE = re.compile(r"\.\d+|\d+(?:\.\d+)?")
_LEFT_HAND_RE = re.compile(
    r"\b(?:left[- ]hand(?:ed|er)|lefty|southpaw|lhp)\b",
    re.IGNORECASE,
)
_RIGHT_HAND_RE = re.compile(
    r"\b(?:right[- ]hand(?:ed|er)|righty|rhp)\b",
    re.IGNORECASE,
)


def banned_phrase_hits(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [phrase for phrase in BANNED_PHRASES if phrase in lowered]


# Key fragments that name a RATE metric whose grounding value may legitimately appear
# in leading-zero rate form (e.g. a 0.322 AVG cited as ".322", tokenized as 322). Only
# these keys get the /1000 collapse — counts (pa/ab/h/hr...) and percentiles must not,
# or a 322-PA count would "ground" a hallucinated .322 AVG.
_RATE_KEY_FRAGMENTS = (
    "avg", "obp", "slg", "ops", "iso", "babip", "era", "whip",
    "_pct", "pct_", "_per_9", "_rate", "rate_", "k9", "bb9",
)


def _is_rate_key(key) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(frag in lowered for frag in _RATE_KEY_FRAGMENTS)


def _collect_numbers(obj, rate_context: bool = False) -> tuple[set[float], set[float]]:
    """Every numeric value anywhere in the grounding (stats, samples, ages, ranks,
    percentiles) — the set a report is allowed to cite. Returns (all, rate_only) where
    rate_only is the subset found under a known rate-metric key, eligible for the
    leading-zero (/1000) rate form."""
    found: set[float] = set()
    rate_found: set[float] = set()
    if isinstance(obj, bool):
        return found, rate_found
    if isinstance(obj, (int, float)):
        found.add(float(obj))
        if rate_context:
            rate_found.add(float(obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            sub_all, sub_rate = _collect_numbers(v, rate_context or _is_rate_key(k))
            found |= sub_all
            rate_found |= sub_rate
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            sub_all, sub_rate = _collect_numbers(v, rate_context)
            found |= sub_all
            rate_found |= sub_rate
    elif isinstance(obj, str):
        for token in _NUMBER_RE.findall(obj):
            try:
                num = float(token)
            except ValueError:
                continue
            found.add(num)
            if rate_context:
                rate_found.add(num)
    return found, rate_found


def _forms(value: float) -> set[float]:
    """The rounding forms a number could legitimately appear as: exact and 1-decimal
    (ERA/WHIP/K9 rounding like 3.36 -> 3.4). No /1000 collapse here — that is applied
    only to rate-metric grounding values (see ``_number_supported``)."""
    return {round(value, 3), round(value, 1)}


def _number_supported(value: float, allowed: set[float], rate_allowed: set[float]) -> bool:
    """Supported if a legitimate rounded form of the cited number matches the grounding.
    The leading-zero rate form (".322" tokenized as 322 -> 0.322) is only honored against
    rate-metric grounding values, so a count like 322 PA cannot ground a .322 AVG."""
    value_forms = _forms(value)
    if any(value_forms & _forms(a) for a in allowed):
        return True
    # cited as a leading-zero rate (".322" -> 322): match against rate-metric values only,
    # comparing the cited /1000 form to the rate value's true form.
    if value >= 30:
        collapsed = _forms(round(value / 1000, 3))
        if any(collapsed & _forms(a) for a in rate_allowed):
            return True
    return False


def unsupported_numbers(text: str, grounding: dict) -> list[str]:
    """Numbers in the report not traceable to the grounding (hallucination guard).
    Soft signal — tolerant of rounding/ordinals to avoid false positives."""
    allowed, rate_allowed = _collect_numbers(grounding)
    out = []
    for token in _NUMBER_RE.findall(text or ""):
        try:
            value = float(token)
        except ValueError:
            continue
        if not _number_supported(value, allowed, rate_allowed):
            out.append(token)
    return out


def _raw_hand_text(value) -> str:
    """Uppercased string form of a handedness value (unwrapping the dict form), used to
    detect switch hitters before resolving an L/R code."""
    if isinstance(value, dict):
        value = value.get("code") or value.get("description") or value.get("side")
    return str(value or "").strip().upper()


def _hand_code(value) -> str | None:
    text = _raw_hand_text(value)
    if text in {"L", "LEFT"} or text.startswith("LEFT "):
        return "L"
    if text in {"R", "RIGHT"} or text.startswith("RIGHT "):
        return "R"
    return None


def handedness_problems(text: str, grounding: dict) -> list[str]:
    """Hard guard against invented or mismatched handedness — pitcher throws hand
    (``throws``) or hitter batting side (``bats``)."""
    role = str((grounding or {}).get("role") or "").lower()
    is_pitcher = role == "pitcher"
    mentions_left = bool(_LEFT_HAND_RE.search(text or ""))
    mentions_right = bool(_RIGHT_HAND_RE.search(text or ""))
    if not mentions_left and not mentions_right:
        return []
    if is_pitcher:
        noun, missing_label = "pitcher", "throws"
        raw = (
            (grounding or {}).get("throws")
            or (grounding or {}).get("pitch_hand")
            or (grounding or {}).get("throw_hand")
        )
    else:
        noun, missing_label = "hitter", "bats"
        raw = (grounding or {}).get("bats") or (grounding or {}).get("bat_hand")
    # Switch hitters legitimately bat both ways — never flag a side for them.
    if _raw_hand_text(raw) in {"S", "SWITCH", "B", "BOTH"}:
        return []
    hand = _hand_code(raw)
    if not hand:
        return [f"{noun} handedness mentioned but {missing_label} is missing from grounding"]
    if hand == "L" and mentions_right:
        return [f"{noun} {missing_label} L but report says right-handed"]
    if hand == "R" and mentions_left:
        return [f"{noun} {missing_label} R but report says left-handed"]
    return []


def validate_report_text(text: str, grounding: dict) -> dict:
    """Post-gen guard. `banned` is a hard fail; `unsupported_numbers` is a soft flag
    (tolerant), surfaced for spot-check rather than auto-discarding on rounding noise."""
    banned = banned_phrase_hits(text)
    numbers = unsupported_numbers(text, grounding)
    handedness = handedness_problems(text, grounding)
    return {
        "banned": banned,
        "unsupported_numbers": numbers,
        "handedness_problems": handedness,
        "ok": not banned and not numbers and not handedness,
        "hard_ok": not banned and not handedness,
    }
