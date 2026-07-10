"""Offline tests for AgentHooks and conversation image pruning.

Uses the same scripted-provider pattern as test_agent_loop_offline.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from pyirena_ai.core.agent import Agent, AgentHooks, AgentStopped
from pyirena_ai.core.session import RunSession
from pyirena_ai.llm.base import AssistantResponse, LLMProvider, ToolCall, Usage


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, responses: list[AssistantResponse]):
        super().__init__(api_key="", model="stub", base_url="")
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def send_with_tools(self, *, system, messages, tools, max_tokens=4096):
        self.calls.append({"system": system, "n_tools": len(tools)})
        if not self._responses:
            return AssistantResponse(text="(stub exhausted)", stop_reason="end_turn")
        return self._responses.pop(0)


def _resp(text="", calls=None, stop="end_turn", thinking=""):
    raw: list[dict] = []
    if text:
        raw.append({"type": "text", "text": text})
    for c in calls or []:
        raw.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.args})
    return AssistantResponse(
        text=text,
        tool_calls=list(calls or []),
        stop_reason=stop,
        usage=Usage(input_tokens=10, output_tokens=5),
        raw_content=raw,
        thinking_text=thinking,
    )


def _image_tool_script(n_images: int):
    """Provider script: n image-tool calls, then end_turn."""
    script = [
        _resp(calls=[ToolCall(id=f"t{i}", name="get_fit_image",
                              args={"session_id": "x"})], stop="tool_use")
        for i in range(n_images)
    ]
    script.append(_resp(text="done", stop="end_turn"))
    return script


def _patch_image_dispatch(monkeypatch):
    from pyirena_ai.core import agent as agent_mod

    def fake_dispatch(name, args):
        return {"image_base64": "Zm9v", "format": "png", "width": 8, "height": 8}

    monkeypatch.setattr(agent_mod, "dispatch", fake_dispatch)


def _count_images(messages) -> int:
    n = 0
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                for b in block.get("content", []):
                    if isinstance(b, dict) and b.get("type") == "image":
                        n += 1
    return n


# ---------------------------------------------------------------------------
# Image pruning
# ---------------------------------------------------------------------------

def test_old_images_pruned_from_history(monkeypatch):
    _patch_image_dispatch(monkeypatch)
    p = ScriptedProvider(_image_tool_script(4))
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=10, keep_images=2)

    agent.run("show fits")

    assert _count_images(agent.messages) == 2
    # Pruned slots must carry a text placeholder, not vanish.
    placeholders = [
        b
        for msg in agent.messages if isinstance(msg.get("content"), list)
        for block in msg["content"] if isinstance(block, dict) and block.get("type") == "tool_result"
        for b in block.get("content", [])
        if isinstance(b, dict) and b.get("type") == "text" and "removed from history" in b.get("text", "")
    ]
    assert len(placeholders) == 2


def test_latest_image_survives(monkeypatch):
    _patch_image_dispatch(monkeypatch)
    p = ScriptedProvider(_image_tool_script(3))
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=10, keep_images=1)

    agent.run("show fits")

    assert _count_images(agent.messages) == 1
    # The surviving image must be in the LAST tool_result message.
    last_tool_msg = [
        m for m in agent.messages
        if isinstance(m.get("content"), list)
        and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"])
    ][-1]
    inner = last_tool_msg["content"][0]["content"]
    assert any(b.get("type") == "image" for b in inner)


def test_keep_images_default_preserves_behavior(monkeypatch):
    """With <= keep_images images, nothing is pruned (old tests still hold)."""
    _patch_image_dispatch(monkeypatch)
    p = ScriptedProvider(_image_tool_script(2))
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=10)  # default keep=2

    agent.run("show fits")
    assert _count_images(agent.messages) == 2


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

def test_should_stop_raises_agent_stopped():
    p = ScriptedProvider([_resp(text="never seen")])
    s = RunSession(input_file="x")
    agent = Agent(
        p, system_prompt="sys", session=s, max_iterations=5,
        hooks=AgentHooks(should_stop=lambda: True),
    )
    with pytest.raises(AgentStopped):
        agent.run("hello")
    assert p.calls == []  # stopped before any LLM call


def test_on_response_and_on_tool_end_fire(monkeypatch):
    from pyirena_ai.core import agent as agent_mod
    monkeypatch.setattr(agent_mod, "dispatch", lambda name, args: {"ok": True})

    seen_responses: list[str] = []
    seen_tools: list[tuple[str, dict, float]] = []

    hooks = AgentHooks(
        on_response=lambda r: seen_responses.append(r.stop_reason),
        on_tool_end=lambda tc, result, elapsed: seen_tools.append((tc.name, result, elapsed)),
    )

    p = ScriptedProvider([
        _resp(calls=[ToolCall(id="t1", name="list_available_models", args={})], stop="tool_use"),
        _resp(text="done", stop="end_turn"),
    ])
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=5, hooks=hooks)

    agent.run("go")

    assert seen_responses == ["tool_use", "end_turn"]
    assert len(seen_tools) == 1
    assert seen_tools[0][0] == "list_available_models"
    assert seen_tools[0][1] == {"ok": True}


def test_harvest_rules_capture_session_fields(monkeypatch):
    """Declarative harvest replaces the old hardcoded per-tool logic."""
    from pyirena_ai.core import agent as agent_mod

    def fake_dispatch(name, args):
        if name == "open_dataset":
            return {"session_id": "cafe1234", "n_points": 42}
        if name == "run_fit":
            return {"reduced_chi_squared": 1.75, "random_seed": 7}
        return {"ok": True}

    monkeypatch.setattr(agent_mod, "dispatch", fake_dispatch)

    p = ScriptedProvider([
        _resp(calls=[ToolCall(id="t1", name="open_dataset", args={"file_path": "/x.h5"})],
              stop="tool_use"),
        _resp(calls=[ToolCall(id="t2", name="run_fit", args={"session_id": "cafe1234"})],
              stop="tool_use"),
        _resp(text="done", stop="end_turn"),
    ])
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=5)
    agent.run("fit it")

    assert s.pyirena_session_id == "cafe1234"
    assert s.final_chi_squared == 1.75
    assert s.last_random_seed == 7


def test_agent_uses_provided_tool_subset():
    subset = [{"name": "open_dataset", "description": "", "input_schema": {}}]
    p = ScriptedProvider([_resp(text="hi")])
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=5, tools=subset)
    agent.run("hello")
    assert p.calls[0]["n_tools"] == 1
