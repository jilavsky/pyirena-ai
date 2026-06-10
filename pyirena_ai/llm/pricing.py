"""Per-million-token pricing for cost estimation in the audit trail.

Numbers are best-effort and only used to give the user a ballpark cost in
the audit JSON. Lifted and extended from `pyirena/gui/ai_advisor.py:259`.
Update as providers re-price.
"""

from __future__ import annotations

from typing import Optional

# (input $/M tokens, output $/M tokens). Lookup is by case-insensitive
# substring match on the model identifier, so e.g. "claude-opus-4-7-1m"
# still matches "claude-opus-4-7".
_COST_PER_1M: dict[str, tuple[float, float]] = {
    "claude-opus-4-7":           (15.0,  75.0),
    "claude-sonnet-4-6":         ( 3.0,  15.0),
    "claude-haiku-4-5":          ( 0.8,   4.0),
    "gpt-4o":                    ( 2.5,  10.0),
    "gpt-4o-mini":               ( 0.15,  0.60),
    "o3":                        (10.0,  40.0),
    "o4-mini":                   ( 1.1,   4.4),
    # Local models priced at $0 — included so the lookup returns a number
    # (zero) rather than None for LM Studio / Ollama runs.
    "local-model":               ( 0.0,   0.0),
    "llama":                     ( 0.0,   0.0),
    "qwen":                      ( 0.0,   0.0),
    "gemma":                     ( 0.0,   0.0),
    "mistral":                   ( 0.0,   0.0),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    """Return estimated cost in USD, or None if the model isn't in the table."""
    key = model.lower()
    for needle, (ci, co) in _COST_PER_1M.items():
        if needle in key:
            return (input_tokens * ci + output_tokens * co) / 1_000_000
    return None
