"""Print role counts from data/projections/current.json. Counts, names and booleans only: this repo's logs are public."""

import json

CLOSERS = {
    "David Bednar", "Mason Miller", "Edwin Díaz", "Josh Hader", "Devin Williams",
    "Robert Suarez", "Ryan Helsley", "Raisel Iglesias", "Andrés Muñoz", "Jhoan Duran",
    "Pete Fairbanks", "Kenley Jansen", "Aroldis Chapman", "Cade Smith", "Trevor Megill",
}

rows = json.load(open("data/projections/current.json", encoding="utf-8"))
pitchers = [r for r in rows if isinstance((r.get("stats") or {}).get("IP"), (int, float))]
real = [r for r in pitchers if r["stats"]["IP"] >= 20]


def gs(row):
    return row["stats"].get("GS") or 0


def bullpen(row):
    return (row["stats"].get("SV") or 0) >= 3 or (row["stats"].get("HLD") or 0) >= 5


low_start = [r for r in real if 0 < gs(r) < 3]
scored_as_starter = [r for r in low_start if r.get("pool") == "starter"]
print("pitcher rows", len(pitchers), "with IP>=20", len(real))
print("IP>=20 pool counts", {p: sum(1 for r in real if r.get("pool") == p) for p in {r.get("pool") for r in real}})
print("IP>=20 with GS=0", sum(1 for r in real if gs(r) == 0))
print("IP>=100 with GS=0, likely a mislabeled starter", sum(1 for r in real if gs(r) == 0 and r["stats"]["IP"] >= 100))
print("IP>=20 with 0<GS<3", len(low_start), "scored as starter", len(scored_as_starter))
print("IP>=20 with 0<GS<3, bullpen line, scored as starter", sorted(r["name"] for r in scored_as_starter if bullpen(r)))
for row in sorted(pitchers, key=lambda r: r.get("name") or ""):
    if row.get("name") in CLOSERS:
        print(row["name"], "pool", row.get("pool"), "positions", row.get("positions"),
              "0<GS", gs(row) > 0, "IP>=20", row["stats"]["IP"] >= 20, "IP>=40", row["stats"]["IP"] >= 40)
ids = [str((r.get("metadata") or {}).get("mlbam_id", "")) for r in rows]
print("ids blank", sum(1 for i in ids if i in ("", "None")), "ids with a decimal", sum(1 for i in ids if "." in i))
