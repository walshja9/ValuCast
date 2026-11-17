"""THROWAWAY probe: why is one starter missing after the flip? Prints flags and counts only."""
from scraper.fangraphs import fetch_projections

rows = fetch_projections("steamer", "pit")


def num(row, key):
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


print("rows", len(rows))
print("rows_missing_mlbam", sum(1 for r in rows if not r.get("xMLBAMID")))
print("starters_gs_ge_5_ip_lt_40", sum(1 for r in rows if num(r, "GS") >= 5 and num(r, "IP") < 40))
by_id = [r for r in rows if str(r.get("xMLBAMID") or "").split(".")[0] == "668881"]
by_name = [r for r in rows if "hunter greene" in str(r.get("PlayerName") or "").lower()]
print("greene_rows_by_id", len(by_id), "greene_rows_by_name", len(by_name))
for r in by_name or by_id:
    print(
        "greene mlbam_present", bool(r.get("xMLBAMID")),
        "mlbam_matches", str(r.get("xMLBAMID") or "").split(".")[0] == "668881",
        "ip_ge_40", num(r, "IP") >= 40,
        "ip_gt_0", num(r, "IP") > 0,
        "gs_gt_0", num(r, "GS") > 0,
        "gs_share_ge_half", num(r, "G") > 0 and num(r, "GS") / num(r, "G") >= 0.5,
        "team_present", bool(r.get("Team")),
    )
