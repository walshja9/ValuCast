"""Public board Time Machine: read the committed daily ``valucast_prospect_rank_v1``
board archive and replay any past date's board state (plan 026).

Fail-soft and network-free — reads committed JSON only (the ``StatcastStore``
precedent). Display-only replay of an archived artifact: NEVER a value input,
computes no new score (the archived ``score`` renders verbatim). Consensus is
the aggregate median + board count ONLY (ToS — no per-source ranks, historically
or otherwise): the raw ``context_only.source_ranks`` dict is reduced here and
never leaves this module.

The archive-read idiom (glob, stem-as-date, ``.get("board")``, fail-soft on
``OSError``/``ValueError``) mirrors the frozen ``prospects/ahead_of_consensus.py``
reference without importing from it. Unlike that module (which iterates every
file to compute streaks), this reader resolves ONE date per request and never
loads all archive files at once (~7 MB each).
"""
from __future__ import annotations

import json
import re
from bisect import bisect_left
from collections import OrderedDict
from datetime import date as _date
from pathlib import Path

from prospects.availability import eta_window_label
from prospects.buys import PROSPECT_BUYS_EPOCH_DATE  # read-only import (not frozen)

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"
# The comparability boundary is the model's re-baseline epoch — imported
# ready-made from prospects/buys.py, NEVER hardcoded (a future re-baseline
# moves the flag automatically because this is an import, not a literal).
EPOCH_DATE = PROSPECT_BUYS_EPOCH_DATE

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Consensus filter — copied from web/public_snapshot_models.py (NOT the frozen
# ahead_of_consensus.py; deliberately duplicated so this read surface never
# couples to the frozen AOTC module). Keep in sync with that file.
_INTERNAL_SOURCES = frozenset({"milb_perf", "milb_breakout", "cfr", "cfr_raw"})
_CONSENSUS_RANK_CAP = 600
_MIN_CONSENSUS_BOARDS = 2

# Bound the rendered board (the archive carries ~2,800 ranked rows; the page
# shows the top slice like the live board does).
_ROW_LIMIT = 300
# Bound the per-date parsed-view cache so a crawler hitting every archive date
# cannot pin ~30 x ~7 MB parses in each worker (plan 026 STOP condition).
_CACHE_MAX = 8


def _consensus(source_ranks: dict | None) -> dict | None:
    """Aggregate-only consensus: ``{"median", "board_count"}`` or ``None``.

    Applies the exact ``_INTERNAL_SOURCES`` / cap-600 / min-2-boards median the
    live board uses (``PublicSnapshotRow.public_source_consensus``). Never
    returns the raw per-source dict.
    """
    ranks = sorted(
        rank
        for source, rank in (source_ranks or {}).items()
        if source not in _INTERNAL_SOURCES
        and isinstance(rank, (int, float))
        and rank <= _CONSENSUS_RANK_CAP
    )
    if len(ranks) < _MIN_CONSENSUS_BOARDS:
        # a single board is not a consensus (MIN_BOARDS)
        return None
    midpoint = len(ranks) // 2
    if len(ranks) % 2:
        median = ranks[midpoint]
    else:
        median = (ranks[midpoint - 1] + ranks[midpoint]) / 2
    return {"median": round(median), "board_count": len(ranks)}


def nearest_board_date(date: str | None, dates: list[str]) -> str | None:
    """Closest available ISO date to a requested one, for the honest
    unavailable-state suggestion link. Callers must present it AS a different
    date — never as a silent substitute for the requested one."""
    if not dates:
        return None
    if not date or not _DATE_RE.fullmatch(date):
        return dates[-1]
    try:
        requested = _date.fromisoformat(date)
    except ValueError:
        return dates[-1]
    idx = bisect_left(dates, date)
    if idx == 0:
        return dates[0]
    if idx >= len(dates):
        return dates[-1]
    before, after = dates[idx - 1], dates[idx]
    try:
        gap_before = (requested - _date.fromisoformat(before)).days
        gap_after = (_date.fromisoformat(after) - requested).days
    except ValueError:
        return dates[-1]
    return before if gap_before <= gap_after else after


def _comparability(date: str) -> str:
    """Pre/post scoring-epoch comparability — the ONE place the boundary
    ternary lives, so ``quality_flag`` and ``board_for`` views can never
    disagree about which side of the epoch a date falls on."""
    return "pre-baseline" if date < EPOCH_DATE else "clean"


def _eta_display(row: dict) -> str | None:
    eta = row.get("eta")
    if eta not in (None, ""):
        return str(eta)
    return eta_window_label(row.get("eta_window"))


class BoardTimeMachineStore:
    """Date-parameterized fail-soft reader over the committed board archive.

    Reads ONE archive file per requested date; ``available_dates()`` never
    loads file bodies (stat/stem only, cached on directory mtime).
    """

    def __init__(self, archive_dir: Path = ARCHIVE_DIR, row_limit: int = _ROW_LIMIT):
        self._dir = Path(archive_dir)
        self._row_limit = row_limit
        self._dates_cache: tuple[float, list[str]] | None = None  # (dir mtime, dates)
        self._board_cache: OrderedDict[str, tuple[int, dict]] = OrderedDict()

    def available_dates(self) -> list[str]:
        """Sorted ISO dates with an archive file present. Stat/stem only."""
        try:
            dir_mtime = self._dir.stat().st_mtime
        except OSError:
            return []
        if self._dates_cache and self._dates_cache[0] == dir_mtime:
            return self._dates_cache[1]
        try:
            dates = sorted(
                p.stem for p in self._dir.glob("*.json") if _DATE_RE.fullmatch(p.stem)
            )
        except OSError:
            return []
        self._dates_cache = (dir_mtime, dates)
        return dates

    def quality_flag(self, date: str) -> str:
        """``unavailable`` (no file / junk date), ``pre-baseline`` (before the
        imported re-baseline epoch), else ``clean``."""
        if not date or not _DATE_RE.fullmatch(date):
            return "unavailable"
        try:
            if not (self._dir / f"{date}.json").exists():
                return "unavailable"
        except OSError:
            return "unavailable"
        return _comparability(date)

    def board_for(self, date: str) -> dict | None:
        """Thin card-ready view of one archived board, or ``None`` when the
        date has no readable archive (missing, malformed, junk shape)."""
        if not date or not _DATE_RE.fullmatch(date):
            return None  # junk shape never reaches the filesystem (traversal belt)
        path = self._dir / f"{date}.json"
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return None  # unavailable -> fail soft
        cached = self._board_cache.get(date)
        if cached and cached[0] == stamp:
            self._board_cache.move_to_end(date)
            return cached[1]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # unreadable -> fail soft (the ahead_of_consensus idiom)
        if not isinstance(payload, dict):
            return None
        board = payload.get("board") or []
        if not isinstance(board, list):
            return None
        rows = []
        for raw in board[: self._row_limit]:
            if not isinstance(raw, dict):
                continue
            rows.append(
                {
                    "rank": raw.get("rank"),
                    "name": raw.get("name"),
                    "role": raw.get("role"),
                    "team": raw.get("mlb_team"),
                    "level": raw.get("level"),
                    "age": raw.get("age"),
                    "positions": raw.get("positions") or [],
                    "score": raw.get("score"),
                    "confidence": raw.get("confidence"),
                    "eta_window": raw.get("eta_window"),
                    "eta_display": _eta_display(raw),
                    # Aggregate-only or None; the raw per-source dict is dropped
                    # here and never reaches a template (ToS).
                    "consensus": _consensus((raw.get("context_only") or {}).get("source_ranks")),
                }
            )
        view = {
            "date": payload.get("date") or date,
            "generated_at": payload.get("generated_at"),
            "rank_version": payload.get("rank_version"),
            "quality": _comparability(date),
            "rows": rows,
            "total_rows": len(board),
        }
        self._board_cache[date] = (stamp, view)
        self._board_cache.move_to_end(date)
        while len(self._board_cache) > _CACHE_MAX:
            self._board_cache.popitem(last=False)
        return view
