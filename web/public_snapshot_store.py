"""Load and validate ValuCast-owned public dynasty snapshots."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .public_snapshot_models import PublicSnapshotRow

logger = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSIONS = {"1.0"}
ARTIFACT_NAME = "valucast_public_dynasty_snapshot"
REQUIRED_RECORD_FIELDS = (
    "id",
    "player_type",
    "name",
    "mlbam_id",
    "role",
    "positions",
    "rank",
    "value",
    "value_scale",
    "value_source",
    "confidence",
    "updated_at",
)
PROHIBITED_TRUE_FLAGS = (
    "dd_values_used",
    "dd_ranks_used",
    "external_rankings_used_for_score",
    "market_values_used_for_score",
)


def _identity_key(record: dict) -> tuple[str, str] | None:
    mlbam_id = record.get("mlbam_id")
    role = record.get("role")
    if mlbam_id in (None, "") or role not in {"hitter", "pitcher"}:
        return None
    return str(mlbam_id), role


def validate_public_snapshot_payload(payload: dict) -> list[str]:
    problems: list[str] = []
    if payload.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        problems.append(f"unsupported schema_version {payload.get('schema_version')}")
    if payload.get("artifact") != ARTIFACT_NAME:
        problems.append(f"artifact must be {ARTIFACT_NAME}")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")

    source_policy = payload.get("source_policy") or {}
    for flag in PROHIBITED_TRUE_FLAGS:
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")

    players = payload.get("players")
    if not isinstance(players, list) or not players:
        problems.append("players must be a non-empty list")
        return problems

    ids = []
    identity_keys = []
    for index, record in enumerate(players):
        if not isinstance(record, dict):
            problems.append(f"players[{index}] must be an object")
            continue
        for field in REQUIRED_RECORD_FIELDS:
            if record.get(field) in (None, ""):
                problems.append(f"players[{index}].{field} is required")
        if not isinstance(record.get("rank"), int):
            problems.append(f"players[{index}].rank must be an integer")
        if not isinstance(record.get("value"), (int, float)):
            problems.append(f"players[{index}].value must be numeric")
        ids.append(record.get("id"))
        key = _identity_key(record)
        if key:
            identity_keys.append(key)

    if len(ids) != len(set(ids)):
        problems.append("duplicate row ids")
    if len(identity_keys) != len(set(identity_keys)):
        problems.append("duplicate MLBAM+role identities")

    validation = payload.get("validation") or {}
    if validation.get("duplicate_identity_count", 0) != 0:
        problems.append("validation reports duplicate identities")
    if validation.get("required_fields_complete") is False:
        problems.append("validation reports incomplete required fields")
    return problems


class PublicSnapshotStore:
    """Loads the ValuCast public dynasty snapshot.

    `is_available` means the snapshot is structurally valid. `ready_for_live_consumers`
    is stricter and controls whether routes may consume it instead of the DD feed.
    """

    def __init__(self, path: str | Path) -> None:
        self._rows: list[PublicSnapshotRow] = []
        self._by_id: dict[str, PublicSnapshotRow] = {}
        self._is_available = False
        self._ready_for_live_consumers = False
        self._generated_at: str | None = None
        self._schema_version: str | None = None
        self._validation: dict = {}
        self._load(Path(path))

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.info("ValuCast public snapshot not found at %s", path)
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load ValuCast public snapshot: %s", exc)
            return

        problems = validate_public_snapshot_payload(raw)
        if problems:
            logger.warning("ValuCast public snapshot rejected: %s", "; ".join(problems))
            return

        rows = []
        try:
            for record in raw.get("players") or []:
                rows.append(PublicSnapshotRow.from_snapshot(record))
        except Exception as exc:  # noqa: BLE001
            logger.warning("ValuCast public snapshot row parsing failed: %s", exc)
            return

        rows.sort(key=lambda row: row.rank)
        self._rows = rows
        self._by_id = {row.id: row for row in rows}
        self._generated_at = raw.get("generated_at")
        self._schema_version = raw.get("schema_version")
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
    def schema_version(self) -> str | None:
        return self._schema_version

    @property
    def validation(self) -> dict:
        return dict(self._validation)

    def get_all(self) -> list[PublicSnapshotRow]:
        return list(self._rows)

    def get_by_id(self, row_id: str) -> PublicSnapshotRow | None:
        return self._by_id.get(row_id)

    def filter(
        self,
        player_type: str | None = None,
        position: str | None = None,
        search: str | None = None,
        pool: str | None = None,
    ) -> list[PublicSnapshotRow]:
        results = self._rows
        if player_type:
            results = [row for row in results if row.player_type == player_type]
        if pool:
            if pool == "prospect":
                results = [row for row in results if row.is_prospect]
            elif pool == "mlb":
                results = [row for row in results if not row.is_prospect]
            elif pool == "hitter":
                results = [
                    row
                    for row in results
                    if any(position not in ("SP", "RP", "P") for position in row.positions)
                ]
            elif pool == "pitcher":
                results = [
                    row
                    for row in results
                    if any(position in ("SP", "RP", "P") for position in row.positions)
                ]
        if position:
            results = [row for row in results if position in row.positions]
        if search:
            query = search.lower()
            results = [row for row in results if query in row.name.lower()]
        return results
