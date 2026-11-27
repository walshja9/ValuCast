from __future__ import annotations

import json
from pathlib import Path

from .models import LeagueConfig


def load_league_config(path: str | Path) -> LeagueConfig:
    with Path(path).open("r", encoding="utf-8") as file:
        return LeagueConfig.from_dict(json.load(file))
