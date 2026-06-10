"""Tool-use agent loop.

Wires `LLMProvider` (provider-agnostic) to the `pyirena.api.control` tool
bridge. The conversation history is kept in Anthropic content-block shape
because that is what the provider layer normalizes to.

Safety caps protect against runaway loops:

  * `max_iterations`        — hard cap on `LLM → tool → LLM` round-trips
  * `max_input_tokens`      — cumulative cap on prompt tokens sent
  * Per-iteration check on the safety state before each provider call.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from pyirena_ai.core.session import RunSession
from pyirena_ai.core.tools import (
    TOOL_SCHEMAS,
    dispatch,
    extract_image_base64,
    is_image_result,
)
from pyirena_ai.llm.base import AssistantResponse, LLMProvider, ToolCall


ProgressFn = Callable[[str], None]  # receives short human-readable updates


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        system_prompt: str,
        session: RunSession,
        max_iterations: int = 50,
        max_input_tokens: int = 200_000,
        max_tokens_per_turn: int = 4096,
        on_progress: Optional[ProgressFn] = None,
    ):
        self.provider = provider
        self.system_prompt = system_prompt
        self.session = session
        self.max_iterations = max_iterations
        self.max_input_tokens = max_input_tokens
        self.max_tokens_per_turn = max_tokens_per_turn
        self.on_progress = on_progress or (lambda _msg: None)

        self.messages: list[dict[str, Any]] = []

    def run(self, user_prompt: str) -> AssistantResponse:
        """Drive the conversation until the model stops calling tools."""
        self.messages.append({
            "role": "user",
            "content": [{"type": "text", "text": user_prompt}],
        })

        last_response: AssistantResponse = AssistantResponse(text="", stop_reason="end_turn")

        for iteration in range(self.max_iterations):
            if self.session.input_tokens >= self.max_input_tokens:
                msg = (
                    f"Aborting: cumulative input tokens "
                    f"({self.session.input_tokens}) exceeded cap ({self.max_input_tokens})."
                )
                self.on_progress(msg)
                self.session.add_error(msg)
                break

            self.on_progress(f"iteration {iteration + 1}: calling LLM …")

            response = self.provider.send_with_tools(
                system=self.system_prompt,
                messages=self.messages,
                tools=TOOL_SCHEMAS,
                max_tokens=self.max_tokens_per_turn,
            )
            last_response = response

            self.session.input_tokens  += response.usage.input_tokens
            self.session.output_tokens += response.usage.output_tokens

            if response.text:
                self.session.add_assistant_text(response.text)

            self.messages.append({"role": "assistant", "content": response.raw_content})

            if response.stop_reason != "tool_use" or not response.tool_calls:
                self.on_progress(
                    f"iteration {iteration + 1}: stop_reason={response.stop_reason!r} — done."
                )
                break

            tool_result_blocks = [self._invoke_tool(tc) for tc in response.tool_calls]
            self.messages.append({"role": "user", "content": tool_result_blocks})

        else:
            warn = (
                f"Aborting: hit max_iterations cap of {self.max_iterations} "
                "without an end_turn."
            )
            self.on_progress(warn)
            self.session.add_error(warn)

        return last_response

    def _invoke_tool(self, tc: ToolCall) -> dict[str, Any]:
        self.on_progress(f"  tool: {tc.name}({_short_args(tc.args)})")

        t0 = time.monotonic()
        result = dispatch(tc.name, tc.args)
        elapsed = time.monotonic() - t0

        self.session.add_tool_use(
            tool=tc.name,
            args=tc.args,
            result=result,
            elapsed_s=elapsed,
        )

        if tc.name == "open_dataset" and isinstance(result, dict) and "session_id" in result:
            self.session.pyirena_session_id = result["session_id"]
        if tc.name == "save_fit" and isinstance(result, dict) and "saved_to" in result:
            self.session.saved_to = result["saved_to"]
        if tc.name in ("run_fit", "get_chi_squared") and isinstance(result, dict):
            rcs = result.get("reduced_chi_squared")
            if isinstance(rcs, (int, float)):
                self.session.final_chi_squared = float(rcs)
        if tc.name == "run_fit" and isinstance(result, dict):
            seed = result.get("random_seed")
            if seed is not None:
                self.session.last_random_seed = int(seed)

        return _tool_result_block(tc.id, result)


def _tool_result_block(tool_use_id: str, result: dict) -> dict[str, Any]:
    """Build an Anthropic-shaped tool_result block.

    Image-returning tools embed the PNG as a vision block so the model can
    see the fit. Everything else is sent as a single JSON text block.
    """
    content: list[dict[str, Any]] = []

    if is_image_result(result):
        b64 = extract_image_base64(result)
        meta = {k: v for k, v in result.items() if k != "image_base64"}
        if meta:
            content.append({
                "type": "text",
                "text": _safe_json(meta, fallback=str(meta)),
            })
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": b64,
            },
        })
    else:
        content.append({"type": "text", "text": _safe_json(result, fallback=str(result))})

    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
    }


def _safe_json(obj: Any, *, fallback: str) -> str:
    import json
    try:
        return json.dumps(obj, default=str)
    except (TypeError, ValueError):
        return fallback


def _short_args(args: dict) -> str:
    """Compact one-liner for progress output: trim long values."""
    parts: list[str] = []
    for k, v in (args or {}).items():
        if isinstance(v, str) and len(v) > 40:
            v = v[:37] + "..."
        parts.append(f"{k}={v!r}")
    return ", ".join(parts)
