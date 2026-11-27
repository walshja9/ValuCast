"""ValuCast scouting voice — the single source the LLM prompt AND the post-gen
validator both import. Pure data + checks; no I/O, no API, no DD imports.

The voice standard is enforced two ways: (1) as the system prompt foundation for
the LLM writer, and (2) as a deterministic post-gen guard (banned phrases + any
number not present in the supplied grounding). ValuCast-owned; intentionally NOT
shared with DD's scouting_voice.py / scouting_validator.py.
"""
from __future__ import annotations

import re

VOICE_PROMPT = """You write one short ValuCast scouting read for a single baseball player — a prospect or an established MLB player. A read is a scout thinking out loud to another scout: a verdict with a reason, not an encyclopedia entry and not a stat recap.

Voice:
- Open with the verdict, the tension in the profile, or the one number that carries the argument. NEVER open with "<Name> is a <age>-year-old <position> who..." or any name-plus-identity template. The first sentence doesn't even need his name in it.
- Pick the two or three numbers that carry the argument and weave them into the prose. Never recite a full stat line or projection line, and never chain stats with parenthetical percentiles like "X (91st percentile), Y (75th percentile)". For an established MLB player, translate the Statcast profile into what he actually is — don't inventory it.
- Cite figures exactly as given and NEVER derive new ones: no arithmetic ("8 points above league average"), no rounding, no "top-5 percent", no "30-plus". If a comparison isn't in the data as a number, make it in words.
- Make the rhythm lumpy: a long descriptive sentence, then a short blunt one. Never three same-shape sentences in a row. At most one em-dash in the whole read; commas and periods do the work.
- Hedge by naming the specific dependency — what the profile hinges on and what happens if it doesn't hold — not with "though X, Y" scaffolding on every claim. No false balance, no double-hedging.
- Give the verdict as a range when the outcome is genuinely open ("either a low-end regular or a good bench bat"), and commit when it isn't. Never write the words "the projection sees" in any sentence, for any purpose — say what he becomes if it works and what's left if it doesn't, in words that fit this player.
- Match register to the player: short and confident for elite guys; honest, a little wry, about limited profiles; for thin-sample lottery tickets, lead with what's loud and name the red flag.
- One idea per sentence. Never restate a fact with new adjectives, no triadic lists, no symmetrical "A with B, C with D" constructions.
- ValuCast rank movement is background context. Mention it only when the move itself is the story, woven into the argument — never as a tacked-on final sentence.
- Never certify a stat with "the power is real" / "not a fluke" — show why it's believable (the sample, the shape, the translation) instead of stamping it. Never spotlight with "the whole story/ballgame". Never close on "the honest question is whether...". Never crown anyone "one of the best/cleanest/nastiest ___ in the game". Don't tack on a confidence rating.
- Comparing a rate to league average is fine, but never with the stock scaffold "X% against a league average of Y%" — vary how the comparison is said, or let one comparison carry the read.

Hard rules (these never bend):
- Use ONLY the data provided below. Never state a number that is not in the data; cite figures exactly as given (no rounding a "+22" move to "+20").
- AVG/OBP/SLG/OPS/ISO in decimal form like .252, never 25.2%. Only BB%, K%, K-BB%, and percentiles use percent wording.
- If a pitcher's throws hand is provided, use it exactly. If it is missing, do not mention pitcher handedness.
- Each stat is tagged with its source (current MLB line / MiLB-equivalent translation / minor-league line / projection). Never blend samples or present one as another.
- Cite a count (walks, strikeouts, hits, home runs, plate appearances) ONLY as the exact number given in the data. Never state a count that is not in the data, and never derive one from a rate or reuse one stat's count for another — if the data gives a walk total but no strikeout total, do not state a strikeout total.
- Every stat carries the exact level of the line it comes from: cite it with that line's level_label and no other. Never attribute a pooled multi-level line to a single one of its sub-levels — when a line's level_label names more than one level (e.g. "AA & A+"), a number from it is "across AA & A+", never "at AA".
- Never invent velocity, pitch shapes, mechanics, defense, makeup, or any scouting texture not in the data. If the data does not show it, do not name it.
- For a prospect, describe qualitative ceiling and floor only as scenarios. Never use projection language, quote an outcome probability, or state a numeric risk; use "translates to" for an MLB-equivalent rate.
- Stay in the player's own role vocabulary. For a hitter, never reduce him to a pitcher idiom (a "depth arm", "organizational arm", "mid-rotation" anything, "swingman", "long reliever") — name his floor/ceiling as a hitter (bench bat, platoon piece, second-division regular, everyday player). For a pitcher, never grade him as a hitter ("his bat", "bat-first", "everyday regular"); referencing the hitters he faces is fine. A two-way player is the only one who gets both vocabularies.
- If a ValuCast ranking-movement note is provided, you may note he is rising or cooling in ValuCast's rankings — as ranking movement, never as a change in his stats, using the exact figure given.
- When a Statcast percentile card is provided (established MLB players), make it the spine of the read — what the percentile profile says about his actual skills — with the projection as context.
- Thin / stale / injured samples: say so honestly in one sentence; never paper over a small sample with a confident read. For a full-season projection or an established Statcast profile, do not manufacture a small-sample caveat.
- Never claim ValuCast beats Steamer/ZiPS or is "the most accurate." State the read, not a comparison to other systems.
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
    # robotic template cadences (the LLM's formulaic tells)
    "operating in the", "suggest his ceiling", "suggests his ceiling",
    "to reach that role", "aligns with those", "align with those",
    # 7/5 voice audit: dominant Sonnet templates measured across 302 cached reads
    "against a league average", "against the league average", "against a league norm",
    "against a league mean", "against a league-average",
    "not a fluke", "the whole story", "the whole ballgame", "is the thing that",
    "the projection sees", "honest question", "last three days",
    "the real tension", "tension in his profile", "in the game",
    "boasts", "possesses", "showcases", "not just", "not only",
    "making him", "makes him a", "one to watch", "valuable asset",
    "confidence feels", "valucast carries",
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
_TRIPLE_SLASH_RE = re.compile(r"(?<![\d.])(\.\d+|0?\.\d+)/(\.\d+|0?\.\d+)/(\.\d+|0?\.\d+)(?![\d.])")


def banned_phrase_hits(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [phrase for phrase in BANNED_PHRASES if phrase in lowered]


# 7/14 grounding audit: the literal "against a league average" bans caught only the exact
# scaffold; the drift variants (measured on 171/728 published reads, 23.5%, zero caught)
# slipped through as "big-league average", "major-league average", "league mark", "league
# backdrop", "majors' 8.5% average", "above/below the ... average". This regex covers the
# family. SOFT signal (drives regen) like unsupported_numbers/style -- a stale scaffold is
# a rewrite candidate, not a factual hazard, so it gates ok but never hard_ok.
_LEAGUE_AVG_SCAFFOLD_RE = re.compile(
    r"\b(?:big[-\s]league|major[-\s]league|majors'?)\s+"
    r"(?:[\w.%-]+\s+){0,3}?(?:average|mean|norm|baseline|mark)\b"
    r"|\bleague\s+(?:mark|backdrop)\b"
    r"|\b(?:above|below)\s+the\s+(?:[\w.%'-]+\s+){0,4}?average\b",
    re.IGNORECASE,
)


def league_average_scaffold_problems(text: str) -> list[str]:
    """Drift variants of the banned 'against a league average' scaffold that the literal
    substring bans miss. Soft signal: surfaced for regen, not a hard fact-hazard."""
    return [
        f"league-average scaffold variant '{match.group(0).strip()}'"
        for match in _LEAGUE_AVG_SCAFFOLD_RE.finditer(text or "")
    ]


# 7/5 voice audit: "never fall into a formula" alone was ignored — 86% of reads opened
# "<Name> is a ...", 100% used em-dashes (avg 2.44), 39% stamped a skill "is real".
# These structural tells need deterministic checks, not prompt vibes.
_IDENTITY_OPENER_RE = re.compile(r"^\s*(?:[A-Z][\w.'-]*\s+){1,4}is an?\s")
# "is real enough to" / "is real rather than" are legitimate analyst constructions;
# only the bare certification stamp ("the power is real") is a tell.
_IS_REAL_RE = re.compile(
    r"\b(?:is|are) (?:real|legit)\b(?!\s+(?:enough|rather))|\bthat's real\b", re.IGNORECASE
)
_EM_DASH_MAX = 1


def style_problems(text: str) -> list[str]:
    out = []
    t = text or ""
    if _IDENTITY_OPENER_RE.match(t):
        out.append("identity-template opener ('<Name> is a ...')")
    if t.count("—") + t.count("–") > _EM_DASH_MAX:
        out.append(f"more than {_EM_DASH_MAX} em-dash")
    if _IS_REAL_RE.search(t):
        out.append("'is real' validation stamp")
    return out


# 7/9 claims audit: the digit-only _NUMBER_RE lets a DERIVED numeric delta spelled as
# a WORD pass the fact guard -- e.g. Eli Willits "more than three points above the
# big-league average" (a subtraction the model invented; no league baseline is in the
# grounding to check it against). VOICE_PROMPT forbids exactly this ("no arithmetic")
# and BANNED_PHRASES catches the digit-form scaffold, but not the word-form.
_NUMBER_WORD = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"couple|several)"
)
# Template A: "<word|digits> [full] points/percentage points/percent/ticks above|below ..."
# All 10 live hits on this template are real violations -- no exclusion needed.
_WORD_DELTA_RE = re.compile(
    r"\b(?:" + _NUMBER_WORD + r"|\d+)\s+(?:full\s+)?"
    r"(?:points?|percentage\s+points?|percent|ticks?)\s+"
    r"(?:above|below|better|worse|higher|lower|more|fewer)\b",
    re.IGNORECASE,
)
# Template B: multiplier comparative ("double/triple/half the league norm"). The
# leading alternation is ONLY the multiplier WORDS -- NOT bare digits/number-words.
# (Allowing a bare number token there over-fires massively: "20.0% ... rate" and every
# "N% ... walk rate" phrase matches -> ~25% flag rate. Verified.) MUST also anchor on
# an average/norm/mean/baseline/rate/clip word or it fires on non-numeric prose
# ("scrubs half the power", "depth more than half the time").
_MULTIPLIER_DELTA_RE = re.compile(
    r"\b(?:double|triple|quadruple|half)\s+"
    r"(?:the\s+)?"
    r"(?:[\w.%-]+\s+){0,3}?"
    r"(?:average|norm|mean|baseline|rate|clip)\b",
    re.IGNORECASE,
)
# Template C: the "N times the league" comparative (separate from the multiplier words).
_TIMES_DELTA_RE = re.compile(
    r"\b(?:" + _NUMBER_WORD + r"|\d+)\s+times\s+(?:the|as|higher|more|league)\b",
    re.IGNORECASE,
)


def derived_word_number_problems(text: str) -> list[str]:
    """Derived numeric deltas spelled as WORDS, which the digit-only number guard
    (unsupported_numbers) cannot see. VOICE_PROMPT bans arithmetic derivation; this
    catches the word-form the digit scan misses. Soft signal (drives regen), same
    class as unsupported_numbers -- surfaced, not a hard fact-hazard."""
    out: list[str] = []
    t = text or ""
    for match in _WORD_DELTA_RE.finditer(t):
        out.append(f"word-form derived delta '{match.group(0).strip()}'")
    for match in _MULTIPLIER_DELTA_RE.finditer(t):
        out.append(f"word-form multiplier comparison '{match.group(0).strip()}'")
    for match in _TIMES_DELTA_RE.finditer(t):
        out.append(f"word-form 'N times' comparison '{match.group(0).strip()}'")
    return out


# --- Role-vocabulary lane guard (7/5) -------------------------------------------------
# The LLM paraphrases a floor/ceiling LABEL into the wrong position's idiom: Brady Ebel's
# ("Bench Or Depth Floor", 815816_hitter) came back as "a patient organizational depth arm
# at shortstop" though "arm" was never in his grounding -- the model invented a real but
# pitcher-only scouting idiom. Cache scan of 713 fresh reads: 4 confirmed hitter leaks (all
# "<pitcher-role> arm" synecdoche) + 1 "mid-rotation regular" tier-borrow; 0 pitcher leaks.
# Precision: flag ONLY role-noun compounds with no valid cross-role meaning. Bare
# "arm"/"starter"/"rotation"/"regular"/"bat" are legitimate for the OTHER role too (a
# hitter's throwing-arm grade, a pitcher facing "platoon bats") and must never fire.
_H_PITCHER_ARM_RE = re.compile(
    r"\b(?:organizational|org|bullpen|relief|relieving|rotational?|"
    r"back[-\s]?end|middle[-\s]?relief|long[-\s]?relief|late[-\s]?inning|"
    r"high[-\s]?leverage|set[-\s]?up|depth|spare|filler|emergency|"
    r"mop[-\s]?up|up[-\s]?and[-\s]?down|bulk[-\s]?innings)[-\s]+arms?\b",
    re.IGNORECASE,
)
# Bare ordinal+starter ("the second starter he faces") is opponent-facing for a hitter --
# excluded. Only pitcher-tier compounds with no hitter meaning fire.
_H_PITCHER_ROTATION_RE = re.compile(
    r"\bmid[-\s]?rotation\b"
    r"|\b(?:front|top|back)[-\s]of[-\s]the[-\s]rotation\b"
    r"|\bback[-\s]?end(?:[-\s]+of[-\s]the)?[-\s]+rotation\b"
    r"|\brotation(?:al)?[-\s]+(?:piece|spot|slot|starter|stalwart|stabilizer|"
    r"cog|workhorse|anchor|stopgap)\b"
    r"|\b(?:back[-\s]?end|backend|spot)[-\s]+starter\b"
    r"|\b(?:no\.?\s*[1-5]|#\s*[1-5]|number[-\s]?(?:one|two|three|four|five))[-\s]+starter\b",
    re.IGNORECASE,
)
_H_PITCHER_ROLE_NOUN_RE = re.compile(
    r"\bswing[-\s]?man\b|\binnings[-\s]?eater\b|\blong[-\s]?reliever\b|"
    r"\bmiddle[-\s]?reliever\b|\bmop[-\s]?up (?:man|guy)\b",
    re.IGNORECASE,
)
# PITCHER reads -> hitter-only verdicts. "<tier> bats/regular" is excluded -- a pitcher
# legitimately describes opponents that way ("neutralizes platoon bats"). Only
# self-referential verdicts (copula/"profiles as" + hitter role noun) fire.
_P_HITTER_SELF_RE = re.compile(
    r"\bbat[-\s]first\b|"
    r"\b(?:he'?s|is|becomes|profiles as|projects as) (?:an? )?"
    r"(?:everyday|platoon|bench|corner|utility|part[-\s]time)[-\s]+(?:bat|regular)\b",
    re.IGNORECASE,
)


def role_vocab_problems(text: str, grounding: dict) -> list[str]:
    """Pitcher-only idioms in a HITTER read / hitter-only verdicts in a PITCHER read.
    Two-way players (role='two_way') legitimately mix both vocabularies and are skipped."""
    role = str((grounding or {}).get("role") or "").lower()
    t = text or ""
    out: list[str] = []
    if role == "hitter":
        checks = (
            (_H_PITCHER_ARM_RE, "pitcher 'arm' synecdoche"),
            (_H_PITCHER_ROTATION_RE, "pitcher rotation/starter tier"),
            (_H_PITCHER_ROLE_NOUN_RE, "pitcher-only role noun"),
        )
        for regex, lane in checks:
            for match in regex.finditer(t):
                out.append(
                    f"pitcher-only idiom '{match.group(0).strip()}' in a hitter read "
                    f"({lane}) -- describe the floor/ceiling with a hitter role label"
                )
    elif role == "pitcher":
        for match in _P_HITTER_SELF_RE.finditer(t):
            out.append(
                f"hitter-only verdict '{match.group(0).strip()}' casts a pitcher as a "
                f"hitter -- describe his floor/ceiling with a pitcher role label"
            )
    return out


_UNCALIBRATED_PROJECTION_CLAIM_RE = re.compile(
    r"\bproject\w*\b"
    r"|\b(?:probabilit(?:y|ies)|odds)\b"
    r"|\b(?:low|medium|high)[-\s]+risk\b"
    r"|\blikely outcome\b"
    r"|\bmost likely (?:destination|landing spot|outcome|role)\b"
    r"|\bprofiles as\b"
    r"|\b\d+(?:\.\d+)?%[^.!?\n]{0,120}\b(?:chance|shot|path|handle)\b"
    r"|\b\d+(?:\.\d+)?%\s+(?:[\w/-]+\s+){0,5}(?:outcome|projection)\b"
    r"|\b(?:role|outcome)[^.!?\n]{0,100}\b(?:in play )?(?:at|projected at)\s+\d+(?:\.\d+)?%"
    r"|(?:\bprojection\b[^.!?\n]{0,180}\b\d+(?:\.\d+)?%"
    r"|\b\d+(?:\.\d+)?%[^.!?\n]{0,180}\b(?:projection|projected)\b)"
    r"[^.!?\n]{0,100}\b(?:outcome|role|regular|starter|relief|depth|bench)\b",
    re.IGNORECASE,
)


def uncalibrated_projection_claims(text: str) -> list[str]:
    """Outcome language that turns qualitative prospect scenarios into probabilities."""
    return [
        match.group(0).strip()
        for match in _UNCALIBRATED_PROJECTION_CLAIM_RE.finditer(text or "")
    ]


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


def sample_context_stale(text: str, grounding: dict) -> bool:
    """True when the text never cites the CURRENT sample size at all -- catches a
    cached report reused against updated grounding after the player's sample grew
    (e.g. a single-level line that later became a multi-level pooled line). Every
    one of the old sub-line's own numbers still individually appear in the new
    grounding's per-level breakdown, so unsupported_numbers() alone can't catch this
    -- the text isn't inventing anything, it's just silently describing a narrower,
    outdated slice of the season as if it were the whole thing. Only meaningful for
    the reused-cache path; a fresh generation always describes the current sample."""
    sample_context = (grounding or {}).get("sample_context")
    sample = sample_context.get("sample") if isinstance(sample_context, dict) else None
    if not isinstance(sample, (int, float)) or sample <= 0:
        return False
    forms = {round(float(sample), 3), round(float(sample), 1), round(float(sample))}
    for token in _NUMBER_RE.findall(text or ""):
        try:
            value = float(token)
        except ValueError:
            continue
        if {round(value, 3), round(value, 1), round(value)} & forms:
            return False
    return True


def _grounding_rate(grounding: dict, key: str) -> float | None:
    for scope in ("card_display_line", "mlb_equivalent_translation", "stat_line_stats"):
        values = (grounding or {}).get(scope)
        # stat_line_stats grounding comes in two shapes across repository.py:
        # flat ({"AVG": ...}) and nested ({"stats": {"AVG": ...}}). Unwrap only
        # when a real nested "stats" dict exists, else use the flat dict directly.
        if scope == "stat_line_stats" and isinstance(values, dict) and isinstance(values.get("stats"), dict):
            values = values.get("stats")
        if not isinstance(values, dict):
            continue
        for raw_key, value in values.items():
            if str(raw_key).lower() == key and isinstance(value, (int, float)):
                return float(value)
    return None


def _same_rate(left: float, right: float) -> bool:
    return round(float(left), 3) == round(float(right), 3)


def triple_slash_problems(text: str, grounding: dict) -> list[str]:
    ops = _grounding_rate(grounding, "ops")
    slg = _grounding_rate(grounding, "slg")
    if ops is None or slg is None or _same_rate(ops, slg):
        return []
    problems = []
    for match in _TRIPLE_SLASH_RE.finditer(text or ""):
        third = float(match.group(3))
        if _same_rate(third, ops):
            problems.append("triple-slash SLG slot matches OPS")
    return problems


# --- Pooled-line level attribution guard (7/14) ------------------------------------------
# The proven Sirota defect: card_display_line.source_kind == "combined_season_line" pooling
# AA + A+, and the read wrote "a .475 OBP at AA" -- attributing the whole pooled sample to a
# single sub-level. Fires ONLY when the citable line is combined AND the text pins a stat to
# one of the pooled sub-levels WITHOUT naming the pooled label nearby. A single-level read
# citing "at AA" is legitimate and never trips this (source_kind is not combined).
# Only real level TOKENS -- never the bare article "a"/"an" (an early over-fire: "in a
# pinch", "at a level where" tokenized the article as Single-A). "A"/"A+" as a level must
# be spelled with the "+" or a level word (Single-A / Low-A), so a lone "a" cannot match.
# A trailing \b after "A+" fails (the "+" is non-word, so a following space is not a word
# boundary), which silently dropped every "A+" token. Use a lookahead for "not another level
# char" instead of \b so "A+" tokenizes. High-A/Low-A come before bare A+ so the longer alias
# wins. "AAA"/"AA" are ordered longest-first so "AAA" is never read as "AA"+"A".
_LEVEL_TOKEN = (
    r"(?:Triple-?A|Double-?A|Single-?A|High[-\s]?A|Low[-\s]?A|"
    r"AAA|AA|A\+|Rookie|Complex|DSL)(?![A-Za-z+])"
)
_AT_LEVEL_RE = re.compile(
    r"\b(?:at|in|across|through|between)\s+"
    r"(" + _LEVEL_TOKEN + r"|the\s+(?:majors|minors)\b)",
    re.IGNORECASE,
)
# A read that names EVERY sub-level ("at AAA and AA", "Triple-A and Double-A") has framed the
# pooled sample correctly even without the exact "&" label. Detect the sub-levels the text
# names so a fully-named pool clears.
_TEXT_LEVEL_TOKEN_RE = re.compile(r"\b(" + _LEVEL_TOKEN + r")", re.IGNORECASE)


def _combined_line_levels(grounding: dict) -> tuple[list[str], str | None]:
    """The sub-levels and pooled label of a combined card line, or ([], None) when the
    citable line is not a pooled multi-level line. Reads card_display_line first, then
    sample_context -- either can carry the source_kind/levels/level_label the build set."""
    for scope in ("card_display_line", "sample_context"):
        block = (grounding or {}).get(scope)
        if not isinstance(block, dict):
            continue
        if block.get("source_kind") != "combined_season_line":
            continue
        levels = [str(lv).strip() for lv in (block.get("levels") or []) if lv]
        if len(levels) <= 1:
            continue
        return levels, (str(block.get("level_label")).strip() if block.get("level_label") else None)
    return [], None


def _norm_level(level: str) -> str:
    return (
        re.sub(r"[\s-]", "", level).lower()
        .replace("triplea", "aaa").replace("doublea", "aa").replace("singlea", "a")
    )


def _level_token_matches(cited: str, level: str) -> bool:
    """A cited level string names the given sub-level (case/spacing/alias tolerant)."""
    c = _norm_level(cited)
    return bool(c) and c == _norm_level(level)


def level_attribution_problems(text: str, grounding: dict) -> list[str]:
    """Combined pooled line cited as a single sub-level (wrong-fact class -> gates hard_ok).
    Flags '<stat> at <sub-level>' only when the citable line pooled multiple levels and the
    read does NOT frame the pool (neither the pooled label nor all sub-levels named). Never
    fires on a single-level read."""
    levels, pooled = _combined_line_levels(grounding)
    if len(levels) <= 1:
        return []
    t = text or ""
    # Pool framed correctly -> do not flag. Two accepted framings:
    #   1. the exact pooled label appears ("AA & A+").
    #   2. the text names EVERY sub-level anywhere ("at AAA and AA", "Triple-A and Double-A").
    if pooled and _norm_level(pooled) in re.sub(r"[\s-]", "", t).lower():
        return []
    named = {_norm_level(m.group(1)) for m in _TEXT_LEVEL_TOKEN_RE.finditer(t)}
    if named >= {_norm_level(lv) for lv in levels}:
        return []
    out: list[str] = []
    for match in _AT_LEVEL_RE.finditer(t):
        prep = match.group(0).split()[0].lower()
        cited = match.group(1)
        # "across"/"between" are pooling prepositions -- naming a sub-level after them is how
        # a correct pooled read reads ("across AA & A+"); only single-level pins fire.
        if prep in ("across", "between"):
            continue
        if any(_level_token_matches(cited, lvl) for lvl in levels):
            label = pooled or " & ".join(levels)
            out.append(
                f"pooled {label} line attributed to a single sub-level "
                f"('{match.group(0).strip()}')"
            )
    return out


# --- Count-role guard (7/14) -------------------------------------------------------------
# Sirota: "74 walks against 74 strikeouts" -- the model reused the walk count for strikeouts
# because no strikeout COUNT was in the grounding. Field-aware: the cited strikeout count
# must exist in the grounding AS a strikeout-count value (repository now injects it), not
# merely appear somewhere (74 walks must not "ground" 74 strikeouts). Wrong-fact class ->
# gates hard_ok.
# A strikeout COUNT is an integer ("74 strikeouts"); a K/9 RATE is a decimal followed by
# "per nine" ("15.0 strikeouts per nine") and must NOT be read as a count. Require an integer
# (no decimal point) and a negative lookahead for the "per (nine|9)" / "rate" rate tail. Also
# exclude "whiff"/"K%" which are rates, not counts -- only true count nouns.
_K_COUNT_RE = re.compile(
    r"(?<![.\d/])(\d{1,3})\s+(?:strikeouts?|k'?s|punch[-\s]?outs?)"
    r"(?!\s+(?:per|/)\s*(?:nine|9)|\s+rate|\s*%|[-\s]*to[-\s]*(?:walk|bb)|/)\b",
    re.IGNORECASE,
)
_WALK_COUNT_RE = re.compile(r"(\d{1,3})\s+(?:walks?|free\s+passes|bases?\s+on\s+balls)\b", re.IGNORECASE)


def _grounding_count(grounding: dict, keys: tuple[str, ...]) -> set[int]:
    """Every integer value stored under any of the named count keys, anywhere in the
    grounding tree. Field-aware: only these keys count, so a walk total cannot satisfy a
    strikeout-count claim."""
    found: set[int] = set()

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and k.lower() in keys and isinstance(v, (int, float)) and not isinstance(v, bool):
                    found.add(round(float(v)))
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v)

    walk(grounding or {})
    return found


def count_role_problems(text: str, grounding: dict) -> list[str]:
    """A cited strikeout count with no matching strikeout-count value in the grounding
    (the model derived or reused it). Wrong-fact class -> gates hard_ok."""
    cited_ks = {int(m.group(1)) for m in _K_COUNT_RE.finditer(text or "")}
    if not cited_ks:
        return []
    allowed = _grounding_count(grounding, ("strikeouts", "so", "k", "strike_outs"))
    out: list[str] = []
    for k in sorted(cited_ks):
        if k not in allowed:
            out.append(
                f"strikeout count '{k}' is not a strikeout total in the data "
                f"(fabricated or reused from another stat)"
            )
    return out


# --- Cross-surface PA consistency (7/14) -------------------------------------------------
# The Sirota card contradicted itself: the read cited 358 PA (pooled) while the deterministic
# peak_summary cited 199 PA (a single sub-level). A read PA claim must match the grounding's
# current sample. Soft signal -- surfaced for regen, not a hard fact-hazard.
_PA_CLAIM_RE = re.compile(r"(\d{2,4})\s+(?:plate\s+appearances|pa)\b", re.IGNORECASE)


def pa_consistency_problems(text: str, grounding: dict) -> list[str]:
    """A read PA count that does not match the grounding sample. Soft signal."""
    sample_context = (grounding or {}).get("sample_context")
    sample = sample_context.get("sample") if isinstance(sample_context, dict) else None
    if not isinstance(sample, (int, float)) or isinstance(sample, bool) or sample <= 0:
        return []
    unit = str(sample_context.get("sample_unit") or "").upper()
    if unit and unit != "PA":
        return []
    target = round(float(sample))
    out: list[str] = []
    for match in _PA_CLAIM_RE.finditer(text or ""):
        cited = int(match.group(1))
        if abs(cited - target) > 1:
            out.append(
                f"read cites {cited} PA but the grounding sample is {target} PA"
            )
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
    derived = derived_word_number_problems(text)
    handedness = handedness_problems(text, grounding)
    slash = triple_slash_problems(text, grounding)
    style = style_problems(text)
    role_vocab = role_vocab_problems(text, grounding)
    projection_claims = (
        uncalibrated_projection_claims(text)
        if (
            (grounding or {}).get("player_type") == "prospect"
            or (grounding or {}).get("peak_projection_detail")
            or (grounding or {}).get("peak_projection")
        )
        else []
    )
    level_attribution = level_attribution_problems(text, grounding)
    count_role = count_role_problems(text, grounding)
    league_scaffold = league_average_scaffold_problems(text)
    pa_consistency = pa_consistency_problems(text, grounding)
    return {
        "banned": banned,
        "unsupported_numbers": numbers,
        "derived_word_number_problems": derived,
        "handedness_problems": handedness,
        "triple_slash_problems": slash,
        "style_problems": style,
        "role_vocab_problems": role_vocab,
        "uncalibrated_projection_claims": projection_claims,
        "level_attribution_problems": level_attribution,
        "count_role_problems": count_role,
        "league_average_scaffold_problems": league_scaffold,
        "pa_consistency_problems": pa_consistency,
        # style gates ok (drives retry + regen) but not hard_ok — a formulaic read is
        # a regen candidate, not a factual hazard. role_vocab is a wrong-fact-shaped
        # error (same class as handedness) so it gates hard_ok too.
        # derived_word_number_problems is a soft signal like unsupported_numbers/style:
        # a word-form derived delta is a regen candidate, not a hard fact-hazard.
        # level_attribution + count_role are wrong-fact class (misattributed pooled level,
        # fabricated strikeout count) -> gate hard_ok. league_average_scaffold (drift
        # variants) and pa_consistency are soft -> gate ok only.
        "ok": (
            not banned and not numbers and not derived and not handedness
            and not slash and not style and not role_vocab
            and not projection_claims
            and not level_attribution and not count_role
            and not league_scaffold and not pa_consistency
        ),
        "hard_ok": (
            not banned and not handedness and not slash and not role_vocab
            and not projection_claims
            and not level_attribution and not count_role
        ),
    }
