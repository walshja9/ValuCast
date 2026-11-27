"""Forward-ledger scoreboard roll-up (plan 030, S2): the Anticipation Score.

`plans/030-forward-ledger.md` PART C. This is the fast-layer standings: it ROLLS
UP the already-frozen gaps claim ledger into a single headline (the median signed
"anticipation" in days), a bootstrap CI, a sign-permutation null, and the full
funnel. It reads committed ARTIFACTS only — the claim ledger, the cohort registry,
and the dated rank archive — and re-derives nothing the frozen modules own.

Two things this module MUST NOT do (both validator-checked downstream):

1. **Never import the frozen protocol modules.** `gaps_claim_ledger`,
   `ahead_of_consensus*`, `call_up_receipts`, the frozen scorecards — none of them
   become a runtime dependency of a post-freeze benchmark (the repo's
   decouple-by-redeclaration rule). The claim OUTCOMES are read verbatim from the
   committed ledger; the only thing recomputed here is the aggregate consensus
   MEDIAN at two dates, needed for the A4 adverse-movement derivations, and that
   reconstruction is REDECLARED (imported from `prospects.forward_cohort`, the S1
   sibling that ports `_public_source_consensus` verbatim — never from a frozen
   module).
2. **Never emit a `role` field or any pitcher/hitter split.** The registered
   one-look protocol (plan 028) forbids it on a standings surface. Claim-SIDE splits
   (higher / lower) are the claim direction, not player role, and ARE reported.
   Consensus is recomputed in-memory only; nothing per-source is ever written out.

--- Anticipation Score, frozen exactly per plan 030 A4 -------------------------
Scoring pool = claims with a terminal EXTERNAL resolution only. Each pooled claim
contributes a SIGNED lead time in days (`resolved_date - claim_date`):

  Win  (+days):
    - resolved_by_callup on the HIGHER side (the field called him up while we led),
    - resolved_by_consensus_move (the field moved toward our rank — direction is
      baked into the ledger's own resolver, so any side counts).
  Loss (-days):
    - resolved_by_callup on the LOWER side (a fade we made got called up),
    - adverse-at-expiry: an expired_unresolved claim where, recomputing consensus
      from the archive at claim_date vs expiry_date, the field moved >= 10 spots
      AWAY from the claim direction (else the expiry is EXCLUDED from the pool,
      still funnel-counted),
    - adverse-before-retraction: a retracted_by_model_move claim where the field had
      ALREADY moved >= 10 spots away at the retraction date (closes the "retract at
      day 59 to dodge the expiry penalty" hole).

Excluded from the pool (always funnel-counted): clean retractions, benign expiries,
open claims. The self-retraction rate is a mandatory companion stat.

Headline = median of the signed pool. The VERDICT (significance) is gated by an
exact one-sided binomial SIGN TEST on the resolved-claim direction — significant
only when P(X >= k | n_nonzero, 0.5) < 0.025 in the LEADING (positive) direction
and the headline median is positive.
This is decision-equivalent to a 95% Clopper-Pearson interval for the win-share
excluding 0.5 on that side, and is strictly MORE conservative than the old
bootstrap-CI-straddles-zero rule, which under-covered on small discrete
sign-imbalanced pools. The bootstrap 95% percentile CI (effect-size band) and the
sign-permutation null (null band) are still computed and published at frozen seed
29016 / 10,000 resamples, demoted to DESCRIPTIVE CONTEXT — they no longer gate the
verdict. The score is PROVISIONAL until some claim has reached EXPIRY_DAYS age (no
expiry can fire before then, so the loss side cannot yet appear); "leading, not yet
significant" whenever the sign test does not clear the 0.025 leading-direction bar.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date

import numpy as np

from prospects.forward_cohort import (
    _public_source_consensus,
    _public_source_ranks,
)

PROTOCOL_VERSION = "030-v1"
ARTIFACT_NAME = "valucast_forward_scoreboard"

# --- Inherited ledger dials (REDECLARED, never imported from the frozen ledger) ---
# Cited verbatim so a reader can verify inheritance; the ledger owns them, we roll
# them up. The adverse-movement floor mirrors the ledger's move floors (10 spots).
ADVERSE_MOVE_FLOOR_SPOTS = 10
EXPIRY_DAYS = 60
SIDES = ("higher", "lower")

# --- Frozen resampling constants (plan 030 A4 / invariant 7) --------------------
RESAMPLE_SEED = 29016
N_RESAMPLES = 10_000
CI_PERCENTILE = 95  # two-sided 95% percentile CI (effect-size band; descriptive)

# --- Verdict gate: exact one-sided binomial sign test ---------------------------
# The published significance decision. One-sided alpha = 0.025 in the LEADING
# (positive/win) direction is decision-equivalent to a two-sided 95% Clopper-Pearson
# interval for the win-share excluding 0.5 on the leading side. Strictly more
# conservative than the retired bootstrap-CI-straddles-zero rule.
SIGN_TEST_ALPHA = 0.025
VERDICT_BASIS = "exact_binomial_sign_test_p025_one_sided"
PROVISIONAL_LABEL = "provisional (no claim has reached the expiry window)"

# The ledger's terminal outcomes we roll up (verbatim vocabulary; not imported).
_TERMINAL_OUTCOMES = frozenset(
    {
        "resolved_by_callup",
        "resolved_by_consensus_move",
        "expired_unresolved",
        "retracted_by_model_move",
    }
)

# The independence statement, published verbatim with every standings view (A1).
INDEPENDENCE_ATTESTATION = (
    "ValuCast scores are computed without any consensus input; external source "
    "ranks are carried as context only and never feed the model. This independence "
    "is validator-enforced."
)


def _days_between(start: str | None, end: str | None) -> int | None:
    try:
        return (date.fromisoformat(str(end)[:10]) - date.fromisoformat(str(start)[:10])).days
    except (TypeError, ValueError):
        return None


# --- Consensus-at-date lookup (in-memory; median + count only) ------------------
# The board archive rows key on identity_key = f"{mlbam_id}_{role.lower()}", the
# same identity the ledger claims carry. We recompute ONLY the aggregate median at a
# given date from the archived source_ranks — nothing per-source is retained.

def _source_ranks(row: dict) -> dict:
    context = row.get("context_only")
    if isinstance(context, dict) and isinstance(context.get("source_ranks"), dict):
        return context["source_ranks"]
    raw = row.get("source_ranks")
    return raw if isinstance(raw, dict) else {}


def _identity_key(row: dict) -> str | None:
    if row.get("mlbam_id") in (None, "") or row.get("role") in (None, ""):
        return None
    return f"{row['mlbam_id']}_{str(row['role']).lower()}"


def _consensus_by_date(archive: dict[str, list[dict]]) -> dict[str, dict[str, int]]:
    """date -> {identity_key: consensus_median}. Only identities with a defined
    consensus (board_count >= 2 external boards) appear; the per-source ranks used
    to compute the median are discarded here and never leave this function."""
    out: dict[str, dict[str, int]] = {}
    for archive_date, board in archive.items():
        by_key: dict[str, int] = {}
        for row in board:
            if not isinstance(row, dict):
                continue
            key = _identity_key(row)
            if key is None:
                continue
            public_ranks = _public_source_ranks(_source_ranks(row))
            if len(public_ranks) < 2:
                continue
            consensus = _public_source_consensus(public_ranks)
            if consensus is not None:
                by_key.setdefault(key, consensus)
        out[archive_date] = by_key
    return out


def _consensus_at(
    consensus_by_date: dict[str, dict[str, int]], as_of: str | None, identity_key: str
) -> int | None:
    """Consensus median for `identity_key` on the archive date == `as_of`. Returns
    None when the date is missing from the archive or the identity had no consensus
    (< 2 boards) that day — the caller treats a missing endpoint as "not adverse"."""
    if not as_of:
        return None
    return (consensus_by_date.get(as_of) or {}).get(identity_key)


def _moved_away(side: str, consensus_start: int | None, consensus_end: int | None) -> int | None:
    """Spots the FIELD moved AWAY from the claim direction between two dates, or None
    if either endpoint is missing. Sign convention is the ledger's (smaller consensus
    rank = better board position):

    - higher side (we rank him ABOVE the field): away = the field faded him FURTHER,
      i.e. consensus grew -> (end - start).
    - lower side (we FADE him vs the field): away = the field caught up to him,
      i.e. consensus shrank -> (start - end).

    A positive return is movement away; compare >= ADVERSE_MOVE_FLOOR_SPOTS."""
    if consensus_start is None or consensus_end is None:
        return None
    delta = consensus_end - consensus_start
    return delta if side == "higher" else -delta


def _score_claim(
    claim: dict, consensus_by_date: dict[str, dict[str, int]]
) -> tuple[str, float | None]:
    """Classify one claim into a funnel bucket and (if pooled) its signed lead time.

    Returns (bucket, signed_days). `signed_days` is None for every claim excluded
    from the median (open, clean retraction, benign expiry). Buckets are the funnel
    labels, disjoint from the ledger's outcome vocabulary only where A4 splits an
    outcome (retracted -> adverse vs clean; expired -> adverse vs benign)."""
    outcome = claim.get("outcome")
    side = claim.get("side")
    claim_date = claim.get("claim_date")
    resolved_date = claim.get("resolved_date")
    identity_key = claim.get("identity_key")

    if outcome == "open":
        return "open", None

    if outcome == "resolved_by_callup":
        days = _days_between(claim_date, resolved_date)
        if days is None:
            return "callup_unscored", None
        if side == "higher":
            return "callup_win", float(days)  # field called him up while we led
        return "callup_loss", float(-days)  # a fade got called up -> loss

    if outcome == "resolved_by_consensus_move":
        days = _days_between(claim_date, resolved_date)
        if days is None:
            return "consensus_move_unscored", None
        # The ledger only records a consensus move TOWARD our rank, so any side wins.
        return "consensus_move_win", float(days)

    if outcome == "retracted_by_model_move":
        # Adverse-before-retraction: at the retraction date the field had ALREADY
        # moved >= floor away from our claim -> a loss, not a clean self-correction.
        away = _moved_away(
            side,
            _consensus_at(consensus_by_date, claim_date, identity_key),
            _consensus_at(consensus_by_date, resolved_date, identity_key),
        )
        if away is not None and away >= ADVERSE_MOVE_FLOOR_SPOTS:
            days = _days_between(claim_date, resolved_date)
            if days is not None:
                return "adverse_before_retraction", float(-days)
        return "clean_retraction", None  # self-correction, excluded from the median

    if outcome == "expired_unresolved":
        away = _moved_away(
            side,
            _consensus_at(consensus_by_date, claim_date, identity_key),
            _consensus_at(consensus_by_date, resolved_date, identity_key),
        )
        if away is not None and away >= ADVERSE_MOVE_FLOOR_SPOTS:
            days = _days_between(claim_date, resolved_date)
            if days is not None:
                return "adverse_at_expiry", float(-days)
        return "benign_expiry", None  # aged out with no adverse move, excluded

    return "unclassified", None


# --- Headline statistics --------------------------------------------------------

def _bootstrap_ci(pool: np.ndarray) -> tuple[float, float]:
    """Percentile bootstrap CI of the median at the frozen seed. Resample the pool
    with replacement N_RESAMPLES times, take the median of each, return the 2.5 /
    97.5 percentiles."""
    rng = np.random.default_rng(RESAMPLE_SEED)
    n = pool.shape[0]
    idx = rng.integers(0, n, size=(N_RESAMPLES, n))
    medians = np.median(pool[idx], axis=1)
    lo = float(np.percentile(medians, (100 - CI_PERCENTILE) / 2))
    hi = float(np.percentile(medians, 100 - (100 - CI_PERCENTILE) / 2))
    return lo, hi


def _permutation_null(pool: np.ndarray) -> dict:
    """Sign-permutation null interval, published as CONTEXT only. The pool measures
    signed lead time, so the null is "the sign is coin-flip noise". Randomly flip
    each entry's sign N_RESAMPLES times (same frozen seed) and collect the null
    distribution of the median. Reports the null median (0.0 by construction, echoed
    for transparency) and its CI interval.

    NO p-value is emitted from THIS null: a sign-permutation p-value is degenerate
    for low-magnitude-variance pools (a unanimous same-sign pool yields a large,
    uninformative p) — identified in pre-registration review and removed before
    freeze. This null is published as a context band only; the VERDICT is gated by
    the exact binomial sign test (`_sign_test`), not by this null and not by the
    bootstrap CI."""
    rng = np.random.default_rng(RESAMPLE_SEED)
    n = pool.shape[0]
    signs = rng.integers(0, 2, size=(N_RESAMPLES, n)) * 2 - 1  # +/-1
    null_medians = np.median(np.abs(pool) * signs, axis=1)
    return {
        "null_median": 0.0,
        "null_ci_low": float(np.percentile(null_medians, (100 - CI_PERCENTILE) / 2)),
        "null_ci_high": float(np.percentile(null_medians, 100 - (100 - CI_PERCENTILE) / 2)),
    }


def _binomial_tail_ge(k: int, n: int) -> float:
    """Exact upper binomial tail P(X >= k | n, p=0.5) = sum_{i=k}^{n} C(n,i) / 2^n.
    Stdlib only (math.comb) — this module runs in the nightly build, no scipy."""
    if n <= 0:
        return 1.0
    if k <= 0:
        return 1.0
    total = sum(math.comb(n, i) for i in range(k, n + 1))
    return total / (2 ** n)


def _sign_test(pool: np.ndarray) -> dict:
    """Exact one-sided binomial SIGN TEST on the resolved-claim direction — the gate.

    Signed lead-times split into positives (leading / wins), negatives (behind /
    losses), and exact zeros (same-day timing). Zeros carry no directional sign and
    are EXCLUDED from the test (disclosed via `zeros_excluded`). Over the n_nonzero
    signed claims, under H0 the sign is a fair coin (p=0.5); the majority direction's
    tail probability is p = P(X >= k_max | n_nonzero, 0.5).

    Verdict is "significant" only when that p < SIGN_TEST_ALPHA AND the majority
    direction is POSITIVE (leading). p < 0.025 one-sided is decision-equivalent to a
    two-sided 95% Clopper-Pearson interval for the win-share excluding 0.5 on the
    leading side. A significant NEGATIVE majority is reported as `direction="behind"`
    and must NOT be labeled as a win by the caller."""
    positives = int(np.count_nonzero(pool > 0))
    negatives = int(np.count_nonzero(pool < 0))
    zeros = int(np.count_nonzero(pool == 0))
    n_nonzero = positives + negatives
    k_max = max(positives, negatives)
    p_value = _binomial_tail_ge(k_max, n_nonzero)
    if positives > negatives:
        direction = "leading"
    elif negatives > positives:
        direction = "behind"
    else:
        direction = "even"
    median = float(np.median(pool)) if pool.size else 0.0
    significant = bool(
        p_value < SIGN_TEST_ALPHA
        and direction == "leading"
        and median > 0
    )
    return {
        "basis": VERDICT_BASIS,
        "positives": positives,
        "negatives": negatives,
        "zeros_excluded": zeros,
        "n_nonzero": n_nonzero,
        "p_value": p_value,
        "direction": direction,
        "significant": significant,
    }


def scoreboard_verdict_label(sign_test: dict, median_lead_days: float | None) -> str:
    direction = sign_test.get("direction")
    p_value = sign_test.get("p_value")
    if direction == "leading":
        significant = (
            isinstance(p_value, (int, float))
            and not isinstance(p_value, bool)
            and math.isfinite(p_value)
            and p_value < SIGN_TEST_ALPHA
            and median_lead_days is not None
            and median_lead_days > 0
        )
        return "significant" if significant else "leading, not yet significant"
    if direction == "behind":
        significant = (
            isinstance(p_value, (int, float))
            and p_value < SIGN_TEST_ALPHA
            and median_lead_days is not None
            and median_lead_days < 0
        )
        return "behind, significant" if significant else "behind, not yet significant"
    return "even, not yet significant"


def _headline(pool_days: list[float], provisional: bool) -> dict:
    """The Anticipation Score headline. Median of the signed pool + bootstrap CI
    (effect-size band) + sign-permutation null (null band), both DESCRIPTIVE. The
    VERDICT is gated by the exact binomial sign test. Empty pool -> nulls, labeled
    explicitly (no claim has resolved into the pool yet)."""
    if not pool_days:
        return {
            "pool_size": 0,
            "median_lead_days": None,
            "ci_low": None,
            "ci_high": None,
            "null": None,
            "sign_test": None,
            "verdict_basis": VERDICT_BASIS,
            "provisional": provisional,
            "label": "no resolved claims in pool yet",
        }
    pool = np.asarray(pool_days, dtype=float)
    median = float(np.median(pool))
    ci_low, ci_high = _bootstrap_ci(pool)
    null = _permutation_null(pool)
    sign_test = _sign_test(pool)
    # Verdict gate = exact one-sided binomial sign test (NOT the bootstrap CI band).
    # Provisional wins outright; then a significant LEADING majority is "significant";
    # a significant BEHIND majority is honestly labeled a loss (never a win); every
    # inconclusive pool is "leading, not yet significant".
    if provisional:
        label = PROVISIONAL_LABEL
    else:
        label = scoreboard_verdict_label(sign_test, median)
    return {
        "pool_size": int(pool.shape[0]),
        "median_lead_days": median,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "null": null,
        "sign_test": sign_test,
        "verdict_basis": VERDICT_BASIS,
        "provisional": provisional,
        "label": label,
    }


# --- Funnel ---------------------------------------------------------------------

_FUNNEL_BUCKETS = (
    "open",
    "callup_win",
    "callup_loss",
    "callup_unscored",
    "consensus_move_win",
    "consensus_move_unscored",
    "adverse_before_retraction",
    "clean_retraction",
    "adverse_at_expiry",
    "benign_expiry",
    "unclassified",
)


def _empty_bucket_counts() -> dict[str, int]:
    return {bucket: 0 for bucket in _FUNNEL_BUCKETS}


def _content_sha256(payload: dict) -> str:
    """sha256 over the deterministic JSON body EXCLUDING the hash field (matches the
    S1 cohort idiom: sort_keys + compact separators)."""
    body = {k: v for k, v in payload.items() if k != "content_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cohort_section(registry: dict | None) -> dict:
    """Registered-cohort roll-up from the S1 registry, or a pending stub when the
    registry does not exist yet (the scoreboard is buildable before cohort #1 is
    registered — it just marks the cohort layer pending)."""
    if not registry or not isinstance(registry.get("cohorts"), dict) or not registry["cohorts"]:
        return {"status": "pending", "cohort_count": 0, "cohorts": []}
    cohorts = []
    for registration_date in sorted(registry["cohorts"]):
        cohort = registry["cohorts"][registration_date]
        counts = cohort.get("counts") or {}
        cohorts.append(
            {
                "registration_date": registration_date,
                "archive_date": cohort.get("archive_date"),
                "content_sha256": cohort.get("content_sha256"),
                "eligible_total": counts.get("eligible_total"),
                "consensus_covered": counts.get("consensus_covered"),
                "rank_only": counts.get("rank_only"),
            }
        )
    return {"status": "registered", "cohort_count": len(cohorts), "cohorts": cohorts}


def build_scoreboard(
    *,
    ledger: dict,
    archive: dict[str, list[dict]],
    registry: dict | None = None,
    generated_at: str,
) -> dict:
    """Roll the committed claim ledger up into the forward scoreboard.

    - `ledger`: the parsed `valucast_gaps_claim_ledger.json` (read verbatim; its
      outcomes are authoritative and never recomputed).
    - `archive`: date -> board rows, only for the A4 adverse-movement consensus
      recompute (median-only, in-memory).
    - `registry`: the parsed S1 cohort registry, or None (cohort section pending).
    - `generated_at`: ISO timestamp (injected for determinism / testing).
    """
    claims = ledger.get("claims") or []
    consensus_by_date = _consensus_by_date(archive)

    buckets = _empty_bucket_counts()
    # "other" absorbs any claim whose side is not higher/lower (0 in real data) so the
    # per-side buckets still sum to the total — a missing side never spuriously fails
    # the validator's by_side reconciliation.
    side_buckets = {side: _empty_bucket_counts() for side in (*SIDES, "other")}
    pool_days: list[float] = []
    total_claims = 0
    retracted_total = 0

    for claim in claims:
        if not isinstance(claim, dict):
            continue
        total_claims += 1
        side = claim.get("side")
        if claim.get("outcome") == "retracted_by_model_move":
            retracted_total += 1
        bucket, signed_days = _score_claim(claim, consensus_by_date)
        buckets[bucket] = buckets.get(bucket, 0) + 1
        side_key = side if side in SIDES else "other"
        side_buckets[side_key][bucket] = side_buckets[side_key].get(bucket, 0) + 1
        if signed_days is not None:
            pool_days.append(signed_days)

    # Provisional until SOME claim has reached the expiry window (no expiry can fire,
    # so the loss side cannot yet appear). Measured off the ledger's own claim ages.
    today = generated_at[:10]
    max_age = max(
        (_days_between(c.get("claim_date"), today) or 0)
        for c in claims
        if isinstance(c, dict)
    ) if claims else 0
    provisional = max_age < EXPIRY_DAYS

    headline = _headline(pool_days, provisional)

    # Funnel: whole + per-side. Wins/losses/excluded/unscored are derived views over
    # the same buckets. These four views PARTITION every funnel bucket, so
    # wins + losses + excluded_from_pool + unscored_or_unclassified == total_claims
    # (validator-checked — no bucket belongs to no published view).
    win_buckets = ("callup_win", "consensus_move_win")
    loss_buckets = ("callup_loss", "adverse_before_retraction", "adverse_at_expiry")
    excluded_buckets = ("open", "clean_retraction", "benign_expiry")
    # Resolved-but-undatable + never-classified claims: a resolved claim missing its
    # resolved_date lands in *_unscored; an unknown outcome lands in unclassified.
    # Neither wins, loses, nor is a clean/benign exclusion, so they get their own view
    # instead of silently vanishing from the reconciliation.
    unscored_buckets = ("callup_unscored", "consensus_move_unscored", "unclassified")

    def _sum(counts: dict[str, int], keys) -> int:
        return sum(counts.get(k, 0) for k in keys)

    funnel = {
        "total_claims": total_claims,
        "buckets": buckets,
        "by_side": side_buckets,
        "pool_size": len(pool_days),
        "wins": _sum(buckets, win_buckets),
        "losses": _sum(buckets, loss_buckets),
        "excluded_from_pool": _sum(buckets, excluded_buckets),
        "unscored_or_unclassified": _sum(buckets, unscored_buckets),
        "open": buckets["open"],
        "self_retraction_rate": {
            "retracted": retracted_total,
            "total": total_claims,
            "rate": (retracted_total / total_claims) if total_claims else None,
        },
    }

    payload = {
        "artifact": ARTIFACT_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "independence_attestation": INDEPENDENCE_ATTESTATION,
        "source_policy": {
            "kind": "valucast_forward_scoreboard",
            "inputs": (
                "valucast_gaps_claim_ledger + valucast_prospect_rank_v1_dated_archive "
                "+ valucast_forward_cohort_registry"
            ),
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
            "per_source_ranks_written": False,
        },
        "dials": {
            "adverse_move_floor_spots": ADVERSE_MOVE_FLOOR_SPOTS,
            "expiry_days": EXPIRY_DAYS,
            "resample_seed": RESAMPLE_SEED,
            "n_resamples": N_RESAMPLES,
            "ci_percentile": CI_PERCENTILE,
        },
        "ledger_ref": {
            "signal_version": ledger.get("signal_version"),
            "generated_at": ledger.get("generated_at"),
        },
        "anticipation_score": headline,
        "funnel": funnel,
        "cohorts": _cohort_section(registry),
        "content_sha256": "",
    }
    payload["content_sha256"] = _content_sha256(payload)
    return payload
