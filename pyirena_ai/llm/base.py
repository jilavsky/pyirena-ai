"""Provider-agnostic interface for an LLM that supports tool-use.

The agent loop talks only to `LLMProvider`. Each concrete provider
(Anthropic, OpenAI-compatible, ...) lives in its own module and is only
imported when actually instantiated, so optional SDKs do not become
mandatory dependencies.

The transport-level message shape is a single normalized "conversation",
expressed as a list of `Message` dicts:

    {"role": "user" | "assistant", "content": <list of content blocks>}

Content blocks the agent passes in user turns:

    {"type": "text", "text": "..."}
    {"type": "tool_result", "tool_use_id": "...", "content": [<text|image>]}
    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "<b64>"}}

Content blocks the provider returns (inside `AssistantResponse.raw_content`):

    {"type": "text", "text": "..."}
    {"type": "tool_use", "id": "...", "name": "...", "input": {...}}

Anthropic's native shape is the reference; the OpenAI-compatible provider
adapts to/from this shape internally.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str           # provider's tool-call identifier; echoed back in tool_result
    name: str         # which tool to invoke
    args: dict        # parsed argument object


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens


@dataclass
class AssistantResponse:
    """One round-trip response from the LLM."""

    text: str                                # concatenation of all text blocks
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""                    # "end_turn", "tool_use", "max_tokens", ...
    usage: Usage = field(default_factory=Usage)
    raw_content: list[dict] = field(default_factory=list)
    """Provider's native content-block list, ready to be echoed back as an assistant
    message in the next turn. The agent loop should not introspect this."""


class LLMProvider(ABC):
    """A connection to a single chat-completion endpoint that supports tool use."""

    name: str = ""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "",
        timeout: float = 120.0,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout

    @abstractmethod
    def send_with_tools(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict],
        max_tokens: int = 4096,
    ) -> AssistantResponse:
        """Send one turn and return the assistant response.

        `messages` must be the full conversation so far (all prior user and
        assistant turns). `tools` is the provider-native tool list in
        Anthropic shape; providers that use a different shape adapt internally.
        """
        raise NotImplementedError
