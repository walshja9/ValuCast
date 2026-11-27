import json
import sys

sys.path.insert(0, "/home/user/ValuCast")
from quality.valucast_governor import _prospect_transition_continuity  # noqa: E402

SP = "/tmp/claude-0/-home-user-ValuCast/f84fd2f2-7e86-57ab-b963-1503c61daf79/scratchpad/eval031"
DAYS = ["2026-07-23", "2026-07-24", "2026-07-25", "2026-07-26", "2026-07-27", "2026-07-28"]
CONF_BUCKETS = {"thin_current_sample_confidence", "moderate_thin_sample_confidence"}


def load(path):
    return json.load(open(path))


boards = {arm: {d: load(f"{SP}/boards/{arm}/{d}.json") for d in DAYS} for arm in ("armA", "armB")}
prior = load(f"{SP}/boards/prior-2026-07-22.json")

# ---------------- Q1 ----------------
print("== Q1 ==")
q1 = {}
for arm in ("armA", "armB"):
    seq = [("2026-07-22", prior)] + [(d, boards[arm][d]) for d in DAYS]
    for (pd, pb), (cd, cb) in zip(seq, seq[1:]):
        res = _prospect_transition_continuity(cb, pb)
        det = res.get("details", res)
        # _check may nest; find incident_count robustly
        def find(key, obj):
            if isinstance(obj, dict):
                if key in obj:
                    return obj[key]
                for v in obj.values():
                    r = find(key, v)
                    if r is not None:
                        return r
            return None
        cnt = find("incident_count", res)
        samples = find("samples", res) or []
        matched = find("evaluated_matched_row_count", res)
        q1[(arm, pd, cd)] = (cnt, matched, samples)
        names = "; ".join(
            f"{s.get('name')} ({s.get('role')}, {s.get('old_level')}->{s.get('new_level')}, final_delta={s.get('final_score_delta')})"
            for s in samples
        )
        print(f"{arm} {pd}->{cd}: incidents={cnt} matched={matched} {names}")

# ---------------- Q2 ----------------
def key(row):
    mid = row.get("mlbam_id")
    role = row.get("role")
    if mid in (None, "") or role not in ("hitter", "pitcher"):
        return None
    return (str(mid), str(role))


def bc_rules(row):
    bc = (row.get("components") or {}).get("bucket_calibration") or {}
    rules = [r for r in (bc.get("rules") or []) if isinstance(r, dict)]
    return rules


def rule_buckets(row):
    return {str(r.get("bucket")) for r in bc_rules(row) if r.get("bucket")}


def floor_applied(row):
    return any(r.get("continuity_floor_applied") is True for r in bc_rules(row))


print("\n== Q2 ==")
pooled = []
per_day_stats = {}
prevB = {"2026-07-23": prior}
for i, d in enumerate(DAYS[:-1]):
    prevB[DAYS[i + 1]] = boards["armB"][d]

for d in DAYS:
    A = {k: r for r in boards["armA"][d]["board"] if (k := key(r))}
    B = {k: r for r in boards["armB"][d]["board"] if (k := key(r))}
    P = {k: r for r in prevB[d]["board"] if (k := key(r))}
    common = set(A) & set(B)
    only_a, only_b = len(set(A) - set(B)), len(set(B) - set(A))
    rows = []
    for k in common:
        ra, rb = A[k], B[k]
        sa, sb = ra.get("score"), rb.get("score")
        if sa is None or sb is None:
            continue
        delta = sb - sa
        if abs(delta) < 0.01:
            continue
        pr = P.get(k)
        level_transition = pr is not None and pr.get("level") != rb.get("level")
        buckets = rule_buckets(rb)
        intended = floor_applied(rb) or (bool(buckets & CONF_BUCKETS) and level_transition)
        rows.append(
            {
                "day": d,
                "key": k,
                "name": rb.get("name"),
                "role": k[1],
                "level": rb.get("level"),
                "delta": delta,
                "abs": abs(delta),
                "score_a": sa,
                "score_b": sb,
                "rank_a": ra.get("rank"),
                "rank_b": rb.get("rank"),
                "buckets": sorted(buckets),
                "floor": floor_applied(rb),
                "level_transition": level_transition,
                "intended": intended,
                "reliability": (rb.get("components") or {}).get("sample_reliability"),
                "rules_b": bc_rules(rb),
                "adj_a": ((A[k].get("components") or {}).get("bucket_calibration") or {}).get("adjustment"),
                "adj_b": ((rb.get("components") or {}).get("bucket_calibration") or {}).get("adjustment"),
            }
        )
    pooled.extend(rows)
    per_day_stats[d] = {"rows": rows, "matched": len(common), "only_a": only_a, "only_b": only_b}


