import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app

ROOT = Path(__file__).parent.parent
ART = ROOT / "data" / "validation" / "methodology_scorecard.json"


class TestMethodologyValidation(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.art = json.loads(ART.read_text(encoding="utf-8"))
        self.html = self.client.get("/methodology").data.decode("utf-8")

    # E2/E6: page renders the artifact's numbers verbatim (page <-> artifact drift-lock)
    def test_renders_artifact_aggregate_numbers(self):
        self.assertEqual(self.client.get("/methodology").status_code, 200)
        self.assertIn(str(self.art["pitching"]["aggregate_mae_ratio"]), self.html)
        self.assertIn(str(self.art["hitting"]["aggregate_mae_ratio"]), self.html)
        self.assertIn(str(self.art["pitching"]["sample_size"]), self.html)
        self.assertIn(str(self.art["hitting"]["sample_size"]), self.html)

    # E3: layout + progressive disclosure
    def test_layout_and_disclosure(self):
        self.assertIn("Back to rankings", self.html)
        self.assertIn("At a glance", self.html)
        self.assertIn("<details", self.html)
        self.assertIn("Under the hood", self.html)
        self.assertIn("Model equations", self.html)
        self.assertIn("Validation details", self.html)

    # E3/E6: equations render the real params (page <-> params drift-lock)
    def test_equations_locked_to_params(self):
        from projections.models.marcel_params import MarcelParams
        from projections.models.pitcher_params import PitcherMarcelParams
        weights = ",".join(str(w) for w in MarcelParams().season_weights)
        self.assertIn(weights, self.html.replace(" ", ""))
        self.assertIn(str(int(PitcherMarcelParams().n_reg)), self.html)

    # E4: per-stat caveats from the artifact
    def test_per_stat_caveats(self):
        self.assertIn("neutral", self.html.lower())
        self.assertIn("AVG/OBP/SLG/OPS", self.html)
        self.assertIn("not shipped", self.html.lower())

    # E5: honesty reframe — Steamer is a comparison board, benchmark pending
    def test_honesty_reframe(self):
        low = self.html.lower().replace("’", "'")
        self.assertIn("not yet proven", low)
        self.assertIn("benchmark pending", low)
        self.assertNotIn("external benchmark", low)

    # public page must not leak the internal own-xBA correlation figure
    def test_no_internal_corr_leak(self):
        self.assertNotIn("0.87", self.html)


class TestReframeRipples(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_caption_reframed(self):
        html = self.client.get("/rankings?source=valucast").data.decode("utf-8")
        self.assertIn("comparison board", html.lower())
        self.assertNotIn("external benchmark", html.lower())

    def test_footer_reframed(self):
        html = self.client.get("/?source=valucast").data.decode("utf-8")
        self.assertNotIn("external benchmark", html.lower())


if __name__ == "__main__":
    unittest.main()
