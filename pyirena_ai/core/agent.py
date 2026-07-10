"""Tool-use agent loop.

Wires `LLMProvider` (provider-agnostic) to the `pyirena.api.control` tool
bridge. The conversation history is kept in Anthropic content-block shape
because that is what the provider layer normalizes to.

Safety caps protect against runaway loops:

  * `max_iterations`        — hard cap on `LLM → tool → LLM` round-trips
  * `max_input_tokens`      — cumulative cap on prompt tokens sent
  * Per-iteration check on the safety state before each provider call.

## Hooks

Frontends observe / steer the loop through `AgentHooks` instead of
monkey-patching methods:

  * `should_stop()`  — checked before each provider call; return True to
    abort the loop (an `AgentStopped` is raised for the caller to catch).
  * `on_response(response)` — after every LLM turn (thinking display, logs).
  * `on_tool_end(tool_call, result, elapsed_s)` — after every tool dispatch
    (UI refresh, image capture, token counters).

## History size control

Fit images are large (~50–100 KB base64 each) and, once embedded in the
conversation, are re-sent — and re-billed — on every subsequent LLM call.
The loop therefore keeps only the most recent `keep_images` images in the
history; older image blocks are rewritten into a short text placeholder.
The audit trail is unaffected (it records/redacts results separately).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pyirena_ai.core.session import RunSession
from pyirena_ai.core.tools import (
    HARVEST_RULES,
    TOOL_SCHEMAS,
    dispatch,
    extract_image_base64,
    is_image_result,
)
from pyirena_ai.llm.base import AssistantResponse, LLMProvider, ToolCall

ProgressFn = Callable[[str], None]  # receives short human-readable updates

_IMAGE_PLACEHOLDER = (
    "[image removed from history to save tokens — superseded by a newer image]"
)


class AgentStopped(Exception):
    """Raised inside the loop when `hooks.should_stop()` returns True."""


@dataclass
class AgentHooks:
    """Optional observer/steering callbacks for the agent loop.

    All fields default to None (no-op). Frontends (CLI, Gradio, future
    batch runner) implement what they need — no monkey-patching required.
    """

    should_stop: Callable[[], bool] | None = None
    on_response: Callable[[AssistantResponse], None] | None = None
    on_tool_end: Callable[[ToolCall, dict, float], None] | None = None


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        system_prompt: str,
        session: RunSession,
        tools: list[dict] | None = None,
        max_iterations: int = 50,
        max_input_tokens: int = 10_000_000,
        max_tokens_per_turn: int = 4096,
        keep_images: int = 2,
        on_progress: ProgressFn | None = None,
        hooks: AgentHooks | None = None,
    ):
        self.provider = provider
        self.system_prompt = system_prompt
        self.session = session
        self.tools = tools if tools is not None else list(TOOL_SCHEMAS)
        self.max_iterations = max_iterations
        self.max_input_tokens = max_input_tokens
        self.max_tokens_per_turn = max_tokens_per_turn
        self.keep_images = max(0, keep_images)
        self.on_progress = on_progress or (lambda _msg: None)
        self.hooks = hooks or AgentHooks()

        self.messages: list[dict[str, Any]] = []
        self._token_warning_sent = False

    def run(self, user_prompt: str) -> AssistantResponse:
        """Drive the conversation until the model stops calling tools."""
        self.messages.append({
            "role": "user",
            "content": [{"type": "text", "text": user_prompt}],
        })
        return self._run_loop()

    def continue_chat(self, user_message: str) -> AssistantResponse:
        """Append a new user message and run one more LLM→tool loop.

        Reuses the existing conversation history and `RunSession` so token
        counts, audit turns, and the open pyirena session_id all accumulate
        across turns. Iteration/token caps apply per call (not reset).
        """
        self.messages.append({
            "role": "user",
            "content": [{"type": "text", "text": user_message}],
        })
        return self._run_loop()

    def _run_loop(self) -> AssistantResponse:
        last_response: AssistantResponse = AssistantResponse(text="", stop_reason="end_turn")

        for iteration in range(self.max_iterations):
            if self.hooks.should_stop and self.hooks.should_stop():
                raise AgentStopped("Stop requested")

            if self.session.input_tokens >= self.max_input_tokens:
                msg = (
                    f"Aborting: cumulative input tokens "
                    f"({self.session.input_tokens}) exceeded cap ({self.max_input_tokens})."
                )
                self.on_progress(msg)
                self.session.add_error(msg)
                break

            if (
                not self._token_warning_sent
                and self.session.input_tokens >= 0.8 * self.max_input_tokens
            ):
                self._token_warning_sent = True
                self.on_progress(
                    f"warning: input-token budget 80% used "
                    f"({self.session.input_tokens:,} of {self.max_input_tokens:,})."
                )

            self.on_progress(f"iteration {iteration + 1}: calling LLM …")

            response = self.provider.send_with_tools(
                system=self.system_prompt,
                messages=self.messages,
                tools=self.tools,
                max_tokens=self.max_tokens_per_turn,
            )
            last_response = response

            self.session.input_tokens  += response.usage.input_tokens
            self.session.output_tokens += response.usage.output_tokens

            if response.thinking_text:
                self.session.add_assistant_text(
                    f"[thinking] {response.thinking_text}"
                )

            if response.text:
                self.session.add_assistant_text(response.text)

            if self.hooks.on_response:
                self.hooks.on_response(response)

            self.messages.append({"role": "assistant", "content": response.raw_content})

            if response.stop_reason != "tool_use" or not response.tool_calls:
                self.on_progress(
                    f"iteration {iteration + 1}: stop_reason={response.stop_reason!r} — done."
                )
                break

            tool_result_blocks = [self._invoke_tool(tc) for tc in response.tool_calls]
            self.messages.append({"role": "user", "content": tool_result_blocks})
            self._prune_old_images()

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

        self._harvest(tc.name, result)

        if self.hooks.on_tool_end:
            self.hooks.on_tool_end(tc, result, elapsed)

        return _tool_result_block(tc.id, result)

    def _harvest(self, tool_name: str, result: Any) -> None:
        """Copy declared result fields onto the RunSession (see HARVEST_RULES)."""
        if not isinstance(result, dict) or "error" in result:
            return
        for result_key, session_attr, cast in HARVEST_RULES.get(tool_name, ()):
            value = result.get(result_key)
            if value is None:
                continue
            try:
                setattr(self.session, session_attr, cast(value))
            except (TypeError, ValueError):
                pass

    def _prune_old_images(self) -> None:
        """Keep only the newest `keep_images` images in the conversation.

        Older image blocks inside tool_result content are replaced with a
        text placeholder so the model is told an image existed, without the
        ~50–100 KB base64 payload being re-sent on every subsequent call.
        """
        image_refs: list[tuple[list, int]] = []  # (containing content list, index)
        for msg in self.messages:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                inner = block.get("content")
                if not isinstance(inner, list):
                    continue
                for i, b in enumerate(inner):
                    if isinstance(b, dict) and b.get("type") == "image":
                        image_refs.append((inner, i))

        excess = len(image_refs) - self.keep_images
        for inner, i in image_refs[:max(0, excess)]:
            inner[i] = {"type": "text", "text": _IMAGE_PLACEHOLDER}


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
