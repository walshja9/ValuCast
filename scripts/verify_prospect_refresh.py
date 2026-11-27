"""Post-refresh verification for the prospect outcome + impact gate work.

Run this after the daily public build rebuilds artifacts. It asserts the three
things the outcome + impact gate change was supposed to deliver, reading only
the published artifacts (read-only, no rebuild):

  1. Front Office Track shows the recovered B+/87 state, capped *only* by the
     time-based forward-observation milestone -- not by a model-score / board
     (ordinal-bridge) gate cap.
  2. Lower-minors (A / A+) prospects are scored from real current stats where
     eligible, instead of being dropped to pedigree fallback.
  3. The rebuild actually took effect (no stale artifact): both the outcome
     board gate and the category-impact gate serialize as ``active``.

Exit code 0 if every check passes, 1 otherwise. Intended for local use after
``scripts/run_daily_public_build.py`` and as a guard against silent regressions.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "data" / "models" / "valucast_prospect_model.json"
BACKTEST_PATH = ROOT / "data" / "models" / "valucast_prospect_outcome_backtest.json"

LOWER_MINORS = {"A", "A+"}
# Cap reasons that mean the grade is held down by model evidence (a gate), as
# opposed to the acceptable time-based forward-observation milestone.
MODEL_GATE_CAP_MARKERS = ("ordinal bridge", "impact gate", "board gate")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_front_office_grade() -> tuple[bool, str]:
    track = _load(BACKTEST_PATH).get("front_office_track", {})
    grade = track.get("grade")
    score = track.get("score")
    caps = track.get("cap_reasons", []) or []
    gate_caps = [c for c in caps if any(m in c.lower() for m in MODEL_GATE_CAP_MARKERS)]
    ok = grade == "B+" and score == 87 and not gate_caps
    detail = f"grade={grade} score={score} cap_reasons={caps}"
    if gate_caps:
        detail += " <- a model-gate cap is still present (a gate is not active)"
    return ok, detail


def check_lower_minors_scored() -> tuple[bool, str]:
    ranked = _load(MODEL_PATH).get("ranked", [])
    lower = [r for r in ranked if r.get("level") in LOWER_MINORS]
    scored = [
        r for r in lower
        if isinstance(r.get("expected_outcome_score"), (int, float))
    ]
    levels = sorted({r.get("level") for r in lower})
    ok = len(scored) > 0
    detail = (
        f"{len(scored)} A/A+ rows scored from stats "
        f"(levels present: {levels or 'none'}); total ranked rows={len(ranked)}"
    )
    return ok, detail


def check_gates_active_not_stale() -> tuple[bool, str]:
    model = _load(MODEL_PATH)
    board = model.get("board_gate", {}) or {}
    impact = model.get("impact_board_gate", {}) or {}
    ok = board.get("status") == "active" and impact.get("status") == "active"
    detail = (
        f"board_gate={board.get('status')} (+{board.get('improvement_pct')}%), "
        f"impact_board_gate={impact.get('status')} (+{impact.get('improvement_pct')}%)"
    )
    return ok, detail


CHECKS = (
    (
        "1. Front Office Track recovered to B+/87 (capped only by forward obs)",
        check_front_office_grade,
    ),
    (
        "2. Lower-minors (A/A+) prospects scored from real current stats",
        check_lower_minors_scored,
    ),
    (
        "3. Rebuild took effect: outcome + impact gates active (no stale artifact)",
        check_gates_active_not_stale,
    ),
)


def main() -> int:
    print("Post-refresh prospect verification")
    print("=" * 64)
    failures = 0
    for label, check in CHECKS:
        try:
            ok, detail = check()
        except FileNotFoundError as exc:
            ok, detail = False, f"missing artifact: {exc.filename}"
        except Exception as exc:  # noqa: BLE001 - report any artifact problem
            ok, detail = False, f"ERROR: {exc!r}"
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        print(f"       {detail}")
        if not ok:
            failures += 1
    print("=" * 64)
    print(f"{len(CHECKS) - failures}/{len(CHECKS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
