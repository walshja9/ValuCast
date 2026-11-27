"""Fail hard when a core public metric label has no glossary definition."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from web.category_registry import HITTING_CATEGORIES, PITCHING_CATEGORIES  # noqa: E402
from web.pitch_discipline_store import _DEFAULT_LABELS  # noqa: E402
from web.prospect_percentiles import METRIC_LABELS  # noqa: E402


GLOSSARY = ROOT / "data" / "manual" / "valucast_glossary.json"
COVERAGE_SCOPE = (
    "player-card headline, skill, and plate-discipline metrics",
    "trade decision and league-context labels",
    "dynasty/prospect board decision columns",
)
MAJOR_SURFACE_LABELS = {
    "$",
    "Ahead of the Curve",
    "Category Fit",
    "Competitive window",
    "Confidence",
    "Dynasty #",
    "Dynasty Value",
    "ETA",
    "League context",
    "Margin",
    "Now $",
    "Opportunity",
    "P#",
    "Prospect slots",
    "Public Consensus",
    "Roster spots",
    "Scoring",
    "Skill",
    "Teams",
    "Trade verdict",
    "ValuCast Rank",
    "ValuCast Value",
    "Value band",
    "Your League #",
}
EXEMPTIONS = {
    "Age": "identity field, not a metric",
    "Player": "identity column, not a metric",
    "Pos": "position field, not a metric",
    "Team": "organization field, not a metric",
}


def _all_labels() -> set[str]:
    categories = {
        category.label for category in HITTING_CATEGORIES + PITCHING_CATEGORIES
    }
    return (
        set(METRIC_LABELS.values())
        | set(_DEFAULT_LABELS.values())
        | categories
        | MAJOR_SURFACE_LABELS
    )


def unresolved_labels(
    glossary_path: Path = GLOSSARY, *, labels: set[str] | None = None
) -> list[str]:
    registry = json.loads(Path(glossary_path).read_text(encoding="utf-8"))
    resolved = set((registry.get("label_map") or {}).keys())
    for term in registry.get("terms") or []:
        resolved.add(term["term"])
        resolved.update(term.get("aliases") or [])
    checked = _all_labels() if labels is None else set(labels)
    return sorted(checked - resolved - set(EXEMPTIONS))


def main() -> int:
    try:
        unresolved = unresolved_labels()
    except (OSError, ValueError, KeyError) as exc:
        print(f"LABEL COVERAGE FAILED: {exc}")
        return 1
    if unresolved:
        print(
            "LABEL COVERAGE FAILED — no glossary term for:\n  "
            + "\n  ".join(unresolved)
        )
        return 1
    print(f"OK: {_all_labels().__len__()} labels resolve across {COVERAGE_SCOPE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
