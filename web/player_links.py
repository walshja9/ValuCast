"""External player-page links (FanGraphs, Baseball Savant) where ids exist.

Links are plain outbound anchors — ValuCast never fetches these sites at
runtime. A player with no usable id simply gets no links ("where available").
"""
from __future__ import annotations

import re
import unicodedata


def _name_slug(name: str) -> str:
    """FanGraphs-style slug: 'José Ramírez' -> 'jose-ramirez'."""
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def fangraphs_url(name: str, fangraphs_id: str | int | None) -> str | None:
    fid = str(fangraphs_id or "").strip()
    if not fid:
        return None
    return f"https://www.fangraphs.com/players/{_name_slug(name) or 'player'}/{fid}"


def savant_url(mlbam_id: str | int | None) -> str | None:
    mid = str(mlbam_id or "").strip()
    # Savant pages exist only for MLBAM-id'd players (numeric ids).
    if not mid.isdigit():
        return None
    return f"https://baseballsavant.mlb.com/savant-player/{mid}"


def build_player_links(
    name: str,
    mlbam_id: str | int | None = None,
    fangraphs_id: str | int | None = None,
) -> list[dict]:
    """[{"label", "url"}] for the card's outbound-links row; [] if no ids."""
    links = []
    savant = savant_url(mlbam_id)
    if savant:
        links.append({"label": "Baseball Savant", "url": savant})
    fangraphs = fangraphs_url(name, fangraphs_id)
    if fangraphs:
        links.append({"label": "FanGraphs", "url": fangraphs})
    return links
