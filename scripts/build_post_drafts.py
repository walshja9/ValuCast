#!/usr/bin/env python3
"""Daily post-drafts digest for @ValuCastHQ.

Scans the freshly built public artifacts each morning, finds post-worthy events,
and renders 2-3 ready-to-paste drafts from DETERMINISTIC templates -- every number
is interpolated straight from the committed artifact row, nothing is computed or
invented here. Nothing auto-posts: the digest prints to stdout, and ``--send``
relays it to Telegram so Alex can pick one and paste it.

Event scanners (v1, priority order a > b > c > d), each diffing TODAY's committed
artifact in ``data/models/`` against the most recent PRIOR dated mirror in
``data/prediction_archive/<model>/`` (the same-date mirror the pipeline writes is
byte-identical to the committed model, so the prior mirror is the second-most-recent
file -- ``sorted(files)[-2]``):

  a. NEW RECEIPT  -- a new identity_key in receipts[] vs the prior mirror.
  b. NEW MISS     -- a new identity_key in misses[] vs the prior mirror.
  c. LEDGER CLOSE -- funnel closed_caught_up increased vs a prior scorecard snapshot
                     (gated on the AOTC scorecard's own publish gate).
  d. BIG MOVER    -- top fresh riser/faller, |score_delta| >= 5, not in yesterday's
                     top list.

If no events fire, the digest is a single honest "quiet day" line.

Standalone; stdlib only (urllib for Telegram). Writes no artifact file -- drafts
must never be committed to a public repo before posting.
"""
from __future__ import annotations

import json
import os
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "data" / "models"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive"

MAX_DRAFTS = 3
TELEGRAM_MAX_CHARS = 4096
MOVER_MIN_DELTA = 5.0

# Share graphics to attach per event family.
RECEIPTS_SHARE_PNG = "https://valucast.app/receipts/share-card.png"
MOVERS_SHARE_PNG = "https://valucast.app/movers/share-card.png"
PLAYER_CARD_URL = "https://valucast.app/prospects/player-card/{player_id}"

# Public URLs the drafts point readers to.
RECEIPTS_PAGE = "valucast.app/receipts"
LEDGER_PAGE = "valucast.app/ledger"
MOVERS_PAGE = "valucast.app/movers"

# The arrival caveat that EVERY receipt draft must carry.
ARRIVAL_CAVEAT = (
    "Receipts score arrival, not career outcome -- outcome calls live on the ledger."
)

# ---------------------------------------------------------------------------
# ToS guardrail: never emit a per-source board name. The receipts/movers rows
# already carry ToS-safe AGGREGATE consensus strings (field_label like
# "1 board, ~#512", consensus_rank, divergence); these tokens are the external
# board source keys (everything NOT internal per prospects/buys._INTERNAL_SOURCES)
# plus the brand names they stand for. A rendered draft that contains any of them
# means a board name leaked -- raise, don't post.
# ---------------------------------------------------------------------------
_EXTERNAL_SOURCE_KEYS = ("hkb", "pipeline", "pl", "sts", "fg")
_EXTERNAL_SOURCE_NAMES = (
    "prospects live",
    "prospectslive",
    "prospects-live",
    "fangraphs",
    "keith law",
    "the board",
    "mlb pipeline",
    "mlb.com pipeline",
    "razzball",
    "baseball prospectus",
    "prospects1500",
)
_FORBIDDEN_STRINGS = _EXTERNAL_SOURCE_NAMES + _EXTERNAL_SOURCE_KEYS


class ForbiddenStringError(RuntimeError):
    """A rendered draft leaked a per-source board name or non-ASCII text."""


def _forbidden_strings(text: str) -> list[str]:
    """Return every ToS-forbidden token found in ``text`` (case-insensitive,
    word-boundary matched so 'pl' inside 'player' or 'sts' inside 'consists'
    never false-positives). Empty list means the draft is clean."""
    hay = text.lower()
    hits = []
    for token in _FORBIDDEN_STRINGS:
        if " " in token:
            # Multi-word brand names: plain substring is fine.
            if token in hay:
                hits.append(token)
            continue
        # Single tokens (source keys / one-word brands): boundary match so short
        # keys can't hide inside ordinary words.
        start = 0
        while True:
            idx = hay.find(token, start)
            if idx < 0:
                break
            before = hay[idx - 1] if idx > 0 else ""
            after = hay[idx + len(token)] if idx + len(token) < len(hay) else ""
            if not before.isalnum() and not after.isalnum():
                hits.append(token)
                break
            start = idx + 1
    return hits


