from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.validate_projection_scorecard import (
    SCORECARD_PATH,
    validate_projection_scorecard,
)

ARTIFACT = json.loads(SCORECARD_PATH.read_text(encoding="utf-8"))


def _scorecard() -> dict:
    return copy.deepcopy(ARTIFACT)


def _write_and_validate(tmp_path: Path, payload: dict) -> list[str]:
    path = tmp_path / "methodology_scorecard.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded, problems = validate_projection_scorecard(path)
    assert loaded == payload
    return problems


def test_committed_artifact_validates(tmp_path: Path) -> None:
    problems = _write_and_validate(tmp_path, _scorecard())

    assert problems == []


def test_blocks_external_hitting_baseline(tmp_path: Path) -> None:
    payload = _scorecard()
    payload["hitting"]["baseline"] = "Steamer"

    problems = _write_and_validate(tmp_path, payload)

    assert any("hitting.baseline" in problem for problem in problems)


def test_blocks_external_claims_outside_not_shipped(tmp_path: Path) -> None:
    payload = _scorecard()
    payload["hitting"]["note"] = "beats Steamer"

    problems = _write_and_validate(tmp_path, payload)

    assert any("steamer" in problem.lower() for problem in problems)


def test_allows_external_tokens_inside_not_shipped(tmp_path: Path) -> None:
    payload = _scorecard()
    payload["not_shipped"].append({"name": "steamer benchmark", "verdict": "pending"})

    problems = _write_and_validate(tmp_path, payload)

    assert problems == []


def test_requires_generated_at(tmp_path: Path) -> None:
    payload = _scorecard()
    payload.pop("generated_at")

    problems = _write_and_validate(tmp_path, payload)

    assert any("generated_at" in problem for problem in problems)


def test_requires_hitting_sample_size(tmp_path: Path) -> None:
    payload = _scorecard()
    payload["hitting"].pop("sample_size")

    problems = _write_and_validate(tmp_path, payload)

    assert any("hitting.sample_size" in problem for problem in problems)
