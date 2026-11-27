"""Statcast input de-noising bridge: blend historical hit components toward
xBA/xSLG, redistribute into 1B/2B/3B/HR by the player's own extra-base mix,
with feasibility guards. alpha=0 is an exact passthrough (classic)."""
from __future__ import annotations

from collections.abc import Sequence


def league_xbh_mix(rows: Sequence[dict]) -> tuple[tuple[float, float, float], float] | None:
    """League-average extra-base shape from a season's rows:
    ((2B_share, 3B_share, HR_share), m) where m = total bases per XB hit.
    None if the league has no extra-base hits (degenerate)."""
    d = sum(float(r.get("2B", 0)) for r in rows)
    t = sum(float(r.get("3B", 0)) for r in rows)
    hr = sum(float(r.get("HR", 0)) for r in rows)
    xb = d + t + hr
    if xb <= 0:
        return None
    m = (2 * d + 3 * t + 4 * hr) / xb
    return ((d / xb, t / xb, hr / xb), m)


def denoise_components(
    row: dict,
    statcast: dict | None,
    alpha_contact: float,
    alpha_power: float,
    league_mix: tuple[tuple[float, float, float], float] | None,
) -> dict:
    """Return a copy of `row` with 1B/2B/3B/HR de-noised toward xBA/xSLG.
    Non-hit fields (PA, AB, BB, SO, ...) are preserved. Passthrough when there is
    no Statcast, AB<=0, or both alphas are 0."""
    out = dict(row)
    ab = float(row.get("AB", 0))
    if statcast is None or ab <= 0 or (alpha_contact == 0.0 and alpha_power == 0.0):
        return out

    s, d, t, hr = (float(row.get(k, 0)) for k in ("1B", "2B", "3B", "HR"))
    H = s + d + t + hr
    TB = s + 2 * d + 3 * t + 4 * hr
    xb = d + t + hr
    xba, xslg = statcast.get("xba"), statcast.get("xslg")

    # 1. De-noise the two aggregates (blend actual rate toward expected).
    if xba is not None and alpha_contact > 0:
        h_star = ab * ((1 - alpha_contact) * (H / ab) + alpha_contact * xba)
    else:
        h_star = H
    h_star = min(max(h_star, 0.0), ab)                 # clamp [0, AB]

    if xslg is not None and alpha_power > 0:
        tb_star = ab * ((1 - alpha_power) * (TB / ab) + alpha_power * xslg)
    else:
        tb_star = TB
    tb_star = max(tb_star, h_star)                     # TB >= H

    # 2. Pick the XBH shape: player's own, else league fallback, else classic power.
    if xb > 0:
        m = (2 * d + 3 * t + 4 * hr) / xb
        props = (d / xb, t / xb, hr / xb)
    elif league_mix is not None:
        props, m = league_mix
    else:
        out["1B"], out["2B"], out["3B"], out["HR"] = h_star, 0.0, 0.0, 0.0
        return out                                     # classic power: all singles

    # 3. Redistribute, clamping XB' (coherence over exact xSLG).
    xb_prime = (tb_star - h_star) / (m - 1) if m > 1 else 0.0
    xb_prime = min(max(xb_prime, 0.0), h_star)
    out["1B"] = max(0.0, h_star - xb_prime)
    out["2B"] = max(0.0, xb_prime * props[0])
    out["3B"] = max(0.0, xb_prime * props[1])
    out["HR"] = max(0.0, xb_prime * props[2])
    return out


def denoise_season(
    rows: Sequence[dict],
    statcast_map: dict[str, dict],
    alpha_contact: float,
    alpha_power: float,
) -> list[dict]:
    """De-noise every row in a season. The league XBH mix is computed from the
    season's actual rows (the reference distribution for zero-XBH players)."""
    league_mix = league_xbh_mix(rows)
    return [
        denoise_components(r, statcast_map.get(r.get("mlbam_id")),
                           alpha_contact, alpha_power, league_mix)
        for r in rows
    ]
