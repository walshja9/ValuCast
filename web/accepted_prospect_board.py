"""Public, pinned v266 export reader. No experiment/model imports or execution."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import io
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

from web.search_fold import fold

CSV_NAME = "ValuCast_Combined_Prospect_Board_v2.6.6.csv"
HEADER = ("Rank", "MLBAM ID", "Player", "Role", "Y12 Surplus", "Y24 Surplus", "Evidence Confidence")
ROLES = ("hitter", "pitcher", "two_way")
DATE = "2026-08-26T12:00:00Z"
KEYS = {"schema", "model_version", "decision_date", "terminal_commit", "registration_sha256",
        "accepted_reproduction_binding_sha256", "production_predictions_sha256", "public_snapshot_sha256",
        "csv_sha256", "byte_count", "row_count", "role_counts"}


class BoardError(ValueError):
    """The selected public board is missing, invalid or not the pinned artifact."""


@dataclass(frozen=True)
class BoardRow:
    rank: int
    mlbam_id: int
    name: str
    role: str
    y12_text: str
    y24_text: str
    confidence: str

    @property
    def id(self):
        return f"v266-{self.mlbam_id}"

    @property
    def y12_display(self):
        return format(Decimal(self.y12_text), ".2f")

    @property
    def y24_display(self):
        return format(Decimal(self.y24_text), ".2f")


@dataclass(frozen=True)
class Board:
    rows: tuple[BoardRow, ...]
    csv_bytes: bytes
    metadata: Mapping
    metadata_sha256: str

    def filtered(self, search="", role=""):
        query = fold(search)
        return tuple(row for row in self.rows
                     if (not query or query in fold(row.name))
                     and (not role or row.role == role
                          or role in {"hitter", "pitcher"} and row.role == "two_way"))

    def get(self, player_id):
        return next((row for row in self.rows if row.id == player_id), None)


@dataclass(frozen=True)
class BoardSelection:
    selected: bool
    board: Board | None = None
    error: str | None = None


def _require(ok, message):
    if not ok:
        raise BoardError(message)


def _closed_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate metadata key")
        result[key] = value
    return result


def _nonfinite(value):
    raise BoardError(f"nonfinite metadata number: {value}")


def load_board(directory, expected_metadata_sha256):
    """Load one externally pinned, complete pair into immutable process memory."""
    try:
        _require(isinstance(expected_metadata_sha256, str)
                 and re.fullmatch(r"[0-9a-f]{64}", expected_metadata_sha256), "invalid metadata pin")
        root = Path(directory)
        raw = (root / "board_metadata.json").read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == expected_metadata_sha256, "metadata pin mismatch")
        metadata = json.loads(raw, object_pairs_hook=_closed_pairs, parse_constant=_nonfinite)
        _require(type(metadata) is dict and set(metadata) == KEYS, "metadata field set differs")
        _require(json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                            allow_nan=False).encode("utf-8") == raw, "metadata is not canonical")
        _require(metadata["schema"] == "valucast_prospect_v2_6_6_board_export_v1"
                 and metadata["model_version"] == "v2.6.6" and metadata["decision_date"] == DATE,
                 "unsupported board identity or forecast date")
        for name in ("terminal_commit", "registration_sha256", "accepted_reproduction_binding_sha256",
                     "production_predictions_sha256", "public_snapshot_sha256", "csv_sha256"):
            length = 40 if name == "terminal_commit" else 64
            _require(type(metadata[name]) is str and re.fullmatch(f"[0-9a-f]{{{length}}}", metadata[name]),
                     f"invalid {name}")
        for name in ("byte_count", "row_count"):
            _require(type(metadata[name]) is int and metadata[name] > 0, f"invalid {name}")
        counts = metadata["role_counts"]
        _require(type(counts) is dict and set(counts) == set(ROLES)
                 and all(type(count) is int and count >= 0 for count in counts.values()), "invalid role counts")
        body = (root / CSV_NAME).read_bytes()
        _require(len(body) == metadata["byte_count"] and hashlib.sha256(body).hexdigest() == metadata["csv_sha256"],
                 "CSV bytes differ from pinned metadata")
        _require(body.startswith(b"\xef\xbb\xbf"), "CSV lacks UTF-8 BOM")
        parsed = list(csv.reader(io.StringIO(body.decode("utf-8-sig"), newline=""), strict=True))
        _require(parsed and tuple(parsed[0]) == HEADER, "CSV header differs")
        output = io.StringIO(newline="")
        csv.writer(output).writerows(parsed)
        _require(output.getvalue().encode("utf-8-sig") == body, "CSV serialization is not canonical BOM/CRLF")
        rows = []
        for fields in parsed[1:]:
            _require(len(fields) == 7, "CSV row width differs")
            rank, identity, name, role, y12, y24, confidence = fields
            _require(re.fullmatch(r"[1-9][0-9]*", rank) and re.fullmatch(r"[1-9][0-9]*", identity),
                     "invalid rank or MLBAM ID")
            _require(name.strip() and role in ROLES and confidence in {"high", "moderate", "low"},
                     "invalid name, role or confidence")
            for value in (y12, y24):
                _require(re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?", value)
                         and math.isfinite(float(value)), "invalid surplus")
            rows.append(BoardRow(int(rank), int(identity), name, role, y12, y24, confidence))
        _require(len(rows) == metadata["row_count"] and len({row.mlbam_id for row in rows}) == len(rows),
                 "CSV count or unique identities differ")
        _require([row.rank for row in rows] == list(range(1, len(rows) + 1)), "ranks are not contiguous")
        ordered = sorted(rows, key=lambda row: (-Decimal(row.y24_text), -Decimal(row.y12_text), row.mlbam_id))
        _require(rows == ordered, "rows differ from sealed surplus order")
        _require(counts == {role: sum(row.role == role for row in rows) for role in ROLES}, "role counts differ")
        metadata["role_counts"] = MappingProxyType(counts)
        return Board(tuple(rows), body, MappingProxyType(metadata), expected_metadata_sha256)
    except BoardError:
        raise
    except (OSError, ValueError, TypeError, csv.Error, OverflowError) as error:
        raise BoardError(f"cannot read selected public board: {error}") from error


def select_board(environ):
    names = ("VALUCAST_PROSPECT_BOARD_DIR", "VALUCAST_PROSPECT_BOARD_METADATA_SHA256")
    if not any(name in environ for name in names):
        return BoardSelection(False)
    if not all(environ.get(name) for name in names):
        return BoardSelection(True, error="Both accepted prospect board settings are required")
    try:
        return BoardSelection(True, load_board(*(environ[name] for name in names)))
    except BoardError as error:
        return BoardSelection(True, error=str(error))
