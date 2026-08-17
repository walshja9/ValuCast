import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import dev_pitcher_pass_stacking as stacking


ROOT = Path(__file__).resolve().parents[1]


def _run(script):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_committed_harnesses_emit_the_program_dev_receipts():
    phase_a = _run("dev_pitcher_pass_phase_a.py")
    assert "dev pitcher pooled n = 1887" in phase_a
    assert "spearman -0.0155  kendall -0.0218  auc -0.0104" in phase_a
    assert "spearman -0.0125  kendall -0.0194  auc -0.0081" in phase_a
    assert "spearman -0.0187  kendall -0.0245  auc -0.0127" in phase_a
    assert "feature width: outcome 35 effective/36 declared across n=3062; neighbors 8" in phase_a
    assert "served 134 wins; neighbors 66 wins; ties 0" in phase_a
    assert "served zero block: 390/1887 (20.67%); contributors 23" in phase_a
    assert "<=0.02 5/190 (2.63%); >=0.04 18/200 (9.00%); gradient 3.42x" in phase_a

    receipt = " ".join(_run("dev_pitcher_pass_stacking.py").split())
    assert "strike coverage: total 3449/3449; 2022 387/387" in receipt
    assert "base hurdle 0.133251 -> strike hurdle 0.131746" in receipt
    assert "base 50/50 0.140299 vs neighbors 0.148680" in receipt
    assert "base score alpha=0.5 d-sp +0.0221 d-kt +0.0093 d-auc +0.0178" in receipt
    assert "base rank alpha=0.5 d-sp +0.0151 d-kt +0.0035 d-auc +0.0127" in receipt
    assert "epsilon tie-break d-sp -0.0033 d-kt -0.0111 d-auc -0.0012" in receipt
    assert "band_blend d-sp +0.0250 d-kt +0.0120 d-auc +0.0197" in receipt


def test_strike_join_fails_closed(monkeypatch):
    row = stacking.load_rows(with_strike=False)[0]
    monkeypatch.delitem(stacking.BY_KEY, stacking._strike_key(row))

    with pytest.raises(ValueError, match="missing raw strike row"):
        stacking.load_rows(with_strike=True)
