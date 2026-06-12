"""Offline tests for the chat-continuation path and prompt toggles.

Mirrors `tests/test_agent_loop_offline.py` (uses the same scripted-provider
pattern), and adds coverage for:

  * `Agent.continue_chat` reusing the same instance across turns
  * thinking_text round-tripping through AssistantResponse
  * `build_system_prompt(include_strategy=False, include_skills=False)`
"""

from __future__ import annotations

from typing import Any

from pyirena_ai.core.agent import Agent
from pyirena_ai.core.session import RunSession
from pyirena_ai.core.skills import build_system_prompt
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


def _resp(text="", calls=None, stop="end_turn", in_tok=10, out_tok=5, thinking=""):
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
        thinking_text=thinking,
    )


# ---------------------------------------------------------------------------
# continue_chat round-trip
# ---------------------------------------------------------------------------

def test_continue_chat_reuses_agent_and_grows_messages():
    """run() + continue_chat() share state and grow the message history."""
    p = ScriptedProvider([
        _resp(text="first reply", stop="end_turn"),
        _resp(text="second reply", stop="end_turn"),
    ])
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=5)

    r1 = agent.run("hello")
    assert r1.text == "first reply"
    # After first turn: user(hello) + assistant(first reply)
    assert len(agent.messages) == 2
    assert agent.messages[0]["role"] == "user"
    assert agent.messages[1]["role"] == "assistant"

    r2 = agent.continue_chat("follow-up")
    assert r2.text == "second reply"
    # After second turn: + user(follow-up) + assistant(second reply)
    assert len(agent.messages) == 4
    assert agent.messages[2]["role"] == "user"
    assert agent.messages[3]["role"] == "assistant"

    # Tokens accumulate across both turns.
    assert s.input_tokens == 20
    assert s.output_tokens == 10


def test_continue_chat_runs_tool_use_mid_conversation(monkeypatch):
    """continue_chat handles a tool call on the follow-up turn."""
    from pyirena_ai.core import agent as agent_mod

    dispatched: list[str] = []

    def fake_dispatch(name, args):
        dispatched.append(name)
        return {"ok": True}

    monkeypatch.setattr(agent_mod, "dispatch", fake_dispatch)

    p = ScriptedProvider([
        _resp(text="hi", stop="end_turn"),
        _resp(
            calls=[ToolCall(id="t1", name="list_available_models", args={})],
            stop="tool_use",
        ),
        _resp(text="done after tool", stop="end_turn"),
    ])
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=5)

    agent.run("greet me")
    assert dispatched == []

    agent.continue_chat("now use a tool")
    assert dispatched == ["list_available_models"]
    assert s.tool_use_count() == 1
    # Final message is assistant("done after tool").
    assert agent.messages[-1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# thinking_text propagation
# ---------------------------------------------------------------------------

def test_thinking_text_surfaces_in_response_and_audit():
    """Provider that returns thinking_text → response carries it; session logs it."""
    p = ScriptedProvider([
        _resp(text="visible reply", thinking="I considered X then Y", stop="end_turn"),
    ])
    s = RunSession(input_file="x")
    agent = Agent(p, system_prompt="sys", session=s, max_iterations=5)

    r = agent.run("question")
    assert r.thinking_text == "I considered X then Y"

    # The agent records thinking as an "assistant_text" turn with a tag,
    # before the visible-text turn.
    thinking_turns = [t for t in s.turns if "[thinking]" in t.text]
    assert len(thinking_turns) == 1
    assert "I considered X then Y" in thinking_turns[0].text


# ---------------------------------------------------------------------------
# build_system_prompt toggles
# ---------------------------------------------------------------------------

def test_build_system_prompt_drops_strategy_when_off():
    strategy_text = "## STRATEGY MARKER\nDo the staged workflow."
    sp = build_system_prompt(strategy_text, include_strategy=False, include_skills=False)
    assert "STRATEGY MARKER" not in sp
    assert "Expert fitting guidance" not in sp


def test_build_system_prompt_drops_skills_when_off(tmp_path, monkeypatch):
    """include_skills=False suppresses the bundled per-tool guidance block."""
    strategy_text = "## STRATEGY MARKER"
    sp = build_system_prompt(strategy_text, include_skills=False)
    assert "STRATEGY MARKER" in sp
    assert "Expert fitting guidance" not in sp


def test_build_system_prompt_keeps_extra_context_with_both_off():
    strategy_text = "## STRATEGY MARKER"
    sp = build_system_prompt(
        strategy_text,
        extra_context="my sample is silica in water",
        include_strategy=False,
        include_skills=False,
    )
    assert "STRATEGY MARKER" not in sp
    assert "Expert fitting guidance" not in sp
    assert "silica in water" in sp
