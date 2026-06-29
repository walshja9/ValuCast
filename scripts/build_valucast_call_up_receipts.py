"""Build the ValuCast-owned permanent call-up receipts artifact."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.call_up_receipts import run_call_up_receipts  # noqa: E402


def main() -> None:
    result = run_call_up_receipts()
    print(
        "ValuCast call-up receipts: "
        f"status={result['status']} "
        f"receipts={result['receipt_count']} "
        f"-> {result['artifact_path']}"
    )
    for row in result["receipts"]:
        print(
            "  - "
            f"{row.get('name')} ({row.get('identity_key')}): "
            f"VC #{row.get('valucast_rank')} vs consensus #{row.get('consensus_rank')} "
            f"+{row.get('divergence')} on {row.get('call_up_date')}"
        )


if __name__ == "__main__":
    main()
