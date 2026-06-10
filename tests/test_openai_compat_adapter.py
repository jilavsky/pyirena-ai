"""Adapter-only tests for OpenAICompatProvider — no network, no SDK."""

from __future__ import annotations

import json

from pyirena_ai.llm.openai_compat import (
    _anthropic_tool_to_openai,
    _messages_anthropic_to_openai,
    _openai_response_to_assistant,
)


def test_tool_schema_adapter_shapes_function_tool():
    tool = {
        "name": "open_dataset",
        "description": "Open a file.",
        "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]},
    }
    oai = _anthropic_tool_to_openai(tool)
    assert oai["type"] == "function"
    assert oai["function"]["name"] == "open_dataset"
    assert oai["function"]["description"] == "Open a file."
    assert oai["function"]["parameters"]["required"] == ["file_path"]


def test_message_adapter_emits_system_then_user_then_assistant_tool_call_then_tool():
    system = "you are an agent"
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "do the thing"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "calling open"},
                {"type": "tool_use", "id": "t1", "name": "open_dataset",
                 "input": {"file_path": "/x.h5"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": [{"type": "text", "text": "{\"session_id\": \"abc\"}"}]},
            ],
        },
    ]
    oai = _messages_anthropic_to_openai(system, messages)

    roles = [m["role"] for m in oai]
    assert roles == ["system", "user", "assistant", "tool"]

    assistant = oai[2]
    assert assistant["content"] == "calling open"
    assert assistant["tool_calls"][0]["id"] == "t1"
    assert assistant["tool_calls"][0]["function"]["name"] == "open_dataset"
    parsed = json.loads(assistant["tool_calls"][0]["function"]["arguments"])
    assert parsed == {"file_path": "/x.h5"}

    tool_msg = oai[3]
    assert tool_msg["tool_call_id"] == "t1"
    assert "session_id" in tool_msg["content"]


def test_image_block_becomes_image_url():
    messages = [{
        "role": "user",
        "content": [{
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "QUFB"},
        }],
    }]
    oai = _messages_anthropic_to_openai("", messages)
    user = oai[0]
    assert isinstance(user["content"], list)
    assert user["content"][0]["type"] == "image_url"
    assert user["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_response_adapter_with_tool_calls():
    data = {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": "thinking",
                "tool_calls": [{
                    "id": "tc_1",
                    "type": "function",
                    "function": {"name": "open_dataset",
                                 "arguments": "{\"file_path\": \"/x.h5\"}"},
                }],
            },
        }],
        "usage": {"prompt_tokens": 42, "completion_tokens": 7},
    }
    resp = _openai_response_to_assistant(data)
    assert resp.stop_reason == "tool_use"
    assert resp.text == "thinking"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "open_dataset"
    assert resp.tool_calls[0].args == {"file_path": "/x.h5"}
    assert resp.usage.input_tokens == 42
    assert resp.usage.output_tokens == 7

    types = [b.get("type") for b in resp.raw_content]
    assert "text" in types and "tool_use" in types


def test_response_adapter_plain_end_turn():
    data = {
        "choices": [{
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "all done"},
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }
    resp = _openai_response_to_assistant(data)
    assert resp.stop_reason == "end_turn"
    assert resp.text == "all done"
    assert resp.tool_calls == []
