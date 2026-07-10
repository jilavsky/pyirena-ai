"""Offline test of the agent loop using a scripted stub provider.

Confirms:
  * The loop dispatches each tool_use block returned by the provider.
  * `RunSession` accumulates turns and tokens correctly.
  * The loop terminates on `end_turn` and on `max_iterations`.
  * The image-result branch packs an image content block back into the
    conversation history.
"""

from __future__ import annotations

from typing import Any

from pyirena_ai.core.agent import Agent
from pyirena_ai.core.session import RunSession
from pyirena_ai.llm.base import AssistantResponse, LLMProvider, ToolCall, Usage


class ScriptedProvider(LLMProvider):
    """Returns a pre-baked list of AssistantResponses in order."""

    name = "scripted"

    def __init__(self, responses: list[AssistantResponse]):
        super().__init__(api_key="", model="stub", base_url="")
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def send_with_tools(self, *, system, messages, tools, max_tokens=4096):
        self.calls.append({
            "system": system,
            "messages": [m for m in messages],
            "n_tools": len(tools),
        })
        if not self._responses:
            return AssistantResponse(text="(stub exhausted)", stop_reason="end_turn")
        return self._responses.pop(0)


def _resp(text: str = "", calls=None, stop="end_turn", in_tok=10, out_tok=5):
    raw: list[dict] = []
    if text:
        raw.append({"type": "text", "text": text})
    for c in calls or []:
        raw.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.args})
    return AssistantResponse(
        text=text,
        tool_calls=list(calls or []),
        stop_reason=stop,
        usage=Usage(input_tokens=in_tok, output_tokens=out_tok),
        raw_content=raw,
    )


def test_loop_terminates_on_end_turn():
    p = ScriptedProvider([_resp(text="all done", stop="end_turn")])
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=5)

    result = agent.run("hello")

    assert len(p.calls) == 1
    assert result.text == "all done"
    assert s.tool_use_count() == 0
    assert s.input_tokens == 10
    assert s.output_tokens == 5


def test_loop_dispatches_tool_then_terminates():
    """Provider asks for list_available_models, then ends after seeing the result."""
    p = ScriptedProvider([
        _resp(
            calls=[ToolCall(id="t1", name="list_available_models", args={})],
            stop="tool_use",
        ),
        _resp(text="done", stop="end_turn"),
    ])
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=5)

    agent.run("please list models")

    assert s.tool_use_count() == 1
    tool_turn = [t for t in s.turns if t.type == "tool_use"][0]
    assert tool_turn.tool == "list_available_models"
    assert "error" not in tool_turn.result
    # After the tool result is appended, there should be 4 messages:
    # user (initial), assistant (tool_use), user (tool_result), assistant (end).
    assert len(p.calls) == 2


def test_loop_aborts_on_max_iterations():
    """Provider keeps asking for the same tool — loop must give up."""
    forever = ToolCall(id="t1", name="list_available_models", args={})
    p = ScriptedProvider([_resp(calls=[forever], stop="tool_use") for _ in range(20)])
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=3)

    agent.run("keep going")

    assert len(p.calls) == 3
    # An error turn must be recorded.
    assert any(t.type == "error" for t in s.turns)


def test_image_result_becomes_image_content_block(monkeypatch):
    """Dispatch returning an image_base64 result is packed as a vision block."""
    # Replace dispatch with one that returns a fake image regardless of args.
    from pyirena_ai.core import agent as agent_mod

    def fake_dispatch(name, args):
        return {"image_base64": "Zm9v", "format": "png", "width": 32, "height": 16}

    monkeypatch.setattr(agent_mod, "dispatch", fake_dispatch)

    p = ScriptedProvider([
        _resp(
            calls=[ToolCall(id="t1", name="get_fit_image", args={"session_id": "x"})],
            stop="tool_use",
        ),
        _resp(text="ok", stop="end_turn"),
    ])
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=5)

    agent.run("show me the fit")

    # Conversation: user(prompt) → assistant(tool_use) → user(tool_result with image) → assistant(end)
    assert len(agent.messages) == 4
    third = agent.messages[2]
    assert third["role"] == "user"
    blocks = third["content"]
    # tool_result block carries content: [text-meta, image]
    assert blocks[0]["type"] == "tool_result"
    inner = blocks[0]["content"]
    assert any(b.get("type") == "image" for b in inner)
    assert any(b.get("type") == "text" for b in inner)


def test_open_dataset_session_id_captured(monkeypatch):
    """When the agent calls open_dataset, the pyirena session_id is recorded."""
    from pyirena_ai.core import agent as agent_mod

    def fake_dispatch(name, args):
        if name == "open_dataset":
            return {"session_id": "deadbeef", "n_points": 100}
        return {"ok": True}

    monkeypatch.setattr(agent_mod, "dispatch", fake_dispatch)

    p = ScriptedProvider([
        _resp(
            calls=[ToolCall(id="t1", name="open_dataset",
                            args={"file_path": "/x.h5"})],
            stop="tool_use",
        ),
        _resp(text="opened", stop="end_turn"),
    ])
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=5)
    agent.run("open it")

    assert s.pyirena_session_id == "deadbeef"
