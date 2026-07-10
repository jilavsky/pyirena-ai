"""OpenAI-compatible chat-completions provider.

One implementation serves OpenAI (https://api.openai.com/v1), LM Studio
(http://localhost:1234/v1), Ollama (http://localhost:11434/v1), and any
internal proxy that speaks the same protocol. The endpoint is set entirely
via `base_url`.

The agent loop sees Anthropic-shaped content blocks at all times. This
provider does two adapters:

  1. *Outgoing*: convert Anthropic-shaped tool schemas and messages into
     OpenAI's `tools=[{"type":"function","function":{...}}]` and
     `messages=[{role, content|tool_calls|tool_call_id}]` shapes.
  2. *Incoming*: convert the OpenAI assistant response (a single message
     with optional `tool_calls`) back into Anthropic-shaped content blocks
     so the agent can echo them as-is in the next turn.
"""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any

import httpx

from pyirena_ai.llm.base import (
    AssistantResponse,
    LLMProvider,
    ToolCall,
    Usage,
)

# Transient failures worth retrying: rate limit, timeout, server errors.
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4          # 1 initial + 3 retries
_BACKOFF_BASE_S = 1.5

# Magistral / other channel-style reasoning models prefix their reply with
# <|channel>thinking text<channel|>. Extract it so the GUI / CLI can display
# the reasoning and the user-visible reply is clean.
_CHANNEL_RE = re.compile(r"<\|channel>(.*?)<channel\|>\s*", flags=re.DOTALL)

# OpenAI o-series reasoning content lands in a separate `reasoning` /
# `reasoning_content` response field (not in `content`) — a future addition
# can read msg.get("reasoning") here when those endpoints are in scope.


class OpenAICompatProvider(LLMProvider):
    """Chat-completions over an OpenAI-compatible HTTP endpoint."""

    name = "openai_compat"

    _client: httpx.Client | None = None  # reused across calls (connection pooling)

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def send_with_tools(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict],
        max_tokens: int = 4096,
    ) -> AssistantResponse:
        if not self.base_url:
            raise RuntimeError(
                f"Provider {self.name!r} requires a base_url "
                "(e.g. https://api.openai.com/v1)."
            )

        oai_tools = [_anthropic_tool_to_openai(t) for t in tools]
        oai_messages = _messages_anthropic_to_openai(
            system, messages, forward_images=self.supports_vision
        )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
        }
        # Newer api.openai.com models reject `max_tokens` in favour of
        # `max_completion_tokens`; local servers and proxies generally still
        # expect `max_tokens`.
        if "api.openai.com" in self.base_url:
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
        if oai_tools:
            payload["tools"] = oai_tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/chat/completions"
        data = self._post_with_retries(url, headers, payload)

        return _openai_response_to_assistant(data)

    def _post_with_retries(self, url: str, headers: dict, payload: dict) -> dict:
        """POST with exponential backoff on transient failures.

        Retries connection/timeout errors and 408/429/5xx responses (a
        single momentary blip should not abort a long fitting run).
        Honours a `Retry-After` header when present. Non-retryable HTTP
        errors raise immediately.
        """
        client = self._get_client()
        last_exc: Exception | None = None

        for attempt in range(_MAX_ATTEMPTS):
            try:
                r = client.post(url, headers=headers, json=payload)
            except httpx.TransportError as e:
                last_exc = e
            else:
                if r.status_code not in _RETRYABLE_STATUS:
                    r.raise_for_status()
                    return r.json()
                last_exc = httpx.HTTPStatusError(
                    f"HTTP {r.status_code} from {url}", request=r.request, response=r,
                )
                retry_after = _parse_retry_after(r.headers.get("retry-after"))
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(retry_after or _backoff_s(attempt))
                    continue
                raise last_exc

            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_backoff_s(attempt))

        raise last_exc  # type: ignore[misc]  # loop always sets it before falling through


def _backoff_s(attempt: int) -> float:
    """Exponential backoff with jitter: ~1.5s, ~3s, ~6s."""
    return _BACKOFF_BASE_S * (2 ** attempt) * (0.5 + random.random())


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Schema adapter
# ---------------------------------------------------------------------------

