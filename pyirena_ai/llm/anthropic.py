"""Anthropic provider (uses the official `anthropic` SDK).

`anthropic` is an optional dependency — install with `pip install
"pyirena-ai[anthropic]"`. The SDK is imported lazily inside `send_with_tools`
so the rest of the package keeps working when it is not installed.

Tool schemas from `pyirena.api.control.schemas.TOOL_SCHEMAS` are already
shaped for the Anthropic API and are passed through unchanged.
"""

from __future__ import annotations

from typing import Any

from pyirena_ai.llm.base import (
    AssistantResponse,
    LLMProvider,
    ToolCall,
    Usage,
)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    _client = None  # lazily created, then reused across calls (connection pooling)

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic  # noqa: PLC0415
            except ImportError as e:
                raise RuntimeError(
                    "The 'anthropic' package is not installed. "
                    "Install with: pip install \"pyirena-ai[anthropic]\""
                ) from e
            client_kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "timeout": self.timeout,
                # SDK-level retry with backoff for transient failures
                # (connection errors, 408/429/5xx).
                "max_retries": 3,
            }
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self._client = anthropic.Anthropic(**client_kwargs)
        return self._client

    def send_with_tools(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict],
        max_tokens: int = 4096,
    ) -> AssistantResponse:
        client = self._get_client()

        create_kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "tools": tools,
            "messages": messages,
        }
        if self.enable_thinking:
            # Extended thinking: budget_tokens must be < max_tokens. Force
            # temperature=1 (required); top_p/top_k are not set elsewhere.
            budget = min(2048, max(512, max_tokens - 512))
            create_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            create_kwargs["temperature"] = 1.0

        response = client.messages.create(**create_kwargs)

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        raw_content: list[dict] = []

        for block in response.content:
            block_dict = block.model_dump() if hasattr(block, "model_dump") else dict(block)
            raw_content.append(block_dict)
            btype = block_dict.get("type")
            if btype == "text":
                text_parts.append(block_dict.get("text", ""))
            elif btype == "thinking":
                thinking_parts.append(block_dict.get("thinking", ""))
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block_dict.get("id", ""),
                        name=block_dict.get("name", ""),
                        args=block_dict.get("input", {}) or {},
                    )
                )

        return AssistantResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason or "",
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            raw_content=raw_content,
            thinking_text="\n\n".join(p for p in thinking_parts if p),
        )
