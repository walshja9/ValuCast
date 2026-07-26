"""Validate the hand-authored ValuCast glossary and its provenance."""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GLOSSARY = ROOT / "data" / "manual" / "valucast_glossary.json"
REQUIRED_TERM_FIELDS = ("id", "term", "definition", "origin")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
THIRD_PARTY_RANK = re.compile(
    r"\b(?:fangraphs|cfr|hkb|pipeline|baseball america|the board)"
    r"\s*(?:rank(?:ed)?|#)\s*#?\d+",
    re.IGNORECASE,
)


def _load(path: Path) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [f"glossary did not parse: {exc}"]
    return (
        payload if isinstance(payload, dict) else None,
        [] if isinstance(payload, dict) else ["glossary must be a JSON object"],
    )


def validate(path: Path = GLOSSARY) -> list[str]:
    payload, problems = _load(Path(path))
    if payload is None:
        return problems

    if payload.get("schema_version") != "1.0":
        problems.append("schema_version must be 1.0")
    try:
        date.fromisoformat(payload["generated_at"])
    except (KeyError, TypeError, ValueError):
        problems.append("generated_at must be an ISO date")
    if not payload.get("principle"):
        problems.append("principle is required")
    changelog = payload.get("changelog")
    if not isinstance(changelog, list):
        problems.append("changelog must be a list")
    else:
        for index, change in enumerate(changelog):
            if not isinstance(change, dict):
                problems.append(f"changelog {index}: must be an object")
                continue
            for field in ("date", "title", "detail"):
                if not isinstance(change.get(field), str) or not change[field].strip():
                    problems.append(f"changelog {index}: {field} is required")
            try:
                date.fromisoformat(change.get("date", ""))
            except (TypeError, ValueError):
                problems.append(f"changelog {index}: date must be ISO date")
    terms = payload.get("terms")
    if not isinstance(terms, list) or not terms:
        return problems + ["terms must be a non-empty list"]
    if not 20 <= len(terms) <= 40:
        problems.append("glossary must contain 20-40 terms")

    ids: list[str] = []
    for index, term in enumerate(terms):
        if not isinstance(term, dict):
            problems.append(f"term {index}: must be an object")
            continue
        tid = term.get("id")
        for field in REQUIRED_TERM_FIELDS:
            if not isinstance(term.get(field), str) or not term[field].strip():
                problems.append(f"term {tid or index}: {field} is required")
        origin = term.get("origin")
        if isinstance(origin, str) and not (
            origin == "original to ValuCast" or origin.startswith("adopted from ")
        ):
            problems.append(
                f"term {tid or index}: origin must be original to ValuCast or adopted from ..."
            )
        if isinstance(tid, str):
            ids.append(tid)
            if not SLUG.fullmatch(tid):
                problems.append(f"term {tid}: id must be a lowercase slug")
        aliases = term.get("aliases", [])
        if not isinstance(aliases, list) or not all(
            isinstance(alias, str) and alias.strip() for alias in aliases
        ):
            problems.append(f"term {tid or index}: aliases must be non-empty strings")

        example = term.get("example")
        if example is not None:
            if not isinstance(example, dict):
                problems.append(f"term {tid or index}: example must be an object")
            else:
                for field in ("text", "source", "as_of"):
                    if not isinstance(example.get(field), str) or not example[field].strip():
                        problems.append(f"term {tid or index}: example.{field} is required")
                source = example.get("source")
                if isinstance(source, str) and source:
                    source_path = (ROOT / source).resolve()
                    data_root = (ROOT / "data").resolve()
                    if not source_path.is_relative_to(data_root) or not source_path.is_file():
                        problems.append(
                            f"term {tid or index}: example source does not exist under data/"
                        )
                as_of = example.get("as_of")
                if isinstance(as_of, str) and as_of:
                    try:
                        date.fromisoformat(as_of)
                    except ValueError:
                        problems.append(f"term {tid or index}: example.as_of must be ISO date")

    id_set = set(ids)
    if len(id_set) != len(ids):
        problems.append("term ids must be unique")
    for term in terms:
        if not isinstance(term, dict):
            continue
        for target in term.get("see_also", []):
            if target not in id_set:
                problems.append(f"term {term.get('id', '?')}: dangling see_also {target!r}")
    for label, target in (payload.get("label_map") or {}).items():
        if not isinstance(label, str) or target not in id_set:
            problems.append(f"label_map {label!r}: target {target!r} does not resolve")

    if THIRD_PARTY_RANK.search(json.dumps(payload, ensure_ascii=False)):
        problems.append("glossary contains a named third-party rank")
    return problems


def main() -> int:
    problems = validate()
    if problems:
        print("GLOSSARY INVALID:\n  " + "\n  ".join(problems))
        return 1
    count = len(json.loads(GLOSSARY.read_text(encoding="utf-8"))["terms"])
    print(f"OK: glossary {count} terms, traceable examples, no named-board ranks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
