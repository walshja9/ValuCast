"""Build the two-sided gaps claim lifecycle ledger (offline, deterministic).

Every row that qualifies on either side of the /gaps board becomes a dated claim
that must resolve or expire. Append-only: terminal outcomes on the committed
artifact are kept verbatim; only open + newly enrolled claims are re-resolved.

Run: python scripts/build_gaps_claim_ledger.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.gaps_claim_ledger import run  # noqa: E402


def main() -> int:
    result = run()
    print(
        f"gaps claim ledger: status={result['status']} "
        f"higher={result['higher_total']} lower={result['lower_total']} "
        f"(open={result['open']} callup={result['resolved_by_callup']} "
        f"consensus_move={result['resolved_by_consensus_move']} "
        f"model_retract={result['retracted_by_model_move']} "
        f"expired={result['expired_unresolved']}) "
        f"archived={result['archived']} -> {result['artifact_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
