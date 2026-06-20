"""ValuCast-owned LLM scouting writer. Consumes the deterministic repository's
grounding, calls Anthropic to write the read, and runs the ValuCast voice guard.

Offline/CI-safe: returns None when the SDK or API key is absent, so the caller keeps
the deterministic report. ValuCast-owned — no DD prompt / persona / validator.
"""
from __future__ import annotations

import hashlib
import json
import os

from scouting.voice import VOICE_PROMPT, validate_report_text

DEFAULT_MODEL = os.environ.get("VALUCAST_SCOUTING_MODEL", "claude-haiku-4-5-20251001")
MAX_TOKENS = 320
MAX_ATTEMPTS = 2
DEFAULT_TIMEOUT_SECONDS = 20.0


def grounding_hash(grounding: dict) -> str:
    """Stable hash of the grounding so the daily build only re-calls changed reports."""
    blob = json.dumps(grounding, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.blake2s(blob.encode("utf-8"), digest_size=16).hexdigest()


def build_prompt(grounding: dict) -> str:
    """Source-tagged facts only, so the model can't blend samples or invent texture."""
    return (
        "Write the ValuCast read for this player using only these facts:\n\n"
        + json.dumps(grounding, indent=2, sort_keys=True, default=str)
    )


def default_client():
    """An Anthropic client from ANTHROPIC_API_KEY, or None when the SDK or key is
    absent. Build once per run and pass into generate_report to reuse the connection."""
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        return None
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    raw_timeout = os.environ.get("VALUCAST_SCOUTING_LLM_TIMEOUT_SECONDS", "")
    try:
        timeout = max(1.0, float(raw_timeout)) if raw_timeout.strip() else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECONDS
    return anthropic.Anthropic(api_key=key, timeout=timeout)


def _extract_text(response) -> str:
    parts = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()


def generate_report(
    grounding: dict,
    *,
    client=None,
    model: str = DEFAULT_MODEL,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict | None:
    """LLM read + voice guard, or None when no client is available (offline / no key).

    `client` is injectable for tests; default lazily builds an Anthropic client from
    ANTHROPIC_API_KEY (returns None if the SDK or key is missing)."""
    client = client if client is not None else default_client()
    if client is None:
        return None
    attempts = max(1, int(max_attempts or 1))
    last: dict | None = None
    for _ in range(attempts):
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=VOICE_PROMPT,
            messages=[{"role": "user", "content": build_prompt(grounding)}],
        )
        text = _extract_text(response)
        guard = validate_report_text(text, grounding)
        last = {
            "text": text,
            "model": model,
            "valid": guard["ok"],
            "hard_ok": guard["hard_ok"],
            "problems": guard,
        }
        if guard["ok"]:
            return last
    return last
