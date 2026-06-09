#!/usr/bin/env python3
"""Post-deploy smoke check.

Usage: python scripts/smoke_check.py <base_url> [expected_commit_sha]

Asserts the live site serves the Dynasty + Prospects tabs, that /health/ready
reports all stores available, and (optionally) that the deployed revision matches
the expected HEAD. Exits non-zero on any failure.
"""
import json
import sys
import urllib.request


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "valucast-smoke"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: smoke_check.py <base_url> [expected_commit_sha]", file=sys.stderr)
        return 2
    base = sys.argv[1].rstrip("/")
    expected = sys.argv[2] if len(sys.argv) > 2 else None
    problems: list[str] = []

    try:
        _, home = _get(base + "/")
        if 'value="dd_dynasty"' not in home:
            problems.append("Dynasty tab missing from nav")
        if 'value="prospects"' not in home:
            problems.append("Prospects tab missing from nav")
        if "Dynasty data is not available" in home:
            problems.append("home shows DD-unavailable fallback notice")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"GET / failed: {exc}")

    try:
        status, body = _get(base + "/health/ready")
        data = json.loads(body)
        if status != 200 or not data.get("ready"):
            problems.append(f"/health/ready not ready (status {status}): {data}")
        if expected and data.get("commit"):
            if not data["commit"].startswith(expected[:7]):
                problems.append(
                    f"deployed commit {data['commit']} != expected {expected[:7]}"
                )
    except Exception as exc:  # noqa: BLE001
        problems.append(f"GET /health/ready failed: {exc}")

    if problems:
        print("SMOKE CHECK FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"Smoke check OK against {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
