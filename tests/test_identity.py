import unittest
from projections.data.identity import age_for, parse_people_payload


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
