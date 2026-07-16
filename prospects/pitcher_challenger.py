"""E1 pitcher challenger — model-supremacy audit lane #1 (dark parallel path).

Research-only. Every lever here is OFF by default and changes NO served score
until a `model_flags` variant in prospects.rank_backtest explicitly flips it (the
same mechanism as PITCHER_STALE_PEDIGREE_DECAY_ENABLED). The 2026-07-16 audit
localized the entire pitcher accuracy deficit to young/mid-minors arms (AA C=0.629
n=90, age<=20 C=0.717) and traced two structural causes:

  (a) the pitcher OUTCOME axis carries `is_starter`/`start_rate`/`starter_x_youth`
      but no interaction between role and the CORE rate stats (k_per_9, k_bb_pct,
      era, whip). Starters and relievers have different rate base rates and
      different signal meaning, so a single ridge coefficient per rate stat is
      mis-shared across roles. The IMPACT axis already splits SP/RP (model.py
      IMPACT_CATEGORY_GROUPS / _impact_target's per-group max); this mirrors that
      split onto the OUTCOME axis by letting role bend the core-rate coefficients.

  (b) a single reliability constant (SAMPLE_REGRESSION["pitcher"] == 50 IP) shrinks
      every pitcher rate stat toward the mean equally. But K-rate stabilizes far
      faster than ERA/WHIP, so thin-sample ERA is over-trusted relative to
      thin-sample K%. This replaces the one constant with per-metric-group
      constants: a FAST group (K-adjacent) regressed LESS, a SLOW group
      (ERA/WHIP/runs-adjacent) regressed MORE.

Both levers are pure feature-space transforms; ridge weights are still fit within
train folds only (no target leakage). The constants below are FIXED and principled
(documented rationale, NOT tuned on the evaluation folds the replay reports).
"""
from __future__ import annotations

# ---- Lever (a): SP/RP split on the pitcher OUTCOME axis -----------------------
# Appended AFTER the existing 36 pitcher OUTCOME features (indices 0..35), so
# turning the flag off leaves every incumbent index, mean, std, and weight
# untouched. is_starter (a NON_SHRINK structural flag) times each core rate;
# starter_x_youth already exists (idx 18) so it is NOT duplicated here.
PITCHER_ROLE_SPLIT_FEATURE_NAMES = (
    "starter_x_k_per_9",
    "starter_x_k_bb_pct",
    "starter_x_era",
    "starter_x_whip",
)

# These are interactions of a structural flag (is_starter, in NON_SHRINK_FEATURES)
# with an already-shrunk core rate. The rate half is regressed on its own index
# upstream; the product must stay structural (a role selector), so it joins
# NON_SHRINK — otherwise the split would be double-shrunk and inert on thin
# samples, exactly the young-arm cohort this lever targets. Mirrors how the
# incumbent treats starter_x_youth (NON_SHRINK).
PITCHER_ROLE_SPLIT_NON_SHRINK = frozenset(PITCHER_ROLE_SPLIT_FEATURE_NAMES)


def pitcher_role_split_extra(base: list[float]) -> list[float]:
    """SP-interaction features for the pitcher outcome vector, from the base vector.

    base is the 8-wide canonical pitcher feature vector
    (k_per_9, bb_per_9, k_bb_pct, era, whip, youth, level, is_starter).
    Returns the four is_starter x core-rate products in
    PITCHER_ROLE_SPLIT_FEATURE_NAMES order.
    """
    k_per_9, _bb_per_9, k_bb_pct, era, whip, _youth, _level, is_starter = base
    return [
        is_starter * k_per_9,
        is_starter * k_bb_pct,
        is_starter * era,
        is_starter * whip,
    ]


# ---- Lever (b): per-metric-group reliability shrink ---------------------------
# reliability_group(sample) = sample / (sample + constant[group]). Same functional
# form as the incumbent's single reliability, only the constant is group-specific.
# Smaller constant => shrinks LESS => trusts thin samples MORE (fast-stabilizing).
# Larger constant  => shrinks MORE => trusts thin samples LESS (slow-stabilizing).
#
# Principled anchors (documented, fixed, NOT fit on eval folds):
#   FAST = 25 IP : K%/whiff metrics stabilize by ~30-70 TBF in the public
#                  stabilization literature (Carleton). At the minors sample sizes
#                  here (median well above 25 IP) a 25-IP prior lets a genuine
#                  strikeout signal through on a thin line instead of diluting it.
#   SLOW = 90 IP : ERA/WHIP/runs-allowed are BABIP/sequencing/LOB driven and
#                  stabilize far slower (hundreds of BF). A larger prior keeps a
#                  thin, lucky/unlucky ERA from dominating the score.
#   OTHER = 50 IP: the incumbent SAMPLE_REGRESSION["pitcher"] value, applied to
#                  every remaining shrunk feature so ONLY the two flagged groups
#                  move relative to baseline.
PITCHER_SHRINK_GROUP_CONSTANTS = {"fast": 25.0, "slow": 90.0, "other": 50.0}

# Core rate names and their derived/interaction relatives, grouped by stabilization
# speed. Membership is by feature NAME so it survives feature-vector reordering.
# Only names that are actually shrunk (SHRINK_FEATURES + shrink-by-default) matter;
# any structural/NON_SHRINK name here is simply never consulted.
_PITCHER_FAST_SHRINK = frozenset(
    {
        "k_per_9",
        "k_bb_pct",
        "k_to_bb_per_9",
        "k_bb_pct_x_youth",
        "k_per_9_x_level",
        "k_bb_pct_x_level",
    }
)
_PITCHER_SLOW_SHRINK = frozenset(
    {
        "era",
        "whip",
        "hr_per_9",
        "h_per_9",
        "era_x_youth",
        "whip_x_youth",
        "era_x_whip",
        "era_x_level",
        "whip_x_level",
    }
)


def pitcher_shrink_group(name: str) -> str:
    """Map a pitcher feature name to its stabilization group.

    Walk-adjacent rates (bb_per_9, walks_per_9_raw, bb_per_9_x_level) and every
    other shrunk feature fall to 'other' (the incumbent 50-IP constant), so the
    lever moves ONLY the K-fast and ERA/WHIP-slow groups relative to baseline.
    """
    if name in _PITCHER_FAST_SHRINK:
        return "fast"
    if name in _PITCHER_SLOW_SHRINK:
        return "slow"
    return "other"


def pitcher_group_reliability(sample: float, name: str) -> float:
    """Per-feature reliability for the per-group shrink lever (pitchers only)."""
    constant = PITCHER_SHRINK_GROUP_CONSTANTS[pitcher_shrink_group(name)]
    return sample / (sample + constant) if (sample + constant) else 0.0
