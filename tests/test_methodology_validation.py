import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertIn("Back to board", self.html)
        self.assertIn("At a glance", self.html)
        self.assertIn("Prospect Rank v1", self.html)
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
        self.assertIn("available as an opt-in", low)
        self.assertIn("will not become the default", low)
        self.assertNotIn("external benchmark", low)

    # public page must not leak the internal own-xBA correlation figure
    def test_no_internal_corr_leak(self):
        self.assertNotIn("0.87", self.html)

    # 014: methodology honesty polish — win-rate interpreted, MAE headlines banded
    # with sample size + a noise caveat, and the live Steamer forward loss surfaced.
    def test_honesty_polish_present(self):
        flat = " ".join(self.html.split())
        low = flat.lower()
        # gap (a): win-rate interpreted, not flat
        self.assertIn("even on ranking", flat)
        self.assertIn("re-ordering players", flat)
        # gap (b): sample size on the aggregate ledger rows + 2020 noise caveat
        self.assertIn(str(self.art["hitting"]["sample_size"]), self.html)
        self.assertIn(str(self.art["pitching"]["sample_size"]), self.html)
        self.assertIn("2020", flat)
        self.assertIn("directional, not precise", flat)
        # gap (c): the committed legacy artifact used cumulative rates, so its
        # magnitude cannot be presented as a valid post-freeze score.
        self.assertIn("stored forward rate readout is excluded", low)
        self.assertIn("not a valid post-freeze score", low)
        self.assertIn("steamer remains the live source", low)
        self.assertNotIn("currently losing", low)

    def test_corrected_forward_readout_separates_hitters_and_pitchers(self):
        corrected = {
            "comparison_basis": {
                "rate_actuals_method": "post_freeze_component_deltas",
                "horizon_days": 30,
            },
            "role_scores": {
                "hitters": {"marcel_mean_ratio_vs_steamer": 1.03},
                "pitchers": {"marcel_mean_ratio_vs_steamer": 1.10},
            },
            "role_gates": {
                "hitters": {"status": "fallback"},
                "pitchers": {"status": "fallback"},
            },
            "publication_veto": {"status": "held"},
            "gate": {"validated_through": "2026-07-18"},
        }
        original_read_text = Path.read_text

        def read_text(path, *args, **kwargs):
            if path.name == "valucast_mlb_projection_source_comparison.json":
                return json.dumps(corrected)
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", read_text):
            html = " ".join(self.client.get("/methodology").data.decode("utf-8").split())

        self.assertIn("Hitter rate error: <strong>1.03x Steamer", html)
        self.assertIn("Pitcher rate error: <strong>1.1x Steamer", html)
        self.assertIn("both roles must clear independently", html)
        self.assertIn("Publication remains held", html)

    def test_prospect_rank_v1_explains_scoring_boundary(self):
        flat = " ".join(self.html.split())
        self.assertIn("Top prospects are generated", flat)
        self.assertIn("eligible prospect universe", flat)
        self.assertIn("universal prospect board", flat)
        self.assertIn("current performance", flat)
        self.assertIn("age/level context", flat)
        self.assertIn("draft/signing investment", flat)
        self.assertIn("availability/sample risk", flat)
        self.assertIn("historical outcome", flat)
        self.assertIn("not by name", flat)
        self.assertIn("Category Fit", flat)
        self.assertIn("does not generate the public", flat)
        self.assertIn("outside dynasty rankings", self.html)
        self.assertIn("outside values", self.html)
        self.assertIn("public prospect rankings", self.html)
        self.assertIn("comparison context only", self.html)
        self.assertIn("applied by rule, not by name", self.html)

    # P1 repair: the worked example is COMPUTED from the real params (drift-proof),
    # using the implementation's weighted-opportunity denominator + PA projection.
    def test_worked_example_matches_params(self):
        from projections.models.marcel_params import MarcelParams
        p = MarcelParams()
        ex = [(30, 600), (26, 580), (20, 520)]
        w = p.season_weights
        w_ev = sum(wi * e for wi, (e, _) in zip(w, ex))     # weighted events
        w_pa = sum(wi * pa for wi, (_, pa) in zip(w, ex))   # weighted OPPORTUNITIES
        reg = (w_ev + 0.033 * p.n_reg) / (w_pa + p.n_reg)
        proj_pa = p.pa_w1 * ex[0][1] + p.pa_w2 * ex[1][1] + p.pa_base
        proj_hr = round(reg * proj_pa, 1)
        self.assertIn(str(int(w_pa)), self.html)            # 6880, the real denominator
        self.assertIn(str(int(round(proj_pa))), self.html)  # 558 projected PA
        self.assertIn(str(proj_hr), self.html)              # ~24.4, not 22
        self.assertNotIn("22 projected HR", self.html)      # the old wrong number is gone

    # 7/7 (revised): the sensitivity section is now rendered from a committed,
    # reproducible artifact (data/validation/sensitivity_scorecard.json, built by
    # scripts/build_sensitivity_scorecard.py), NOT hardcoded prose. This test
    # drift-locks the page to that artifact the same way test_renders_artifact_*
    # locks the held-out scorecard: every published movement number must match a
    # number the script actually produced against the real board.
    def test_sensitivity_section_drift_locks_to_the_committed_artifact(self):
        sens = json.loads(
            (ROOT / "data" / "validation" / "sensitivity_scorecard.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn('id="sensitivity"', self.html)
        # board size rendered from the artifact (comma-formatted, as the page shows it)
        self.assertIn("{:,}".format(sens["board_size"]), self.html)
        self.assertTrue(sens["levers"], "artifact must carry at least one lever")
        for lever in sens["levers"]:
            self.assertIn(lever["label"], self.html)
            for variant in lever["variants"]:
                # the load-bearing measured numbers must appear verbatim on the page
                self.assertIn("{:,}".format(variant["moved_25plus"]), self.html)
                self.assertIn("{:,}".format(variant["moved_10plus"]), self.html)
        # reproducibility pointer -- the public claim "not a simulation" is only
        # honest if the reader knows it is regenerated, not hand-typed. The
        # provenance is stated in plain language now (no visitor-facing script path).
        self.assertIn("regenerates nightly from the public data pipeline", self.html)
        self.assertNotIn("build_sensitivity_scorecard.py", self.html)
        # dated, and must still decline to claim any setting predicts outcomes better
        self.assertIn(sens["generated_at"][:10], self.html)
        self.assertIn("does <strong>not</strong> tell you", self.html)


class TestBuilderGuard(unittest.TestCase):
    def test_requires_full_pitching_history(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "bvs", ROOT / "scripts" / "build_validation_scorecard.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.PIT_HISTORY, list(range(2010, 2026)))  # 2010..2025, role factors


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