def _fold_ascii(text: str) -> str:
    """Fold accented characters to their ASCII base (Vasquez, Pena) so real
    player names arriving from board artifacts pass the ASCII guard. ONLY
    combining marks are stripped -- em-dashes and smart quotes survive folding
    unchanged, so the guard still catches the defect class it exists for."""
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def _assert_draft_clean(body: str) -> None:
    """A rendered draft must be ASCII-safe (no em-dashes / smart punctuation)
    and free of any per-source board name. Raise on either -- a bad draft must
    never reach Telegram."""
    try:
        body.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ForbiddenStringError(
            f"Draft is not ASCII-safe (non-ASCII char): {exc}"
        ) from None
    hits = _forbidden_strings(body)
    if hits:
        raise ForbiddenStringError(
            f"Draft leaked forbidden board source name(s): {sorted(set(hits))}"
        )


# ---------------------------------------------------------------------------
# Artifact loading + prior-mirror resolution.
# ---------------------------------------------------------------------------
def _load_json(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _load_model(name: str):
    """Today's committed artifact from data/models/, or None if absent."""
    path = MODELS_DIR / f"{name}.json"
    if not path.exists():
        return None
    return _load_json(path)


def _prior_mirror(name: str):
    """The most recent PRIOR dated mirror for a model.

    The daily pipeline snapshots the committed artifact into data/prediction_archive/
    on the same run that updates data/models/, so the newest mirror is byte-identical
    to today's committed file. The correct prior baseline is therefore the
    SECOND-most-recent mirror (sorted[-2]) -- robust to the inconsistent generated_at
    date formats and self-correcting if a day's write is ever skipped. Returns None
    when fewer than two mirrors exist."""
    mirror_dir = ARCHIVE_DIR / name
    if not mirror_dir.is_dir():
        return None
    files = sorted(p for p in mirror_dir.iterdir() if p.suffix == ".json")
    if len(files) < 2:
        return None
    return _load_json(files[-2])


# ---------------------------------------------------------------------------
# A Draft bundles the pasteable body with the operator header (source, why it
# fired, the graphic to attach). Priority orders the digest and enforces the cap.
# ---------------------------------------------------------------------------
class Draft:
    __slots__ = ("priority", "source", "why", "graphic_url", "body", "extra_url")

    def __init__(self, priority, source, why, graphic_url, body, extra_url=None):
        self.priority = priority
        self.source = source
        self.why = why
        self.graphic_url = graphic_url
        self.body = body
        self.extra_url = extra_url

    def render(self) -> str:
        header = f"[{self.source}] {self.why}\nAttach: {self.graphic_url}"
        if self.extra_url:
            header += f"\nPlayer card: {self.extra_url}"
        return f"{header}\n\n{self.body}"


# ---------------------------------------------------------------------------
# Scanner a: NEW RECEIPT (highest priority).
# ---------------------------------------------------------------------------
def _receipt_draft_body(row: dict) -> str:
    """Render a single new-receipt draft entirely from the receipt row's own
    fields. Scored rows carry consensus_rank + divergence (a public-board median,
    already aggregate/ToS-safe); the row does NOT carry a board count, so the
    template does not claim one. Field-unranked rows carry the ToS-safe aggregate
    field_label instead of a number."""
    name = row.get("name") or "the prospect"
    team = row.get("team") or "-"
    vc = row.get("valucast_rank")
    days_early = row.get("flagged_days_early")

    if row.get("field_unranked"):
        field_label = row.get("field_label") or "no public board inside 600"
        line = (
            f"Called up: {name} ({team}). ValuCast had him #{vc} -- "
            f"{field_label}, that's why there's no number on him."
        )
    else:
        cons = row.get("consensus_rank")
        div = row.get("divergence")
        line = (
            f"Called up: {name} ({team}). ValuCast had him #{vc} -- "
            f"the field ~#{cons} (+{div})."
        )

    if isinstance(days_early, int) and days_early > 0:
        line += f" We flagged him {days_early}d before the call."

    return (
        f"{line}\n\n"
        f"Logged automatically the day he reached the majors, like every "
        f"call-up: {RECEIPTS_PAGE}\n\n{ARRIVAL_CAVEAT}"
    )


def scan_new_receipts(today, prior) -> list[Draft]:
    if not isinstance(today, dict):
        return []
    prior_keys = _identity_keys(prior, "receipts") if isinstance(prior, dict) else set()
    drafts = []
    for row in today.get("receipts") or []:
        key = row.get("identity_key")
        if not key or key in prior_keys:
            continue
        why = (
            f"NEW receipt: {row.get('name')} reached the majors "
            f"(not in prior mirror)."
        )
        drafts.append(
            Draft(
                priority=1,
                source="RECEIPTS",
                why=why,
                graphic_url=RECEIPTS_SHARE_PNG,
                body=_receipt_draft_body(row),
            )
        )
    return drafts


# ---------------------------------------------------------------------------
# Scanner b: NEW MISS / BEHIND (accountability lane).
# ---------------------------------------------------------------------------
def _miss_draft_body(row: dict) -> str:
    """The field beat us on this call-up. Same numbers-from-artifact discipline:
    consensus_rank and valucast_rank come straight off the miss row."""
    name = row.get("name") or "the prospect"
    team = row.get("team") or "-"
    vc = row.get("valucast_rank")
    cons = row.get("consensus_rank")
    return (
        f"The field beat us on {name} ({team}). They had him ~#{cons}; "
        f"ValuCast had him #{vc}.\n\n"
        f"We log these too -- that's the point. {RECEIPTS_PAGE}"
    )


def scan_new_misses(today, prior) -> list[Draft]:
    if not isinstance(today, dict):
        return []
    prior_keys = _identity_keys(prior, "misses") if isinstance(prior, dict) else set()
    drafts = []
    for row in today.get("misses") or []:
        key = row.get("identity_key")
        if not key or key in prior_keys:
            continue
        why = f"NEW miss: the field beat us on {row.get('name')} (not in prior mirror)."
        drafts.append(
            Draft(
                priority=2,
                source="RECEIPTS",
                why=why,
                graphic_url=RECEIPTS_SHARE_PNG,
                body=_miss_draft_body(row),
            )
        )
    return drafts


# ---------------------------------------------------------------------------
# Scanner c: LEDGER CLOSE.
#
# The closed_caught_up funnel lives only in the AOTC scorecard
# (data/models/valucast_ahead_of_consensus_scorecard.json). That artifact has no
# dated mirror, so a day-over-day increase can only be detected against a prior
# scorecard snapshot supplied by the caller (tests inject one; in production none
# exists yet, so this scanner stays silent -- honest, never fabricated). It is also
# gated on the scorecard's OWN publish gate (gate.publishable): the ledger doesn't
# publish while accruing, so neither do its drafts.
# ---------------------------------------------------------------------------
def _load_scorecard():
    path = MODELS_DIR / "valucast_ahead_of_consensus_scorecard.json"
    if not path.exists():
        return None
    return _load_json(path)


def scan_ledger_close(scorecard, prior_scorecard) -> list[Draft]:
    if not isinstance(scorecard, dict):
        return []
    gate = scorecard.get("gate") or {}
    if not gate.get("publishable"):
        return []
    funnel = scorecard.get("funnel") or {}
    now = funnel.get("closed_caught_up")
    if not isinstance(now, int):
        return []
    if not isinstance(prior_scorecard, dict):
        # No prior snapshot to establish an increase -- do not fabricate a close.
        return []
    prior_funnel = prior_scorecard.get("funnel") or {}
    before = prior_funnel.get("closed_caught_up")
    if not isinstance(before, int) or now <= before:
        return []

    newly_closed = now - before
    # Try to name the closing player(s) from the per-player calls. The scorecard's
    # calls[] carry status == "closed_caught_up" with the aggregate-safe consensus_now.
    prior_closed = _closed_call_keys(prior_scorecard)
    fresh = [
        c
        for c in scorecard.get("calls") or []
        if c.get("status") == "closed_caught_up"
        and c.get("identity_key")
        and c.get("identity_key") not in prior_closed
    ]

    if len(fresh) == 1:
        c = fresh[0]
        body = (
            f"Another call closed all the way: the field came the rest of the way "
            f"to us on {c.get('name')} -- now ~#{c.get('consensus_now')}, "
            f"where ValuCast had him. Ledger: {LEDGER_PAGE}"
        )
        why = f"LEDGER close: {c.get('name')} caught up to us."
    else:
        # Can't cleanly attribute a single player -> aggregate framing (counts only).
        noun = "call" if newly_closed == 1 else "calls"
        body = (
            f"The ledger closed {newly_closed} more {noun} all the way: "
            f"the field came the rest of the way to us. Ledger: {LEDGER_PAGE}"
        )
        why = f"LEDGER close: closed_caught_up {before} -> {now}."

    return [
        Draft(
            priority=3,
            source="LEDGER",
            why=why,
            graphic_url=RECEIPTS_SHARE_PNG,
            body=body,
        )
    ]


def _closed_call_keys(scorecard) -> set:
    if not isinstance(scorecard, dict):
        return set()
    return {
        c.get("identity_key")
        for c in scorecard.get("calls") or []
        if c.get("status") == "closed_caught_up" and c.get("identity_key")
    }


# ---------------------------------------------------------------------------
# Scanner d: BIG MOVER (top fresh riser/faller).
# ---------------------------------------------------------------------------
# The digest must read the SAME board the attached share card renders: the page
# and the bare /movers/share-card.png default to the 14d window
# (app.DEFAULT_MOVER_WINDOW = 14). The artifact's top-level rising/cooling lists
# are the era-clamped legacy view (e.g. "over 18d" since the 6/22 re-baseline),
# which contradicts the card's pills (7/14/21/30) in a public post.
_MOVER_WINDOW_KEY = "14d"


def _mover_board(payload) -> dict:
    """The default-window board (windows['14d']); legacy top-level fallback."""
    if not isinstance(payload, dict):
        return {}
    windows = payload.get("windows")
    if isinstance(windows, dict) and isinstance(windows.get(_MOVER_WINDOW_KEY), dict):
        return windows[_MOVER_WINDOW_KEY]
    return payload


def _mover_ids(payload, key) -> set:
    board = _mover_board(payload)
    return {r.get("id") for r in board.get(key) or [] if r.get("id")}


def _mover_draft_body(row: dict, direction: str) -> str:
    """Render from the mover row's own fields. ``why`` on the row is the exact
    stat line the movers board carries (e.g. 'A 294 PA, .925 OPS, ...') -- pasted
    verbatim, never recomputed."""
    name = row.get("name") or "the prospect"
    team = row.get("team") or "-"
    level = row.get("level") or "-"
    delta = abs(row.get("score_delta") or 0)
    window = row.get("window_days")
    stat_line = row.get("why") or ""
    verb = "up" if direction == "rising" else "down"
    return (
        f"{name} ({team}, {level}) is {verb} {delta:g} on the ValuCast board over "
        f"the last {window}d -- {stat_line}. Card: {MOVERS_PAGE}"
    )


def scan_big_mover(today, prior) -> list[Draft]:
    if not isinstance(today, dict):
        return []
    board = _mover_board(today)
    prior_rising = _mover_ids(prior, "rising")
    prior_cooling = _mover_ids(prior, "cooling")

    def top_fresh(key, prior_ids):
        for row in board.get(key) or []:
            if abs(row.get("score_delta") or 0) < MOVER_MIN_DELTA:
                continue
            if row.get("id") in prior_ids:
                continue
            return row
        return None

    riser = top_fresh("rising", prior_rising)
    faller = top_fresh("cooling", prior_cooling)

    # One BIG MOVER draft per day: prefer the larger fresh move (riser vs faller).
    candidates = []
    if riser is not None:
        candidates.append(("rising", riser))
    if faller is not None:
        candidates.append(("cooling", faller))
    if not candidates:
        return []
    direction, row = max(candidates, key=lambda c: abs(c[1].get("score_delta") or 0))

    verb = "riser" if direction == "rising" else "faller"
    why = (
        f"BIG mover: fresh top {verb} {row.get('name')} "
        f"({row.get('score_delta'):+g} over {row.get('window_days')}d)."
    )
    player_id = row.get("player_id")  # vc_prospect_* form resolves on the card page
    extra = PLAYER_CARD_URL.format(player_id=player_id) if player_id else None
    return [
        Draft(
            priority=4,
            source="MOVERS",
            why=why,
            graphic_url=MOVERS_SHARE_PNG,
            body=_mover_draft_body(row, direction),
            extra_url=extra,
        )
    ]


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------
def _identity_keys(payload, key) -> set:
    if not isinstance(payload, dict):
        return set()
    return {r.get("identity_key") for r in payload.get(key) or [] if r.get("identity_key")}


# ---------------------------------------------------------------------------
# Digest assembly.
# ---------------------------------------------------------------------------
QUIET_LINE = (
    "Quiet day -- nothing worth posting beats a filler post. "
    "(Scanned receipts, ledger, movers.)"
)


def collect_drafts(
    receipts_today,
    receipts_prior,
    scorecard,
    scorecard_prior,
    movers_today,
    movers_prior,
) -> list[Draft]:
    """Run every scanner in priority order and cap at MAX_DRAFTS."""
    drafts: list[Draft] = []
    drafts += scan_new_receipts(receipts_today, receipts_prior)
    drafts += scan_new_misses(receipts_today, receipts_prior)
    drafts += scan_ledger_close(scorecard, scorecard_prior)
    drafts += scan_big_mover(movers_today, movers_prior)
    drafts.sort(key=lambda d: d.priority)
    return drafts[:MAX_DRAFTS]


def build_digest(drafts: list[Draft], today: date | None = None) -> str:
    """The full pasteable digest: date header + each draft separated by a rule.
    Guardrails run on every draft body here -- a leaked board name or non-ASCII
    char raises before anything can be printed or sent."""
    day = (today or datetime.now(timezone.utc).date()).isoformat()
    header = f"ValuCast post-drafts -- {day}"
    if not drafts:
        return f"{header}\n\n{QUIET_LINE}"

    rule = "\n\n" + ("-" * 40) + "\n\n"
    rendered = []
    for draft in drafts:
        # Fold accents BEFORE the guard: an accented player name is data, not
        # a defect. The guard then runs on the exact text that ships.
        text = _fold_ascii(draft.render())
        _assert_draft_clean(text)
        rendered.append(text)
    return header + "\n\n" + rule.join(rendered)


def build_digest_from_disk(today: date | None = None) -> str:
    """Load every artifact from disk, run the scanners, and return the digest."""
    receipts_today = _load_model("valucast_call_up_receipts")
    receipts_prior = _prior_mirror("valucast_call_up_receipts")
    scorecard = _load_scorecard()
    movers_today = _load_model("valucast_prospect_movers")
    movers_prior = _prior_mirror("valucast_prospect_movers")
    drafts = collect_drafts(
        receipts_today,
        receipts_prior,
        scorecard,
        None,  # no scorecard mirror exists -> ledger-close scanner stays silent
        movers_today,
        movers_prior,
    )
    return build_digest(drafts, today=today)


# ---------------------------------------------------------------------------
# Telegram.
# ---------------------------------------------------------------------------
def _split_for_telegram(text: str, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Split a long digest into <=limit-char chunks, preferring paragraph breaks
    then line breaks so drafts don't get chopped mid-sentence."""
    if len(text) <= limit:
        return [text]
    chunks = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut <= 0:
            cut = window.rfind("\n")
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip("\n"))
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


def send_to_telegram(text: str, token: str, chat_id: str) -> None:
    """Send the digest as plain text (no markdown parse mode -> no escaping bugs),
    splitting into multiple messages when over the 4096-char limit."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in _split_for_telegram(text):
        payload = urllib.parse.urlencode(
            {"chat_id": chat_id, "text": chunk}
        ).encode("utf-8")
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    send = "--send" in argv[1:]
    digest = build_digest_from_disk()
    print(digest)

    if not send:
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        # CI must never fail on missing secrets.
        print(
            "\nTelegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID "
            "missing) -- printed only."
        )
        return 0

    try:
        send_to_telegram(digest, token, chat_id)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"\nTelegram send failed: {exc}")
        return 0
    print("\nSent to Telegram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
