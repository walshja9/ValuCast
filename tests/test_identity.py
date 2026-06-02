import tempfile
import unittest
from pathlib import Path
from unittest import mock

from projections.data import identity as identity_mod
from projections.data.identity import (
    age_for, parse_people_payload, build_identity_store, load_identity_store,
)


class TestIdentity(unittest.TestCase):
    def test_age_as_of_april_first(self):
        # Born 1995-06-01 -> as of 2026-04-01 has NOT had 2026 birthday: age 30.
        self.assertEqual(age_for("1995-06-01", 2026), 30)
        # Born 1995-03-01 -> already had birthday by Apr 1: age 31.
        self.assertEqual(age_for("1995-03-01", 2026), 31)

    def test_missing_birthdate_returns_none(self):
        self.assertIsNone(age_for("", 2026))
        self.assertIsNone(age_for(None, 2026))

    def test_parse_people_payload(self):
        payload = {"people": [
            {"id": 660271, "fullName": "X", "birthDate": "1994-07-05",
             "batSide": {"code": "L"}, "pitchHand": {"code": "R"}},
        ]}
        out = parse_people_payload(payload)
        self.assertEqual(out["660271"]["birth_date"], "1994-07-05")
        self.assertEqual(out["660271"]["bats"], "L")

    def test_build_then_load_identity_store(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            fake = {"5": {"mlbam_id": "5", "name": "Bat", "birth_date": "1995-01-01"}}
            with mock.patch.object(identity_mod, "fetch_identities", return_value=fake):
                built = build_identity_store(["5", "5"], data_dir)  # dedups
            self.assertEqual(built, fake)
            self.assertEqual(load_identity_store(data_dir), fake)

    def test_load_identity_store_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_identity_store(Path(d)), {})
