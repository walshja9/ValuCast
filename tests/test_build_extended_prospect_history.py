"""Offline contract tests for the extended-history command line builder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.build_extended_prospect_history as builder


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hitter(mlbam_id: int, *, year: int = 2014) -> dict:
    return {
        "cohort_year": year,
        "mlbam_id": mlbam_id,
        "name": f"Hitter {mlbam_id}",
        "role": "hitter",
        "level": "AA",
        "sport_id": 12,
        "age": 21,
        "plate_appearances": 300,
    }


def _pitcher(mlbam_id: int, *, year: int = 2014, innings=60.667) -> dict:
    return {
        "cohort_year": year,
        "mlbam_id": mlbam_id,
        "name": f"Pitcher {mlbam_id}",
        "role": "pitcher",
        "level": "AA",
        "sport_id": 12,
        "age": 21,
        # The committed raw dataset stores true decimal innings, while a direct
        # StatsAPI checkpoint uses baseball whole.outs notation such as "60.2".
        "innings_pitched": innings,
    }


def _statsapi_split(row: dict) -> dict:
    is_hitter = row["role"] == "hitter"
    stat = {
        "age": row.get("age"),
        "gamesPlayed": 80 if is_hitter else 15,
    }
    if is_hitter:
        stat.update(
            {
                "plateAppearances": row.get("plate_appearances", 300),
                "atBats": 270,
                "hits": 81,
                "homeRuns": 10,
                "strikeOuts": 60,
                "baseOnBalls": 30,
                "doubles": 15,
                "triples": 2,
                "stolenBases": 5,
                "rbi": 40,
                "runs": 50,
                "sacFlies": 3,
                "avg": ".300",
                "obp": ".370",
                "slg": ".481",
                "ops": ".851",
            }
        )
    else:
        innings = float(row.get("innings_pitched", 60.667))
        whole = int(innings)
        outs = round((innings - whole) * 3)
        stat.update(
            {
                "inningsPitched": f"{whole}.{outs}",
                "strikeOuts": 70,
                "baseOnBalls": 20,
                "battersFaced": 250,
                "gamesStarted": 12,
                "wins": 5,
                "losses": 3,
                "hits": 55,
                "homeRuns": 4,
                "earnedRuns": 21,
                "runs": 24,
                "era": "3.12",
                "whip": "1.24",
                "strikeoutsPer9Inn": "10.38",
                "walksPer9Inn": "2.97",
            }
        )
    return {
        "season": str(row["cohort_year"]),
        "player": {"id": row["mlbam_id"], "fullName": row["name"]},
        "team": {"name": "Test Club"},
        "sport": {"id": row.get("sport_id", 12)},
        "position": {"abbreviation": "SS" if is_hitter else "P"},
        "stat": stat,
    }


def _statsapi_response(rows: list[dict]) -> dict:
    return {
        "copyright": "fixture",
        "stats": [
            {
                "type": {"displayName": "season"},
                "group": {"displayName": role},
                "splits": [
                    _statsapi_split(row)
                    for row in rows
                    if row["role"] == ("hitter" if role == "hitting" else "pitcher")
                ],
            }
            for role in ("hitting", "pitching")
        ],
    }


def _contract(rows: list[dict]) -> dict:
    identities = [
        {"mlbam_id": row["mlbam_id"], "role": row["role"]} for row in rows
    ]
    return {
        "artifact": "valucast_extended_history_2014_identity_parity",
        "schema_version": 1,
        "cohort_year": 2014,
        "identity_count": len(identities),
        "source_policy": {
            "identity_fields_only": True,
            "outcomes_read": False,
            "mlb_seasons_read": False,
        },
        "rows": identities,
    }


def _draft_fact() -> dict:
    return {
        "draft_record_known": True,
        "rule4_drafted": False,
        "draft_year": None,
        "draft_pick_number": None,
        "draft_round": None,
        "signing_bonus": None,
        "pick_value": None,
        "school_type": None,
        "bats": "R",
        "throws": "R",
    }


def _prepare_args(
    tmp_path: Path, raw: Path, committed: Path
) -> tuple[list[str], Path, Path, Path]:
    output = tmp_path / "research" / "prepared.json"
    manifest = tmp_path / "research" / "source-manifest.json"
    draft_output = tmp_path / "research" / "draft-facts.json"
    input_rows = json.loads(raw.read_text(encoding="utf-8"))["rows"]
    raw_ids = {str(row["mlbam_id"]) for row in input_rows}
    checkpoint_dir = tmp_path / "research" / "checkpoints"
    response_dir = tmp_path / "research" / "milb-source-responses"
    years = sorted({int(row["cohort_year"]) for row in input_rows})
    for year in years:
        response_path = _write(
            response_dir / f"milb-{year}.json",
            _statsapi_response(
                [row for row in input_rows if int(row["cohort_year"]) == year]
            ),
        )
        replayed = builder.parse_milb_stats_response(
            json.loads(response_path.read_text(encoding="utf-8")), year=year
        )
        checkpoint = builder.build_milb_checkpoint(
            year=year,
            rows=replayed,
            response_path=response_path,
            response_sha256=_sha256(response_path),
            repository_root=tmp_path,
        )
        _write(checkpoint_dir / f"milb-{year}.json", checkpoint)
    draft_source = _write(
        tmp_path / "raw" / "draft-facts.json",
        {player_id: _draft_fact() for player_id in raw_ids},
    )
    return (
        [
            *[
                value
                for year in years
                for value in ("--cohort-year", str(year))
            ],
            "--parity-contract",
            str(committed),
            "--checkpoint-dir",
            str(checkpoint_dir),
            "--milb-response-dir",
            str(response_dir),
            "--draft-source",
            str(draft_source),
            "--draft-supplement",
            str(tmp_path / "research" / "draft-supplement.json"),
            "--draft-output",
            str(draft_output),
            "--repository-root",
            str(tmp_path),
            "--output",
            str(output),
            "--manifest",
            str(manifest),
        ],
        output,
        manifest,
        draft_output,
    )


def test_prepare_only_is_the_default_and_never_joins_outcomes(tmp_path):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    committed = _write(tmp_path / "production.json", _contract([_hitter(1)]))
    args, output, manifest_path, _ = _prepare_args(tmp_path, raw, committed)

    assert builder.main(args) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["artifact"] == "valucast_extended_prospect_history_prepared"
    assert payload["mode"] == "prepare_only"
    assert payload["source_policy"]["outcomes_read"] is False
    assert payload["identity_parity"]["status"] == "ready"
    assert "outcome" not in payload["rows"][0]
    assert manifest["mode"] == "prepare_only"
    assert not hasattr(builder, "build_labeled_rows")


def test_prepare_rejects_outcome_options_before_reading_them(tmp_path):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    committed = _write(tmp_path / "production.json", _contract([_hitter(1)]))
    args, output, _, _ = _prepare_args(tmp_path, raw, committed)
    missing_outcomes = tmp_path / "must-not-be-read.json"

    with pytest.raises(SystemExit):
        builder.main([*args, "--outcome-cache", str(missing_outcomes)])

    assert not output.exists()


def test_prepare_fails_closed_on_2014_identity_mismatch(tmp_path):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    committed = _write(tmp_path / "production.json", _contract([_hitter(2)]))
    args, output, manifest, _ = _prepare_args(tmp_path, raw, committed)

    with pytest.raises(ValueError, match="2014 identity parity"):
        builder.main(args)

    assert not output.exists()
    assert not manifest.exists()


@pytest.mark.parametrize(
    "contamination",
    [
        {"outcome": "star"},
        {"nested": {"outcome_label": "role"}},
        {"historical_mlb_seasons": {}},
        {"nested": {"mlb_seasons": {}}},
    ],
)
def test_prepare_rejects_any_outcome_or_mlb_season_content_in_parity_source(
    tmp_path, contamination
):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    parity = _contract([_hitter(1)]) | contamination
    committed = _write(tmp_path / "parity.json", parity)
    args, output, manifest, _ = _prepare_args(tmp_path, raw, committed)

    with pytest.raises(ValueError, match="identity-only parity"):
        builder.main(args)

    assert not output.exists()
    assert not manifest.exists()


def test_prepare_accepts_and_preserves_recorded_true_decimal_innings(tmp_path):
    raw = _write(tmp_path / "milb.json", {"rows": [_pitcher(7)]})
    committed = _write(tmp_path / "production.json", _contract([_pitcher(7)]))
    args, output, _, _ = _prepare_args(tmp_path, raw, committed)

    builder.main(args)

    row = json.loads(output.read_text(encoding="utf-8"))["rows"][0]
    assert row["innings_pitched"] == pytest.approx(60.667)


def test_registered_receipt_is_replayed_without_rewriting_source_files(
    tmp_path, monkeypatch
):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    committed = _write(tmp_path / "production.json", _contract([_hitter(1)]))
    args, output, manifest, draft_output = _prepare_args(tmp_path, raw, committed)
    checkpoint = tmp_path / "research" / "checkpoints" / "milb-2014.json"
    response = (
        tmp_path / "research" / "milb-source-responses" / "milb-2014.json"
    )
    source_bytes = (checkpoint.read_bytes(), response.read_bytes())
    replaced: list[Path] = []
    real_replace = builder.os.replace

    def replace_spy(source, target):
        replaced.append(Path(target))
        real_replace(source, target)

    monkeypatch.setattr(builder.os, "replace", replace_spy)
    builder.main(args)

    assert {output, manifest, draft_output} <= set(replaced)
    assert checkpoint not in replaced
    assert response not in replaced
    assert source_bytes == (checkpoint.read_bytes(), response.read_bytes())
    assert not list(tmp_path.rglob("*.tmp"))

    builder.main(args)
    assert json.loads(output.read_text(encoding="utf-8"))["candidate_count"] == 1
    assert source_bytes == (checkpoint.read_bytes(), response.read_bytes())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("endpoint", "https://example.invalid/stats"),
        ("query", {"season": 2014}),
        ("status", 201),
        ("response_sha256", "0" * 64),
    ],
)
def test_prepare_rejects_milb_receipt_contract_or_hash_drift(
    tmp_path, field, value
):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    committed = _write(tmp_path / "production.json", _contract([_hitter(1)]))
    args, output, manifest, _ = _prepare_args(tmp_path, raw, committed)
    checkpoint_path = tmp_path / "research" / "checkpoints" / "milb-2014.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["source_receipt"][field] = value
    _write(checkpoint_path, checkpoint)

    with pytest.raises(ValueError, match="receipt contract drift|response hash mismatch"):
        builder.main(args)

    assert not output.exists()
    assert not manifest.exists()


def test_prepare_rejects_minimal_or_fabricated_checkpoint(tmp_path):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    committed = _write(tmp_path / "production.json", _contract([_hitter(1)]))
    args, output, manifest, _ = _prepare_args(tmp_path, raw, committed)
    checkpoint_path = tmp_path / "research" / "checkpoints" / "milb-2014.json"
    _write(
        checkpoint_path,
        {
            "artifact": "valucast_extended_history_milb_checkpoint",
            "schema_version": 2,
            "cohort_year": 2014,
            "rows": [_hitter(1)],
        },
    )

    with pytest.raises(ValueError, match="checkpoint schema is invalid"):
        builder.main(args)

    assert not output.exists()
    assert not manifest.exists()


def test_prepare_rejects_checkpoint_parser_output_mismatch(tmp_path):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    committed = _write(tmp_path / "production.json", _contract([_hitter(1)]))
    args, output, manifest, _ = _prepare_args(tmp_path, raw, committed)
    checkpoint_path = tmp_path / "research" / "checkpoints" / "milb-2014.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["rows"][0]["plate_appearances"] += 1
    _write(checkpoint_path, checkpoint)

    with pytest.raises(ValueError, match="parser output mismatch"):
        builder.main(args)

    assert not output.exists()
    assert not manifest.exists()


def test_prepare_rejects_raw_response_byte_tampering(tmp_path):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    committed = _write(tmp_path / "production.json", _contract([_hitter(1)]))
    args, output, manifest, _ = _prepare_args(tmp_path, raw, committed)
    response_path = (
        tmp_path / "research" / "milb-source-responses" / "milb-2014.json"
    )
    response_path.write_bytes(response_path.read_bytes() + b" ")

    with pytest.raises(ValueError, match="source response hash mismatch"):
        builder.main(args)

    assert not output.exists()
    assert not manifest.exists()


def test_prepare_rejects_outcome_content_even_when_raw_hash_is_rebound(tmp_path):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    committed = _write(tmp_path / "production.json", _contract([_hitter(1)]))
    args, output, manifest, _ = _prepare_args(tmp_path, raw, committed)
    response_path = (
        tmp_path / "research" / "milb-source-responses" / "milb-2014.json"
    )
    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["outcome"] = "future MLB label"
    _write(response_path, response)
    checkpoint_path = tmp_path / "research" / "checkpoints" / "milb-2014.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["source_receipt"]["response_sha256"] = _sha256(response_path)
    _write(checkpoint_path, checkpoint)

    with pytest.raises(ValueError, match="outcome-bearing content"):
        builder.main(args)

    assert not output.exists()
    assert not manifest.exists()


def test_prepare_manifest_hashes_every_source_and_the_output(tmp_path):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    committed = _write(tmp_path / "production.json", _contract([_hitter(1)]))
    args, output, manifest_path, draft_output = _prepare_args(tmp_path, raw, committed)

    builder.main(["--prepare-only", *args])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = {(entry["kind"], entry["path"]): entry for entry in manifest["sources"]}
    checkpoint = tmp_path / "research" / "checkpoints" / "milb-2014.json"
    response = tmp_path / "research" / "milb-source-responses" / "milb-2014.json"
    assert sources[("milb_checkpoint", "research/checkpoints/milb-2014.json")][
        "sha256"
    ] == _sha256(checkpoint)
    assert sources[
        (
            "milb_statsapi_response",
            "research/milb-source-responses/milb-2014.json",
        )
    ]["sha256"] == _sha256(response)
    assert sources[("identity_parity_contract", "production.json")]["sha256"] == _sha256(
        committed
    )
    assert all(
        source["path"] != "data/prospects/prospect_model_inputs.json"
        for source in manifest["sources"]
    )
    assert manifest["output"]["path"] == "research/prepared.json"
    assert manifest["output"]["sha256"] == _sha256(output)
    assert manifest["draft_facts_output"]["path"] == "research/draft-facts.json"
    assert manifest["draft_facts_output"]["sha256"] == _sha256(draft_output)


def test_cli_has_no_sealed_look_or_outcome_cache_path(tmp_path):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    committed = _write(tmp_path / "production.json", _contract([_hitter(1)]))
    args, output, _, _ = _prepare_args(tmp_path, raw, committed)

    with pytest.raises(SystemExit):
        builder.main([*args, "--execute-sealed-look"])
    with pytest.raises(SystemExit):
        builder.main([*args, "--outcome-cache", str(tmp_path / "outcomes.json")])
    with pytest.raises(SystemExit):
        builder.main([*args, "--milb-input", str(raw)])
    assert not hasattr(builder, "execute_sealed_look")
    assert "milb_fetcher" not in builder.prepare_history.__annotations__
    assert not output.exists()


def test_prepare_refuses_to_overwrite_the_reference_contract(tmp_path):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(1)]})
    committed = _write(tmp_path / "production.json", _contract([_hitter(1)]))
    prepare_args, _, _, _ = _prepare_args(tmp_path, raw, committed)
    contract_before = committed.read_bytes()

    with pytest.raises(ValueError, match="protected contract"):
        builder.main([*prepare_args, "--output", str(committed)])

    assert committed.read_bytes() == contract_before


def test_prepare_outputs_are_byte_deterministic_and_draft_ids_are_exact(tmp_path):
    raw = _write(tmp_path / "milb.json", {"rows": [_hitter(2), _pitcher(1)]})
    committed = _write(
        tmp_path / "production.json", _contract([_hitter(2), _pitcher(1)])
    )
    args, output, manifest, draft_output = _prepare_args(tmp_path, raw, committed)
    builder.main(args)
    first = (output.read_bytes(), manifest.read_bytes(), draft_output.read_bytes())

    builder.main(args)

    assert first == (output.read_bytes(), manifest.read_bytes(), draft_output.read_bytes())
    draft = json.loads(draft_output.read_text(encoding="utf-8"))
    assert list(draft) == ["1", "2"]
    assert all(set(value) == set(builder.DRAFT_FACT_FIELDS) for value in draft.values())


def test_draft_supplement_must_exactly_cover_base_cache_gaps(tmp_path):
    candidates = [_hitter(1), _pitcher(2)]

    with pytest.raises(ValueError, match="exactly cover"):
        builder.build_candidate_draft_facts(
            candidates,
            {"1": _draft_fact()},
            {"3": _draft_fact()},
        )


def test_candidate_draft_facts_normalize_exact_schema_and_types():
    source = _draft_fact() | {
        "rule4_drafted": True,
        "draft_year": "2012",
        "draft_pick_number": 9,
        "draft_round": " 1 ",
        "signing_bonus": 125000,
        "pick_value": 140000,
        "school_type": "college",
    }

    facts = builder.build_candidate_draft_facts([_hitter(1)], {"1": source})

    assert set(facts) == {"1"}
    assert tuple(facts["1"]) == builder.DRAFT_FACT_FIELDS
    assert facts["1"]["draft_year"] == 2012
    assert type(facts["1"]["draft_year"]) is int
    assert facts["1"]["signing_bonus"] == 125000.0
    assert type(facts["1"]["signing_bonus"]) is float
    assert facts["1"]["draft_round"] == "1"


def test_undrafted_year_anomaly_is_normalized_to_null_without_changing_receipt():
    source = _draft_fact() | {"draft_year": 1979}

    facts = builder.build_candidate_draft_facts([_hitter(1)], {"1": source})

    assert facts["1"]["rule4_drafted"] is False
    assert facts["1"]["draft_year"] is None


def test_committed_564653_raw_anomaly_receipt_is_preserved_but_not_promoted():
    response_path = (
        builder.RESEARCH_DIR / "draft-source-responses" / "people-08.json"
    )
    response = json.loads(response_path.read_text(encoding="utf-8"))
    person = next(person for person in response["people"] if person["id"] == 564653)
    output = json.loads(builder.DEFAULT_DRAFT_OUTPUT.read_text(encoding="utf-8"))
    manifest = json.loads(
        builder.DEFAULT_PREPARE_MANIFEST.read_text(encoding="utf-8")
    )

    assert person["birthDate"] == "1990-04-01"
    assert person["draftYear"] == 1979
    assert _sha256(response_path) == (
        "7e21e97546f39bb09542a14489d1eb1bf06f964f352a00d0e6388dd5b930d448"
    )
    assert output["564653"]["rule4_drafted"] is False
    assert output["564653"]["draft_year"] is None
    receipt = next(
        source
        for source in manifest["sources"]
        if source["path"].endswith("draft-source-responses/people-08.json")
    )
    assert receipt["sha256"] == _sha256(response_path)


def test_committed_milb_receipts_replay_every_checkpoint_exactly():
    manifest = json.loads(
        builder.DEFAULT_PREPARE_MANIFEST.read_text(encoding="utf-8")
    )
    expected_checkpoints = [
        f"data/research/extended_prospect_history/checkpoints/milb-{year}.json"
        for year in builder.DEFAULT_COHORT_YEARS
    ]
    expected_responses = [
        f"data/research/extended_prospect_history/milb-source-responses/milb-{year}.json"
        for year in builder.DEFAULT_COHORT_YEARS
    ]
    assert [source["path"] for source in manifest["sources"][:26]] == [
        *expected_checkpoints,
        *expected_responses,
    ]

    for year in builder.DEFAULT_COHORT_YEARS:
        checkpoint_path = builder.DEFAULT_CHECKPOINT_DIR / f"milb-{year}.json"
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        replayed, response_path, receipt = builder._checkpoint_rows(
            checkpoint,
            year=year,
            source=checkpoint_path,
            response_dir=builder.DEFAULT_MILB_RESPONSE_DIR,
            repository_root=builder.ROOT,
        )
        assert checkpoint["schema_version"] == 2
        assert replayed == checkpoint["rows"]
        assert builder._json_bytes(replayed) == builder._json_bytes(checkpoint["rows"])
        assert checkpoint["rows_sha256"] == builder._rows_sha256(replayed)
        assert receipt["response_sha256"] == _sha256(response_path)


@pytest.mark.parametrize(
    "change",
    [
        {"draft_record_known": False},
        {"rule4_drafted": False, "draft_pick_number": 3},
        {"bats": "X"},
        {"pick_value": float("nan")},
        {"unexpected": "field"},
    ],
)
def test_candidate_draft_facts_fail_closed_on_inconsistent_source(change):
    source = _draft_fact() | change

    with pytest.raises(ValueError, match="draft fact 1"):
        builder.build_candidate_draft_facts([_hitter(1)], {"1": source})


def test_committed_draft_inputs_are_exactly_reproducible_from_bound_sources():
    prepared = json.loads(builder.DEFAULT_PREPARED_OUTPUT.read_text(encoding="utf-8"))

    facts, sources = builder._load_draft_inputs(
        candidates=prepared["rows"],
        draft_source=builder.DEFAULT_DRAFT_SOURCE,
        draft_supplement=builder.DEFAULT_DRAFT_SUPPLEMENT,
        repository_root=builder.ROOT,
    )

    candidate_ids = {str(row["mlbam_id"]) for row in prepared["rows"]}
    assert set(facts) == candidate_ids
    assert len(facts) == 10_397
    assert sum(fact["rule4_drafted"] for fact in facts.values()) == 7_327
    assert builder._json_bytes(facts) == builder.DEFAULT_DRAFT_OUTPUT.read_bytes()
    response_sources = [
        source
        for source in sources
        if source["kind"] == "draft_facts_statsapi_response"
    ]
    assert len(response_sources) == 21
    assert all(not Path(source["path"]).is_absolute() for source in sources)
