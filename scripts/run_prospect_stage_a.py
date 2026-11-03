"""Local, aggregate-only entry point for the Stage A research checks."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import warnings

# Synthetic runs must not leave import caches in the checkout.
sys.dont_write_bytecode = True

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        from projections.backtest import prospect_stage_a as stage_a
    except Exception:
        stage_a = None


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "projections/backtest/stage_a_freeze.json"
MANIFEST_RELATIVE_PATH = "projections/backtest/stage_a_freeze.json"
HASHED_FILES = (
    "projections/backtest/prospect_stage_a.py",
    "scripts/run_prospect_stage_a.py",
    "tests/test_prospect_stage_a.py",
    "projections/backtest/stage_a_plan.md",
    "prospects/model.py",
    "prospects/impact_oof.py",
    "prospects/gate.py",
    "prospects/input_contract.py",
    "prospects/raw_input_builder.py",
    "prospects/stage1_outcome_proof.py",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()


def frozen_constants() -> dict:
    """The predeclared configuration, without any data-derived values."""
    from prospects import model

    return {
        "seed": stage_a.SEED,
        "sealed_cohort": stage_a.SEALED_COHORT,
        "mature_through": model.MATURE_THROUGH,
        "environment_flags": {"VALUCAST_POOLED_SHADOW": model.POOLED_SHADOW_ENABLED},
        "B": {"0": 0, "1": 5000, "2": 5000, "3": 2000,
              "4": 0, "5": 5000, "6": 0, "7": 0},
        "minimum_null_reps": 2000,
        "bootstrap_resamples": 5000,
        "configuration_grid": stage_a.configuration_grid(),
        "k_extra": [0, 8, 24],
        "dedup_rules": {
            "D1": "largest pa/ip; ties keep first in list order",
            "D2": "D1 only when sample equals sum of others and a counting stat also matches",
            "D3": "optional team-key probe: no-team row when present, otherwise D1",
            "hitter_sample_tolerance": 0.01,
            "pitcher_sample_tolerance": 0.34,
            "counting_fields": ["hr", "r", "rbi", "sb", "so"],
        },
        "purge_rule": {
            "training": "c + horizon <= T",
            "outcome_horizon_years": model.OUTCOME_HORIZON_YEARS,
            "impact_horizon_years": 4,
            "clip": "c < season_year <= min(c + 4, T)",
        },
        "thresholds": {
            "permutation_extreme_p": 0.01,
            "permutation_ambiguous_p": 0.05,
            "n2_false_active_fraction": 0.05,
            "gate_min_improvement_pct": 2.0,
            "n2_median_improvement_pct": 1.0,
            "gate_min_sample": 250,
            "pooled_gate_min_sample": 500,
            "purge_margin_drop_fraction": 0.5,
            "reference_margin_drop_fraction": 0.5,
            "reference_bootstrap_excludes_zero": True,
            "serve_top_n": 100,
            "serve_outside_support_fraction": 0.1,
            "serve_outside_feature_count": 3,
            "serve_step_score_change": 0.02,
            "serve_step_rank_move": 10,
            "serve_step_fraction": 0.1,
            "dedup_label_change_fraction": 0.05,
            "dedup_any_impact_gate_change": True,
            "dedup_any_graduated_flip": True,
            "dedup_top_n": 50,
            "dedup_minimum_overlap": 45,
            "dedup_minimum_spearman": 0.99,
        },
    }


def _versions() -> dict:
    import numpy
    import scipy

    return {"python": platform.python_version(), "numpy": numpy.__version__,
            "scipy": scipy.__version__}


def build_freeze_manifest(input_sha256: str, commit: str | None = None) -> dict:
    """Build the owner's future manifest in memory; never write it here."""
    if re.fullmatch(r"[0-9a-f]{64}", input_sha256) is None:
        raise stage_a.FreezeError()
    return {
        "code_commit": commit or _git("rev-parse", "HEAD"),
        "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                   for name in HASHED_FILES},
        "input_sha256": input_sha256,
        "versions": _versions(),
        **frozen_constants(),
    }


def verify_freeze_manifest(manifest: dict, input_path: Path | None = None) -> None:
    """Check frozen source, settings and versions before any contract parsing."""
    try:
        from prospects import model

        _verify_served_environment_defaults()
        if model.MATURE_THROUGH != 2019 or manifest.get("mature_through") != 2019:
            raise stage_a.FreezeError()
        if not re.fullmatch(r"[0-9a-f]{40,64}", manifest.get("code_commit", "")):
            raise stage_a.FreezeError()
        expected = build_freeze_manifest(manifest["input_sha256"], manifest["code_commit"])
        if manifest != expected:
            raise stage_a.FreezeError()
        if input_path is not None:
            digest = hashlib.sha256(Path(input_path).read_bytes()).hexdigest()
            if digest != manifest["input_sha256"]:
                raise stage_a.FreezeError()
    except stage_a.FreezeError:
        raise
    except Exception:
        raise stage_a.FreezeError() from None


