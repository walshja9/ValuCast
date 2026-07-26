from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GLOSSARY = ROOT / "data" / "manual" / "valucast_glossary.json"


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    assert path.exists(), f"{path} is missing"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _registry(**term_overrides):
    term = {
        "id": "sample-rate",
        "term": "Sample Rate",
        "definition": "A test definition.",
        "origin": "original to ValuCast",
        "see_also": [],
    }
    term.update(term_overrides)
    return {
        "schema_version": "1.0",
        "generated_at": "2026-07-26",
        "principle": "Missing data stays missing; estimates are labeled.",
        "changelog": [],
        "terms": [term],
    }


def test_committed_glossary_passes_schema_and_label_coverage():
    schema = _load_script("validate_glossary")
    coverage = _load_script("validate_label_glossary_coverage")

    assert schema.validate(GLOSSARY) == []
    assert coverage.unresolved_labels(GLOSSARY) == []


def test_schema_validator_rejects_malformed_or_untraceable_terms(tmp_path):
    schema = _load_script("validate_glossary")
    cases = [
        (_registry(id=None), "id"),
        (_registry(see_also=["missing-term"]), "see_also"),
        (
            _registry(
                example={
                    "text": "Untraceable.",
                    "source": "data/models/does-not-exist.json",
                }
            ),
            "as_of",
        ),
        (_registry(definition="FanGraphs #12"), "third-party rank"),
    ]

    for index, (payload, expected) in enumerate(cases):
        path = tmp_path / f"case-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert any(expected in problem for problem in schema.validate(path))


def test_schema_validator_enforces_registry_contract(tmp_path):
    schema = _load_script("validate_glossary")
    payload = _registry()
    payload.pop("schema_version")
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    problems = schema.validate(path)
    assert any("schema_version" in problem for problem in problems)
    assert any("20-40 terms" in problem for problem in problems)


def test_coverage_gate_fails_hard_and_honors_visible_exemptions(tmp_path):
    coverage = _load_script("validate_label_glossary_coverage")
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(_registry()), encoding="utf-8")

    assert coverage.unresolved_labels(path, labels={"Mystery Metric"}) == [
        "Mystery Metric"
    ]
    assert coverage.unresolved_labels(path, labels={"Player"}) == []
    assert "warn" not in coverage.main.__code__.co_varnames


def test_glossary_route_is_fail_soft_and_cross_linked(monkeypatch):
    import app as app_module

    client = app_module.app.test_client()
    response = client.get("/glossary")
    body = response.data.decode()
    assert response.status_code == 200
    assert "ValuCast Glossary" in body
    assert "Missing data stays missing" in body
    assert 'href="/models"' in body
    assert 'href="/methodology"' in body

    monkeypatch.setattr(
        app_module, "GLOSSARY_PATH", ROOT / "data" / "manual" / "__missing__.json"
    )
    response = client.get("/glossary")
    assert response.status_code == 200
    assert "Glossary unavailable" in response.data.decode()


def test_methodology_footer_and_player_help_links_resolve():
    import app as app_module

    client = app_module.app.test_client()
    methodology = client.get("/methodology").data.decode()
    assert "methodology-principle" in methodology
    assert "2026-07-10" in methodology
    assert "max_tokens" not in methodology
    assert 'href="/glossary"' in methodology
    assert b'href="/glossary"' in client.get("/ledger").data

    player = client.get(
        "/player/vc_prospect_806956_hitter?mode=prospects",
        follow_redirects=True,
    ).data.decode()
    anchors = set(re.findall(r'href="/glossary#([a-z0-9-]+)"', player))
    terms = {
        term["id"]
        for term in json.loads(GLOSSARY.read_text(encoding="utf-8"))["terms"]
    }
    assert anchors
    assert anchors <= terms


def test_glossary_validators_are_daily_build_gates():
    from scripts import run_daily_public_build

    commands = {" ".join(step) for step in run_daily_public_build.VALIDATE_STEPS}
    assert "scripts/validate_glossary.py" in commands
    assert "scripts/validate_label_glossary_coverage.py" in commands
