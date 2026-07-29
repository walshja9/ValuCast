import json, sys

SP = "/tmp/claude-0/-home-user-ValuCast/f84fd2f2-7e86-57ab-b963-1503c61daf79/scratchpad/eval031"

def strip(obj):
    """Remove excluded nondeterministic/context fields."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("generated_at",):
                continue
            if k == "context_only" and isinstance(v, dict):
                v = {kk: vv for kk, vv in v.items() if kk != "source_ranks"}
            out[k] = strip(v)
        return out
    if isinstance(obj, list):
        return [strip(x) for x in obj]
    return obj

def load(p):
    return strip(json.load(open(p)))

def diff_paths(a, b, path="", out=None, limit=50):
    if out is None:
        out = []
    if len(out) >= limit:
        return out
    if type(a) != type(b):
        out.append((path, "type", type(a).__name__, type(b).__name__))
    elif isinstance(a, dict):
        for k in set(a) | set(b):
            if k not in a:
                out.append((path + "/" + str(k), "only-in-B", None, b[k].__class__.__name__))
            elif k not in b:
                out.append((path + "/" + str(k), "only-in-A", a[k].__class__.__name__, None))
            else:
                diff_paths(a[k], b[k], path + "/" + str(k), out, limit)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append((path, "len", len(a), len(b)))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                diff_paths(x, y, path + f"[{i}]", out, limit)
    elif a != b:
        out.append((path, "value", a, b))
    return out

# 1) determinism: armA 07-25 build1 vs build2
d = diff_paths(load(f"{SP}/boards/armA/2026-07-25.json"), load(f"{SP}/boards/armA/2026-07-25.rebuild2.json"))
print("determinism armA 07-25 rebuild diffs (excl generated_at, context_only.source_ranks):", len(d))
for row in d[:20]:
    print("  ", row)

# 2) served sanity: armB 07-23 rebuild vs served 5e8959d board
d2 = diff_paths(load(f"{SP}/boards/armB/2026-07-23.json"), load(f"{SP}/boards/served-2026-07-23.json"))
print("armB 07-23 rebuild vs served diffs (same exclusions):", len(d2))
for row in d2[:20]:
    print("  ", row)
