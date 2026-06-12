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
import re
from typing import Any

import httpx

# Magistral / other channel-style reasoning models prefix their reply with
# <|channel>thinking text<channel|>. Extract it so the GUI / CLI can display
# the reasoning and the user-visible reply is clean.
_CHANNEL_RE = re.compile(r"<\|channel>(.*?)<channel\|>\s*", flags=re.DOTALL)

# OpenAI o-series reasoning content lands in a separate `reasoning` /
# `reasoning_content` response field (not in `content`) — a future addition
# can read msg.get("reasoning") here when those endpoints are in scope.

from pyirena_ai.llm.base import (
    AssistantResponse,
    LLMProvider,
    ToolCall,
    Usage,
)


class OpenAICompatProvider(LLMProvider):
    """Chat-completions over an OpenAI-compatible HTTP endpoint."""

    name = "openai_compat"

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
        oai_messages = _messages_anthropic_to_openai(system, messages)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "max_tokens": max_tokens,
        }
        if oai_tools:
            payload["tools"] = oai_tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/chat/completions"

        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()

        return _openai_response_to_assistant(data)


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

def _messages_anthropic_to_openai(system: str, messages: list[dict]) -> list[dict]:
    """Anthropic-shaped message list → OpenAI-shaped message list.

    Anthropic interleaves tool_use / tool_result blocks inside assistant /
    user messages; OpenAI splits them into separate `assistant` (with
    `tool_calls`) and `tool` (with `tool_call_id`) messages.
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


def _tool_result_to_openai_string(result_content: Any) -> str:
    """Flatten Anthropic tool_result content into a single string for OpenAI.

    Anthropic tool_result.content is a list of {type:text|image,...} blocks.
    OpenAI's `tool` message takes a plain string. Images embedded in the
    tool result are dropped here with a placeholder; for a vision-aware
    follow-up we would need to re-attach them as a separate user image
    message.
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
                parts.append("[image attachment — not forwarded in this turn]")
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