def pctl(vals, p):
    if not vals:
        return None
    v = sorted(vals)
    if len(v) == 1:
        return v[0]
    idx = p / 100 * (len(v) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (idx - lo)


def summarize(rows):
    intd = [r for r in rows if r["intended"]]
    unin = [r for r in rows if not r["intended"]]
    si = sum(r["abs"] for r in intd)
    su = sum(r["abs"] for r in unin)
    tot = si + su
    ua = [r["abs"] for r in unin]
    return {
        "affected": len(rows),
        "intended": len(intd),
        "unintended": len(unin),
        "sum_int": si,
        "sum_unint": su,
        "share_int": (si / tot * 100) if tot else None,
        "unint_median": pctl(ua, 50),
        "unint_p95": pctl(ua, 95),
    }


def t100_moves(rows):
    out = []
    for r in rows:
        ra, rb = r["rank_a"], r["rank_b"]
        if ra is None or rb is None:
            continue
        if (ra <= 100) != (rb <= 100):
            out.append(r)
    return out


for d in DAYS:
    st = per_day_stats[d]
    s = summarize(st["rows"])
    un100 = t100_moves([r for r in st["rows"] if not r["intended"]])
    print(
        f"{d}: matched={st['matched']} onlyA={st['only_a']} onlyB={st['only_b']} "
        f"affected={s['affected']} intended={s['intended']} unintended={s['unintended']} "
        f"sum|d|_int={s['sum_int']:.2f} sum|d|_unint={s['sum_unint']:.2f} "
        f"share_int={s['share_int']:.1f}% "
        f"unint_med={s['unint_median'] if s['unint_median'] is None else round(s['unint_median'],2)} "
        f"unint_p95={s['unint_p95'] if s['unint_p95'] is None else round(s['unint_p95'],2)} "
        f"unint_top100_moves={len(un100)}"
    )
    for r in un100:
        print(f"    T100 {r['name']} ({r['key'][0]},{r['role']}) rankA={r['rank_a']} rankB={r['rank_b']} dScore={r['delta']:+.2f} buckets={r['buckets']}")

s = summarize(pooled)
print(
    f"POOLED: affected={s['affected']} intended={s['intended']} unintended={s['unintended']} "
    f"sum|d|_int={s['sum_int']:.2f} sum|d|_unint={s['sum_unint']:.2f} share_int={s['share_int']:.1f}% "
    f"unint_med={round(s['unint_median'],2)} unint_p95={round(s['unint_p95'],2)}"
)
# intended top100 moves too, for context
int100 = t100_moves([r for r in pooled if r["intended"]])
print(f"pooled intended top100 moves: {len(int100)}; pooled unintended top100 moves: {len(t100_moves([r for r in pooled if not r['intended']]))}")

print("\n== top10 unintended by |dScore| (pooled) ==")
for r in sorted([r for r in pooled if not r["intended"]], key=lambda x: -x["abs"])[:10]:
    print(
        f"{r['day']} {r['name']} ({r['key'][0]},{r['role']},{r['level']}) "
        f"A={r['score_a']:.2f}(r{r['rank_a']}) B={r['score_b']:.2f}(r{r['rank_b']}) d={r['delta']:+.2f} "
        f"rel={r['reliability']} bucketsB={r['buckets']} adjA={r['adj_a']} adjB={r['adj_b']} "
        f"floor={r['floor']} lvl_trans={r['level_transition']}"
    )

# ---------------- subgroups ----------------
print("\n== subgroups (pooled) ==")


def band(r):
    ra = r["rank_a"]
    if ra is None:
        return "unranked"
    if ra <= 100:
        return "top-100"
    if ra <= 500:
        return "101-500"
    return "rest"


def group(rows, fn, label):
    from collections import defaultdict

    g = defaultdict(list)
    for r in rows:
        g[fn(r)].append(r)
    print(f"-- by {label} --")
    for kk in sorted(g, key=str):
        s = summarize(g[kk])
        print(
            f"{kk}: affected={s['affected']} intended={s['intended']} unintended={s['unintended']} "
            f"sum_int={s['sum_int']:.2f} sum_unint={s['sum_unint']:.2f} "
            f"share_int={(s['share_int'] if s['share_int'] is None else round(s['share_int'],1))} "
            f"unint_med={(None if s['unint_median'] is None else round(s['unint_median'],2))} "
            f"unint_p95={(None if s['unint_p95'] is None else round(s['unint_p95'],2))}"
        )


group(pooled, lambda r: r["role"], "role")
group(pooled, lambda r: r["level"] or "none", "level")
group(pooled, lambda r: ",".join(r["buckets"]) or "none", "bucket membership (arm B rules)")
group(pooled, lambda r: r["floor"], "continuity_floor_applied (arm B)")
group(pooled, band, "rank band (arm A rank)")

json.dump(
    {"pooled_n": len(pooled)},
    open(f"{SP}/q2_done.json", "w"),
)
