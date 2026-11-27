"""Write every redraft row for one variant: identities and our values only, no stat lines."""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare_2027_boards import _ascii, redraft_rows  # noqa: E402

rows = redraft_rows(ROOT / "data/projections/current.json")
with Path(sys.argv[1]).open("w", encoding="ascii", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(("mlbam_id", "name", "role", "rank", "value"))
    for row in rows:
        writer.writerow((row["mlbam_id"], _ascii(row["name"]), row["role"], row["rank"], round(row["value"], 2)))
print(len(rows), "redraft rows")