def _anthropic_tool_to_openai(tool: dict) -> dict:
    """Anthropic tool dict → OpenAI function-tool dict."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
        },
    }


# ---------------------------------------------------------------------------
# Outgoing message adapter
# ---------------------------------------------------------------------------

def _messages_anthropic_to_openai(
    system: str, messages: list[dict], *, forward_images: bool = False,
) -> list[dict]:
    """Anthropic-shaped message list → OpenAI-shaped message list.

    Anthropic interleaves tool_use / tool_result blocks inside assistant /
    user messages; OpenAI splits them into separate `assistant` (with
    `tool_calls`) and `tool` (with `tool_call_id`) messages.

    OpenAI `tool` messages take a plain string, so images inside tool
    results cannot ride along directly. When `forward_images` is True
    (vision-capable endpoint) each tool-result image is re-attached as an
    immediately following `user` message with an `image_url` block, so the
    visual-feedback loop (model inspecting the fit plot) works the same as
    on Anthropic. When False, images are replaced with a placeholder note.
    """
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for block in _as_blocks(content):
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_calls.append({
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {}) or {}),
                        },
                    })
            entry: dict[str, Any] = {"role": "assistant"}
            text_joined = "".join(text_parts).strip()
            entry["content"] = text_joined if text_joined else None
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
            continue

        if role == "user":
            # User turns mix plain text/image with tool_result blocks. Tool
            # results must be emitted as separate {role:"tool"} messages in
            # OpenAI's format.
            user_blocks: list[dict] = []
            for block in _as_blocks(content):
                btype = block.get("type")
                if btype == "tool_result":
                    out.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": _tool_result_to_openai_string(block.get("content")),
                    })
                    if forward_images:
                        image_blocks = _tool_result_images_to_openai(block.get("content"))
                        if image_blocks:
                            out.append({
                                "role": "user",
                                "content": (
                                    [{"type": "text",
                                      "text": "Image returned by the tool call above:"}]
                                    + image_blocks
                                ),
                            })
                elif btype == "text":
                    user_blocks.append({"type": "text", "text": block.get("text", "")})
                elif btype == "image":
                    src = block.get("source", {}) or {}
                    if src.get("type") == "base64":
                        media = src.get("media_type", "image/png")
                        data = src.get("data", "")
                        user_blocks.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{media};base64,{data}"},
                        })
                else:
                    user_blocks.append({"type": "text", "text": json.dumps(block)})
            if user_blocks:
                # If every block is plain text, collapse to a string to keep
                # the request maximally compatible with non-vision endpoints.
                if all(b.get("type") == "text" for b in user_blocks):
                    out.append({
                        "role": "user",
                        "content": "\n".join(b.get("text", "") for b in user_blocks),
                    })
                else:
                    out.append({"role": "user", "content": user_blocks})
            continue

        # Pass through anything unknown.
        out.append(msg)

    return out


def _as_blocks(content: Any) -> list[dict]:
    """Normalize Anthropic message `content` (string or list) into a block list."""
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b if isinstance(b, dict) else {"type": "text", "text": str(b)} for b in content]
    return [{"type": "text", "text": str(content)}]


def _tool_result_images_to_openai(result_content: Any) -> list[dict]:
    """Extract image blocks from Anthropic tool_result content as OpenAI
    `image_url` blocks (data URLs). Empty list if there are none."""
    if not isinstance(result_content, list):
        return []
    images: list[dict] = []
    for block in result_content:
        if not isinstance(block, dict) or block.get("type") != "image":
            continue
        src = block.get("source", {}) or {}
        if src.get("type") == "base64" and src.get("data"):
            media = src.get("media_type", "image/png")
            images.append({
                "type": "image_url",
                "image_url": {"url": f"data:{media};base64,{src['data']}"},
            })
    return images


def _tool_result_to_openai_string(result_content: Any) -> str:
    """Flatten Anthropic tool_result content into a single string for OpenAI.

    Anthropic tool_result.content is a list of {type:text|image,...} blocks.
    OpenAI's `tool` message takes a plain string. Images are noted with a
    placeholder here; on vision-capable endpoints the caller re-attaches
    them as a following user message (see `_messages_anthropic_to_openai`).
    """
    if isinstance(result_content, str):
        return result_content
    if isinstance(result_content, list):
        parts: list[str] = []
        for block in result_content:
            if not isinstance(block, dict):
                parts.append(str(block))
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "image":
                parts.append(
                    "[the tool returned an image — attached as the next "
                    "user message if this endpoint supports vision]"
                )
            else:
                parts.append(json.dumps(block))
        return "\n".join(parts)
    return json.dumps(result_content)


# ---------------------------------------------------------------------------
# Incoming response adapter
# ---------------------------------------------------------------------------

def _openai_response_to_assistant(data: dict) -> AssistantResponse:
    """OpenAI chat-completion response → AssistantResponse with Anthropic content."""
    choices = data.get("choices") or []
    if not choices:
        return AssistantResponse(text="", stop_reason="end_turn")

    choice = choices[0]
    msg = choice.get("message") or {}
    finish_reason = choice.get("finish_reason") or ""

    raw_text = msg.get("content") or ""
    thinking_text, text = _split_channel_thinking(raw_text)
    tool_call_dicts = msg.get("tool_calls") or []

    raw_content: list[dict] = []
    if text:
        # Echo only the cleaned reply back to the model in the next turn;
        # the channel-thinking is per-turn and should not be replayed.
        raw_content.append({"type": "text", "text": text})

    tool_calls: list[ToolCall] = []
    for tc in tool_call_dicts:
        fn = tc.get("function") or {}
        name = fn.get("name", "")
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(ToolCall(id=tc.get("id", ""), name=name, args=args))
        raw_content.append({
            "type": "tool_use",
            "id": tc.get("id", ""),
            "name": name,
            "input": args,
        })

    stop_reason = "tool_use" if tool_calls else _map_finish_reason(finish_reason)

    usage_data = data.get("usage") or {}
    usage = Usage(
        input_tokens=int(usage_data.get("prompt_tokens", 0) or 0),
        output_tokens=int(usage_data.get("completion_tokens", 0) or 0),
    )

    return AssistantResponse(
        text=text,
        tool_calls=tool_calls,
        stop_reason=stop_reason,
        usage=usage,
        raw_content=raw_content,
        thinking_text=thinking_text,
    )


def _split_channel_thinking(raw: str) -> tuple[str, str]:
    """Return (thinking, cleaned_text) for a Magistral-style reply.

    If `raw` contains no channel blocks, returns ("", raw).
    """
    if not raw or "<|channel>" not in raw:
        return "", raw
    thinking = "\n\n".join(m.group(1).strip() for m in _CHANNEL_RE.finditer(raw))
    cleaned = _CHANNEL_RE.sub("", raw).strip()
    return thinking, cleaned


def _map_finish_reason(finish: str) -> str:
    """OpenAI finish_reason → Anthropic stop_reason vocabulary."""
    if finish == "stop":
        return "end_turn"
    if finish == "length":
        return "max_tokens"
    if finish == "tool_calls":
        return "tool_use"
    return finish or "end_turn"
