#!/usr/bin/env python3
"""Atomically sync the public Diamond Dynasties feed into ValuCast."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from web.feed_validation import validate_dd_feed  # noqa: E402

DEFAULT_URL = (
    "https://diamonddynastiesleagueanalyzer.onrender.com/api/valucast-feed"
)
DEFAULT_OUTPUT = ROOT / "data" / "dd" / "dd_dynasty_feed.json"
TIMEOUT_SECONDS = 60


def fetch_feed(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ValuCast daily public-data refresh"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def sync_feed(url: str = DEFAULT_URL, output: Path = DEFAULT_OUTPUT) -> dict:
    body = fetch_feed(url)
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("DD feed response must be a JSON object")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )
        problems = validate_dd_feed(tmp)
        if problems:
            raise ValueError("invalid DD feed: " + "; ".join(problems))
        os.replace(tmp, output)
    finally:
        tmp.unlink(missing_ok=True)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = sync_feed(args.url, args.output)
    print(
        f"Synced DD feed: generated_at={payload.get('generated_at')} "
        f"players={len(payload.get('players', []))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
