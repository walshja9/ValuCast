#!/usr/bin/env python3
"""Season-stamped, append-only vintage archive of the AAA-Statcast feature artifact.

Snapshots data/models/valucast_aaa_statcast_features.json to
data/aaa_statcast_archive/<YYYY-MM-DD>.json with vintage metadata (the source
artifact's generated_at, the archive row count, and a bat_tracking_coverage note).

WHY: a new-vintage forward gate (plan 030 / model-supremacy) needs a durable trail
of what the AAA-Statcast layer looked like on each date so a ~2030 gate can compare
against a fresh vintage. The archive never prunes: one snapshot per source date
(a same-date re-run with changed data overwrites that date's file, last-write-wins),
and a source date OLDER than the latest archived vintage is refused (back-dating
guard -- a stale/replayed upstream `as_of` must not corrupt the trail's ordering).

HASH-SKIP: the features artifact rewrites its `generated_at`/`as_of` envelope every
nightly build even when nothing measurable changed, so a naive per-day snapshot would
write 365 near-identical files a year. We hash only the SUBSTANTIVE payload (the
pitchers/hitters rollups + season + gates + counts, with the volatile envelope fields
excluded) and SKIP writing when that hash equals the most recent archived snapshot's
stored content_hash. Same content -> no new vintage file.

ponytail: stdlib only, ZERO network, deterministic. Mirrors the atomic-write posture
of scripts/archive_valucast_actuals_snapshot.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FEATURES_PATH = ROOT / "data" / "models" / "valucast_aaa_statcast_features.json"
ARCHIVE_DIR = ROOT / "data" / "aaa_statcast_archive"

# Envelope fields that churn every build without a real data change; excluded from the
# content hash so an identical measurement vintage never spawns a new archive file.
_VOLATILE_ENVELOPE_KEYS = ("generated_at", "as_of")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def content_hash(features: dict) -> str:
    """Deterministic sha256 over the substantive payload (volatile envelope removed).

    sort_keys + compact separators make the digest order-independent and stable across
    Python runs, so the same measurements always hash the same regardless of dict order
    or the generated_at/as_of stamp the source artifact rewrites nightly.
    """
    stripped = {k: v for k, v in features.items() if k not in _VOLATILE_ENVELOPE_KEYS}
    canonical = json.dumps(stripped, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _latest_snapshot_path(archive_dir: Path) -> Path | None:
    """The most recently dated archived snapshot path, or None if the archive is empty.

    Archive filenames are <YYYY-MM-DD>.json, so lexical max == chronological latest
    (the back-dating guard in archive_features keeps that invariant true).
    """
    snapshots = sorted(archive_dir.glob("*.json"))
    return snapshots[-1] if snapshots else None


def _row_count(features: dict) -> int:
    return len(features.get("pitchers") or {}) + len(features.get("hitters") or {})


def _bat_tracking_coverage_note(features: dict) -> str:
    """Human-readable vintage note.

    Bat-tracking (swing speed / attack angle) is NOT part of the AAA-Statcast feature
    rollup -- Savant does not publish bat-tracking at the minor-league level, so this
    vintage carries none. Recording that explicitly is the whole point of a vintage
    trail: a ~2030 reader must know coverage was contact-quality + pitch-shape only,
    not bat-tracking, when it compares vintages.
    """
    counts = features.get("counts") or {}
    return (
        "no bat-tracking (swing speed / attack angle) at AAA in this vintage; "
        f"coverage = pitch-shape + plate-outcome + contact-quality only "
        f"(pitchers={counts.get('pitchers', 0)}, hitters={counts.get('hitters', 0)})"
    )


def build_snapshot(features: dict, archived_at: str) -> dict:
    """Wrap the features artifact with vintage metadata for the archive."""
    return {
        "artifact": "valucast_aaa_statcast_features_vintage",
        "schema_version": 1,
        "archived_at": archived_at,
        # Source-artifact provenance: the generated_at IS the vintage stamp we care
        # about; season lets a reader bucket vintages by year without parsing dates.
        "source_generated_at": features.get("generated_at"),
        "source_as_of": features.get("as_of"),
        "season": features.get("season"),
        "row_count": _row_count(features),
        "bat_tracking_coverage": _bat_tracking_coverage_note(features),
        "content_hash": content_hash(features),
        "features": features,
    }


def archive_features(
    features: dict,
    date_str: str,
    *,
    archive_dir: Path = ARCHIVE_DIR,
    archived_at: str | None = None,
) -> tuple[Path, bool]:
    """Write today's vintage snapshot unless it duplicates the latest archived content.

    Returns (path, written). `written` is False when the content hash matches the most
    recent archived snapshot (no-op) OR when `date_str` is older than the latest
    archived vintage (back-dating guard) -- the returned path then points at that
    existing latest snapshot for the caller's log line.
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    new_hash = content_hash(features)

    latest_path = _latest_snapshot_path(archive_dir)
    if latest_path is not None:
        try:
            latest = _load_json(latest_path)
        except (OSError, ValueError):
            latest = None
        if latest is not None and latest.get("content_hash") == new_hash:
            return latest_path, False
        # Back-dating guard: hash-skip compares against the lexically-latest file,
        # so a regressed upstream `as_of` writing an older-dated file would corrupt
        # the "latest == lexical max" invariant. Refuse instead.
        if date_str < latest_path.stem:
            return latest_path, False

    snapshot = build_snapshot(features, archived_at or _now_iso())
    path = archive_dir / f"{date_str}.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def archive_current_features(
    features_path: Path = FEATURES_PATH,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict:
    if not features_path.exists():
        # No features artifact yet (cold-cache CI morning never produced one). Nothing
        # to archive; no-op so the daily build continues -- same fail-soft posture as
        # the guarded git-add in the workflow.
        return {"archive_path": None, "archive_written": False, "reason": "no features artifact"}
    features = _load_json(features_path)
    date_str = str(features.get("as_of") or date.today().isoformat())[:10]
    path, written = archive_features(features, date_str, archive_dir=archive_dir)
    return {
        "archive_path": str(path),
        "archive_written": written,
        "row_count": _row_count(features),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features-path", type=Path, default=FEATURES_PATH)
    parser.add_argument("--archive-dir", type=Path, default=ARCHIVE_DIR)
    args = parser.parse_args(argv)

    result = archive_current_features(args.features_path, args.archive_dir)
    if result.get("reason"):
        print(f"AAA statcast vintage: skipped ({result['reason']})", flush=True)
        return 0
    print(
        "AAA statcast vintage: "
        f"rows={result['row_count']} written={result['archive_written']} "
        f"-> {result['archive_path']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
