"""Numeric trust-boundary tests; no model fitting or stored inputs."""
from copy import deepcopy
import unittest

from prospects import input_contract as contract_schema
from prospects import raw_input_builder as exporter
from prospects import universal


def _contract():
    return {
        "schema_version": "1.2", "generated_at": "2026-11-26T00:00:00+00:00",
        "source_policy": {
            "kind": "factual_only",
            "sources": sorted(contract_schema.SUPPORTED_SCHEMA_SOURCES["1.2"]),
            **{flag: False for flag in contract_schema.PROHIBITED_POLICY_FLAGS},
        },
        "historical": {"rows": [{"mlbam_id": 101, "role": "hitter", "level": "AAA", "age": 22, "cohort_year": 2018, "ops": 0.85}]},
        "current": {"hitters": [{"mlbam_id": 101, "role": "hitter", "level": "AAA", "age": 22, "plate_appearances": 200, "ops": 0.85}],
                    "pitchers": [{"mlbam_id": 202, "role": "pitcher", "level": "AA", "age": 22, "innings_pitched": 30, "era": 3.5, "is_starter": True}]},
        "historical_mlb_seasons": {"101_hitter": [{"year": 2019, "pa": 500, "ops": 0.85}], "202_pitcher": [{"year": 2019, "ip": 100, "era": 3.5}]},
        "mlb_service": [{"mlbam_id": 101, "role": "hitter", "pa": 0, "ab": 0, "graduated": False}, {"mlbam_id": 202, "role": "pitcher", "ip": 0, "graduated": False}],
    }


def _locations(payload):
    return [
        (payload["historical"]["rows"][0], "ops", "historical.rows[0].ops"),
        (payload["current"]["hitters"][0], "ops", "current.hitters[0].ops"),
        (payload["current"]["pitchers"][0], "era", "current.pitchers[0].era"),
        (payload["historical_mlb_seasons"]["101_hitter"][0], "ops", "historical_mlb_seasons.101_hitter[0].ops"),
        (payload["historical_mlb_seasons"]["202_pitcher"][0], "era", "historical_mlb_seasons.202_pitcher[0].era"),
        (payload["mlb_service"][0], "pa", "mlb_service[0].pa"),
    ]


def _produce(payload, draft_facts=None):
    return exporter.build_contract(
        dataset=payload["historical"], current=payload["current"], milb_history={},
        mlb_seasons=payload["historical_mlb_seasons"], draft_facts=draft_facts or {},
        fantrax_availability={}, generated_at=payload["generated_at"],
    )


class TestProspectNumericContract(unittest.TestCase):
    def test_factual_validator_rejects_supplied_invalid_measurements(self):
        for index in range(6):
            for value in (float("nan"), float("inf"), -float("inf"), "NaN", "1e309", "invalid", True, False, 10**1000):
                payload = _contract()
                row, field, path = _locations(payload)[index]
                row[field] = value
                with self.subTest(path=path, value_type=type(value).__name__):
                    problems = contract_schema.validate_factual_contract(payload)
                    self.assertTrue(any(path in problem for problem in problems), "supplied invalid measurement accepted")

    def test_universal_validator_preserves_supported_schemas_and_rejects_bad_measurements(self):
        for schema in ("1.0", "1.1", "1.2"):
            clean = _contract()
            clean["schema_version"] = schema
            clean["source_policy"]["sources"] = sorted(universal.INPUT_SCHEMA_SOURCES[schema])
            universal.validate_input_contract(clean)
            for index in range(6):
                payload = _contract()
                payload["schema_version"] = schema
                payload["source_policy"]["sources"] = sorted(universal.INPUT_SCHEMA_SOURCES[schema])
                row, field, path = _locations(payload)[index]
                row[field] = float("nan")
                with self.subTest(schema=schema, path=path), self.assertRaisesRegex(ValueError, path.replace("[", r"\[").replace("]", r"\]")):
                    universal.validate_input_contract(payload)

    def test_producer_rejects_bad_preserved_measurements_before_return(self):
        for index in range(5):
            payload = _contract()
            row, field, path = _locations(payload)[index]
            row[field] = float("nan")
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "finite|numeric"):
                _produce(payload)

    def test_valid_zero_missing_numeric_strings_and_boolean_flags_are_unchanged(self):
        for value in (None, 0, 0.0, "0", -0.5, "0.85"):
            payload = _contract()
            for row, field, _ in _locations(payload):
                row[field] = value
            payload["current"]["hitters"][0].update(name="NaN", notes="inf", source_artifact="milb_season_stats")
            before = deepcopy(payload)
            self.assertEqual(contract_schema.validate_factual_contract(payload), [])
            universal.validate_input_contract(payload)
            self.assertEqual(payload, before)
            produced = _produce(payload)
            self.assertEqual(produced["historical"]["rows"][0]["ops"], value)
            self.assertEqual(produced["current"]["hitters"][0]["ops"], value)
        payload = _contract()
        before = deepcopy(payload)
        self.assertEqual(_produce(payload)["current"]["pitchers"][0]["is_starter"], True)
        self.assertEqual(payload, before)

    def test_optional_draft_text_is_preserved_but_nonfinite_draft_numbers_are_rejected(self):
        for field in ("draft_round", "draft_pick_number", "signing_bonus", "pick_value"):
            for value in ("CBA", "$1,000,000", "1,000,000", None, 0, "0", "12.5"):
                payload = _contract()
                payload["current"]["pitchers"][0][field] = value
                self.assertEqual(contract_schema.validate_factual_contract(payload), [])
                universal.validate_input_contract(payload)
                produced = _produce(payload, {"202": {field: value}})
                self.assertEqual(produced["current"]["pitchers"][0][field], value)
            for value in (float("nan"), float("inf"), "NaN", "inf", "1e309", True, False, 10**1000):
                payload = _contract()
                payload["current"]["pitchers"][0][field] = value
                with self.subTest(field=field, value_type=type(value).__name__):
                    self.assertTrue(contract_schema.validate_factual_contract(payload))
                    with self.assertRaises(ValueError):
                        universal.validate_input_contract(payload)
                    with self.assertRaises(ValueError):
                        _produce(payload, {"202": {field: value}})

    def test_measurement_classification_covers_producer_declarations(self):
        declared = set(exporter._HISTORICAL_FIELDS) | set(exporter._DRAFT_FIELDS)
        declared.update(field for fields in exporter._CURRENT_FIELDS.values() for field in fields)
        declared.update(field for fields in exporter._MLB_SEASON_FIELDS.values() for field in fields)
        metadata = {"cohort_year", "mlbam_id", "name", "normalized_name", "role", "level", "position", "is_starter", "outcome", "draft_record_known", "rule4_drafted", "draft_year", "school_type", "bats", "throws", "team", "sport_id", "sample_season", "sample_fetched_date", "sample_staleness_years", "source_artifact", "source_kind", "roster_status", "availability_status", "availability_source", "availability_note", "availability_fetched_date", "year"}
        numeric = getattr(contract_schema, "NUMERIC_MEASUREMENT_FIELDS", frozenset())
        self.assertFalse(declared - metadata - set(numeric), "new producer field requires numeric/metadata classification")
        self.assertTrue({"games", "hr", "sb", "pa", "ab", "ip"} <= set(numeric))
        self.assertFalse(metadata & set(numeric), "metadata and boolean flags must retain their existing semantics")