def _verify_real_checkout(manifest: dict) -> None:
    try:
        code_commit = manifest["code_commit"]
        if not re.fullmatch(r"[0-9a-f]{40,64}", code_commit):
            raise stage_a.FreezeError()
        if _git("status", "--porcelain"):
            raise stage_a.FreezeError()
        _git("merge-base", "--is-ancestor", code_commit, "HEAD")
        changed = _git("diff", "--name-only", code_commit, "HEAD").splitlines()
        if any(name != MANIFEST_RELATIVE_PATH for name in changed):
            raise stage_a.FreezeError()
    except stage_a.FreezeError:
        raise
    except Exception:
        raise stage_a.FreezeError() from None


def _verify_served_environment_defaults() -> None:
    from prospects import model

    if os.environ.get("VALUCAST_POOLED_SHADOW", "1") == "0" or model.POOLED_SHADOW_ENABLED is not True:
        raise stage_a.FreezeError()


def validate_environment(out: Path, synthetic: bool) -> Path:
    if any(name in os.environ for name in ("GITHUB_ACTIONS", "CI", "RUNNER_OS")):
        raise RuntimeError()
    resolved = Path(out).resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise RuntimeError()
    if synthetic:
        temporary_roots = [Path(os.environ[name]).resolve() for name in ("TEMP", "TMP", "TMPDIR")
                           if os.environ.get(name)]
        if not temporary_roots:
            temporary_roots = [Path(tempfile.gettempdir()).resolve()]
        if not any(path in resolved.parents for path in temporary_roots):
            raise RuntimeError()
    if not synthetic:
        _verify_served_environment_defaults()
        if os.environ.get("VALUCAST_STAGE_A_REAL") != "1":
            raise RuntimeError()
    return resolved


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--stage", choices=["all", *map(str, range(8))], default="all")
    parser.add_argument("--reps", type=int)
    parser.add_argument("--budget-minutes", type=float)
    parser.add_argument("--k-extra", type=int, choices=(0, 8, 24), default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--hash-inputs", action="store_true")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    status, digest = "error", "0" * 64
    previous_logging_level = logging.root.manager.disable
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            logging.disable(logging.CRITICAL)
            try:
                if stage_a is None:
                    raise RuntimeError()
                args = _parser().parse_args(argv)
                out = validate_environment(args.out, args.synthetic)
                if args.reps is not None and args.reps < 1:
                    raise ValueError()
                if args.budget_minutes is not None and (
                    not math.isfinite(args.budget_minutes) or args.budget_minutes <= 0
                ):
                    raise ValueError()
                options = dict(stage=args.stage, reps=args.reps,
                               budget_minutes=args.budget_minutes,
                               k_extra=args.k_extra, resume=args.resume)
                if args.synthetic:
                    if args.hash_inputs:
                        raise ValueError()
                    result = stage_a.run_synthetic(out, **options)
                else:
                    from prospects.input_contract import VALUCAST_INPUT_PATH

                    if args.hash_inputs:
                        if _git("status", "--porcelain"):
                            raise stage_a.FreezeError()
                        digest = hashlib.sha256(VALUCAST_INPUT_PATH.read_bytes()).hexdigest()
                        status = "ok"
                        result = None
                    else:
                        manifest = json.loads(args.manifest.read_bytes())
                        _verify_real_checkout(manifest)
                        verify_freeze_manifest(manifest, VALUCAST_INPUT_PATH)
                        safe = stage_a.load_sealed_safe_contract(VALUCAST_INPUT_PATH)
                        if safe.input_sha256 != manifest["input_sha256"]:
                            raise stage_a.FreezeError()
                        result = stage_a.run_stages(safe, out, **options)
                if result is not None:
                    status = result.get("status", "ok")
                    if status not in ("ok", "partial"):
                        raise ValueError()
                    digest = hashlib.sha256((out / "results.json").read_bytes()).hexdigest()
            except BaseException as error:
                if stage_a is not None and isinstance(error, stage_a.SealedDataError):
                    status = "abort_sealed"
                elif stage_a is not None and isinstance(error, stage_a.FreezeError):
                    status = "abort_hash"
                elif stage_a is not None and isinstance(error, stage_a.EquivalenceError):
                    status = "abort_equiv"
                else:
                    status = "error"
            finally:
                logging.disable(previous_logging_level)
    print(f"STAGE_A status={status} results_sha256={digest}")
    return 0 if status in ("ok", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
