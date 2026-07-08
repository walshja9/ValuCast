"""Accent-insensitive text folding for player-name search.

Board names carry their real diacritics ("Héctor Rodríguez") but nobody types
them into a search box, so every name filter must compare folded text on BOTH
sides: strip combining marks, then casefold.
"""
from __future__ import annotations

import unicodedata


def fold(text: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
