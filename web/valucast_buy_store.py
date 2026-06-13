"""Load and validate ValuCast-owned prospect buy signals."""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_SIGNAL_VERSIONS = {"0.1.0"}
PROHIBITED_TRUE_FLAGS = (
    "dd_values_used",
    "dd_ranks_used",
    "dd_context_used",
    "public_source_ranks_used",
    "external_rankings_used_for_score",
    "market_values_used_for_score",
)
REQUIRED_ROW_FIELDS = ("id", "name", "mlbam_id", "role", "rank", "score", "terms")


def validate_valucast_buy_payload(payload: dict) -> list[str]:
    problems = []
    if payload.get("status") != "shadow_only":
        problems.append("status must be shadow_only")
    if payload.get("signal_version") not in SUPPORTED_SIGNAL_VERSIONS:
        problems.append("unsupported signal_version")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")

    source_policy = payload.get("source_policy") or {}
    for flag in PROHIBITED_TRUE_FLAGS:
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")

    board = payload.get("board")
    if not isinstance(board, list) or not board:
        problems.append("board must be a non-empty list")
        return problems

    ids = []
    identities = []
    for index, row in enumerate(board):
        if not isinstance(row, dict):
            problems.append(f"board[{index}] must be an object")
            continue
        for field in REQUIRED_ROW_FIELDS:
            if row.get(field) in (None, ""):
                problems.append(f"board[{index}].{field} is required")
        if row.get("role") not in {"hitter", "pitcher"}:
            problems.append(f"board[{index}].role must be hitter or pitcher")
        if not isinstance(row.get("rank"), int):
            problems.append(f"board[{index}].rank must be an integer")
        if not isinstance(row.get("score"), (int, float)):
            problems.append(f"board[{index}].score must be numeric")
        ids.append(row.get("id"))
        identities.append((str(row.get("mlbam_id")), row.get("role")))

    if len(ids) != len(set(ids)):
        problems.append("duplicate row ids")
    if len(identities) != len(set(identities)):
        problems.append("duplicate MLBAM+role identities")

    validation = payload.get("validation") or {}
    if validation.get("duplicate_identity_count", 0) != 0:
        problems.append("validation reports duplicate identities")
    if validation.get("ranks_contiguous") is False:
        problems.append("validation reports non-contiguous ranks")
    return problems


class ValuCastBuyStore:
    """Loads ValuCast prospect buy signals.

    `is_available` means structurally valid. `ready_for_live_consumers` remains
    the promotion gate for `/buys`.
    """

    def __init__(self, path: str | Path) -> None:
        self._rows: list[dict] = []
        self._is_available = False
        self._ready_for_live_consumers = False
        self._generated_at: str | None = None
        self._validation: dict = {}
        self._load(Path(path))

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.info("ValuCast buy signals not found at %s", path)
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load ValuCast buy signals: %s", exc)
            return

        problems = validate_valucast_buy_payload(raw)
        if problems:
            logger.warning("ValuCast buy signals rejected: %s", "; ".join(problems))
            return

        rows = list(raw.get("board") or [])
        rows.sort(key=lambda row: row["rank"])
        self._rows = rows
        self._generated_at = raw.get("generated_at")
        self._validation = raw.get("validation") or {}
        self._ready_for_live_consumers = bool(
            self._validation.get("ready_for_live_consumers")
        )
        self._is_available = True

    @property
    def is_available(self) -> bool:
        return self._is_available

    @property
    def ready_for_live_consumers(self) -> bool:
        return self._ready_for_live_consumers

    @property
    def generated_at(self) -> str | None:
        return self._generated_at

    @property
    def validation(self) -> dict:
        return dict(self._validation)

    def get_all(self) -> list[dict]:
        return list(self._rows)
