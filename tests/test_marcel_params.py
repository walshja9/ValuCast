import unittest
from projections.models.marcel_params import MarcelParams


class TestMarcelParams(unittest.TestCase):
    def test_defaults_match_classic_marcel(self):
        p = MarcelParams()
        self.assertEqual(p.season_weights, (5.0, 4.0, 3.0))
        self.assertEqual(p.n_reg, 1200.0)
        self.assertAlmostEqual(p.k_young, 0.006)
        self.assertAlmostEqual(p.k_old, 0.003)
        self.assertEqual((p.pa_w1, p.pa_w2, p.pa_base), (0.5, 0.1, 200.0))

    def test_is_frozen(self):
        p = MarcelParams()
        with self.assertRaises(Exception):
            p.n_reg = 5.0  # type: ignore

    def test_gamma_defaults_to_zero_classic(self):
        p = MarcelParams()
        self.assertEqual(p.gamma, 0.0)        # gamma=0 == classic Marcel
        self.assertEqual(p.n_reg, 1200.0)     # n_reg is the base level, unchanged

    def test_gamma_is_settable_via_constructor(self):
        p = MarcelParams(gamma=0.5)
        self.assertEqual(p.gamma, 0.5)

    def test_alpha_knobs_default_to_zero(self):
        p = MarcelParams()
        self.assertEqual(p.alpha_contact, 0.0)   # 0 = no de-noising = classic
        self.assertEqual(p.alpha_power, 0.0)

    def test_alpha_knobs_settable(self):
        p = MarcelParams(alpha_contact=0.4, alpha_power=0.6)
        self.assertEqual((p.alpha_contact, p.alpha_power), (0.4, 0.6))
