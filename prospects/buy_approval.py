"""Pure standing-approval contract shared by Buy review and new promotion."""
from datetime import datetime


APPROVAL_SCHEMA_VERSION = "1.0.0"
# Standing approval covers the current Buy score/units and promotion policy.
# A broad score or units change needs a reviewed scope decision and new ID.
APPROVAL_SCOPE = "valucast_owned_buys_promotion_v1"


def qualified_approval_receipt(receipt) -> bool:
    if not isinstance(receipt, dict) or set(receipt) != {"schema_version", "origin", "scope", "approved_at"}:
        return False
    if (
        receipt.get("schema_version") != APPROVAL_SCHEMA_VERSION
        or receipt.get("origin") != "explicit_manual_input"
        or receipt.get("scope") != APPROVAL_SCOPE
        or not isinstance(receipt.get("approved_at"), str)
    ):
        return False
    try:
        return datetime.fromisoformat(receipt["approved_at"].replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False
