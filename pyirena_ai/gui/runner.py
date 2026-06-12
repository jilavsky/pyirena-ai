"""Background-thread agent runner with a queue-based streaming bridge to Gradio.

The agent loop is synchronous (blocking LLM calls). Gradio's streaming
requires a Python generator. The bridge:

  1. A `GradioRunner` starts the agent in a `threading.Thread`.
  2. After each tool dispatch or LLM turn, the thread puts a `UIUpdate`
     onto a `queue.Queue`.
  3. The Gradio generator method (`stream`) polls the queue and yields
     the current `UIState` to Gradio after each update.
  4. Pressing **Stop** sets a `threading.Event`; the agent checks it before
     each `send_with_tools` call and raises `StopFitError`.

`UIState` carries exactly the values Gradio needs to update the five output
components: image, parameter-table markdown, chatbot messages, token line,
status text.
"""

from __future__ import annotations

import base64
import queue
import threading
import traceback
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Generator, Optional

from pyirena_ai.config.keyring_io import get_api_key
from pyirena_ai.config.settings import load_settings
from pyirena_ai.core.agent import Agent
from pyirena_ai.core.audit import default_audit_path, write_audit_json
from pyirena_ai.core.session import RunSession
from pyirena_ai.core.skills import build_system_prompt
from pyirena_ai.core.strategy import load_strategy
from pyirena_ai.core.tools import dispatch, is_image_result
from pyirena_ai.gui.formatting import (
    clean_llm_text,
    params_to_markdown,
    thinking_block,
    token_line,
    tool_event_line,
)
from pyirena_ai.llm.pricing import estimate_cost_usd
from pyirena_ai.llm.registry import agent_defaults, build_provider


class StopFitError(Exception):
    pass


# Tools that mutate model state — we re-read and re-render params after these.
_PARAM_CHANGING_TOOLS = {
    "select_model", "set_parameter_value", "set_parameter_bounds",
    "fix_parameter", "free_parameter", "fix_all_except",
    "reset_parameters_to_defaults", "add_unified_level", "remove_unified_level",
    "run_fit",
}


@dataclass
class UIState:
    image:         Any = None                   # PIL Image or None
    params_md:     str = "_Not started_"
    log:           list[dict] = field(default_factory=list)
    token_md:      str = ""
    status:        str = "idle"
    chat_messages: list[dict] = field(default_factory=list)
    """Chat-mode only: the user↔assistant dialogue (separate from `log`,
    which holds tool-call events). Empty in Fit mode."""

    def clone(self) -> "UIState":
        return UIState(
            image=self.image,
            params_md=self.params_md,
            log=list(self.log),
            token_md=self.token_md,
            status=self.status,
            chat_messages=list(self.chat_messages),
        )

    def as_tuple(self) -> tuple:
        return (self.image, self.params_md, self.log, self.token_md, self.status)

    def as_chat_tuple(self) -> tuple:
        return (self.image, self.params_md, self.log, self.token_md,
                self.status, self.chat_messages)


class GradioRunner:
    """Manages one fit run. Create a new instance per Fit button click."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._q: queue.Queue[UIState] = queue.Queue()
        self._session: Optional[RunSession] = None

    def request_stop(self) -> None:
        self._stop.set()

    # -----------------------------------------------------------------------
    # Background thread — runs the agent
    # -----------------------------------------------------------------------

    def _run(
        self,
        file_path: str,
        provider_name: str,
        model_id: str,
        base_url: str,
        strategy: str,
        user_context: str,
        include_strategy: bool,
        include_skills: bool,
        show_thinking: bool,
        state: UIState,
    ) -> None:
        """Runs in a background thread. Mutates `state` and puts copies on the queue."""

        def push(status: str | None = None) -> None:
            if status:
                state.status = status
            self._q.put(state.clone())

        try:
            # Normalize path: strip whitespace and surrounding quotes (users
            # often paste shell paths like '/my data/file.h5' with quotes).
            file_path = file_path.strip().strip("'\"")

            # ---- build provider -------------------------------------------
            settings = load_settings()
            prov_cfg = settings.get(provider_name)
            model_id  = model_id  or prov_cfg.model
            base_url  = base_url  or prov_cfg.base_url
            api_key   = get_api_key(provider_name)

            timeout = 600.0 if provider_name in {"lmstudio", "ollama"} else 120.0
            provider = build_provider(
                provider_name,
                api_key=api_key,
                model=model_id,
                base_url=base_url,
                timeout=timeout,
                enable_thinking=show_thinking,
            )

            # ---- load strategy + skills + user instructions ---------------
            try:
                strategy_text = load_strategy(strategy) if include_strategy else ""
            except KeyError as e:
                state.log.append({"role": "assistant", "content": f"⚠ {e}"})
                push("error: strategy not found")
                return

            system_prompt = build_system_prompt(
                strategy_text,
                tool_name="unified_fit",
                extra_context=user_context,
                include_strategy=include_strategy,
                include_skills=include_skills,
            )

            self._session = RunSession(
                input_file=file_path,
                provider=provider_name,
                model=model_id,
                base_url=base_url,
                strategy=strategy,
                system_prompt=system_prompt,
            )

            prov_defaults = agent_defaults(provider_name)
            agent = build_streaming_agent(
                provider=provider,
                system_prompt=system_prompt,
                session=self._session,
                state=state,
                push=push,
                stop_event=self._stop,
                show_thinking=show_thinking,
                max_iterations=prov_defaults["max_iterations"],
                max_input_tokens=prov_defaults["max_input_tokens"],
            )

            user_prompt = (
                f"Fit the dataset at:\n  {file_path}\n\n"
                f"When done, save the result with save_fit(session_id, output_path=None) "
                f"to overwrite the source file.\n\n"
                "Follow the staged fitting workflow from your system prompt. "
                "Return a plain-English summary as your final message."
            )

            state.log.append({
                "role": "user",
                "content": (
                    f"🚀 Starting fit — provider: **{provider_name}** · "
                    f"model: **{model_id}** · "
                    f"max iterations: **{prov_defaults['max_iterations']}** · "
                    f"input token cap: **{prov_defaults['max_input_tokens']:,}**"
                ),
            })
            push("running")
            final = agent.run(user_prompt)

            if final.text:
                state.log.append({"role": "assistant", "content": clean_llm_text(final.text)})

        except StopFitError:
            state.log.append({"role": "assistant", "content": "⏹ Fit stopped by user."})
            push("stopped")
        except Exception:
            tb = traceback.format_exc()
            state.log.append({"role": "assistant", "content": f"❌ Error:\n```\n{tb}\n```"})
            push("error")
        finally:
            # Always write audit trail
            if self._session:
                try:
                    cost = estimate_cost_usd(
                        self._session.model,
                        self._session.input_tokens,
                        self._session.output_tokens,
                    )
                    self._session.cost_usd_estimate = cost
                    audit_path = default_audit_path(file_path)
                    write_audit_json(self._session, audit_path)
                    state.log.append({
                        "role": "assistant",
                        "content": f"📄 Audit trail: `{audit_path}`",
                    })
                    # Release pyirena session
                    sid = self._session.pyirena_session_id
                    if sid:
                        dispatch("close_session", {"session_id": sid})
                except Exception:
                    pass
            if state.status == "running":
                state.status = "done"
            push()

    # -----------------------------------------------------------------------
    # Generator — called by Gradio event handler
    # -----------------------------------------------------------------------

    def stream(
        self,
        file_path: str,
        provider_name: str,
        model_id: str,
        base_url: str,
        strategy: str,
        user_context: str = "",
        include_strategy: bool = True,
        include_skills: bool = True,
        show_thinking: bool = False,
    ) -> Generator[tuple, None, None]:
        """Start the background thread and yield UIState tuples until done."""
        self._stop.clear()
        state = UIState(status="starting…")

        t = threading.Thread(
            target=self._run,
            args=(file_path, provider_name, model_id, base_url, strategy,
                  user_context, include_strategy, include_skills, show_thinking,
                  state),
            daemon=True,
        )
        t.start()

        yield from _pump_queue(t, self._q, state)


# ---------------------------------------------------------------------------
# Shared helpers — used by GradioRunner and ChatRunner
# ---------------------------------------------------------------------------

def _b64_to_pil(b64: str) -> Any:
    """Convert a base64 PNG string to a PIL Image (lazy import)."""
    from PIL import Image  # noqa: PLC0415
    data = base64.b64decode(b64)
    return Image.open(BytesIO(data))


def build_streaming_agent(
    *,
    provider,
    system_prompt: str,
    session: RunSession,
    state: UIState,
    push,                                      # callable: push(status=None) → None
    stop_event: threading.Event,
    show_thinking: bool,
    max_iterations: int,
    max_input_tokens: int,
) -> Agent:
    """Construct an Agent that streams UIState updates as it runs.

    Behavior added on top of the base Agent:
      * Stop button: each call to provider.send_with_tools first checks
        `stop_event` and raises `StopFitError` if set.
      * Thinking display: when `show_thinking` is True, any `thinking_text`
        on the response is appended to `state.log` as a collapsible block
        before the tool dispatches that follow.
      * Tool instrumentation: after each tool call, append a one-line event
        to `state.log`, refresh the parameter table on state-changing tools,
        capture fit images, and update the token counter.

    Shared by `GradioRunner` (one-shot fit) and `ChatRunner` (multi-turn).
    """

    def on_progress(msg: str) -> None:
        if "calling LLM" in msg:
            state.log.append({"role": "user", "content": f"🤖 {msg}"})
            push()

    agent = Agent(
        provider,
        system_prompt=system_prompt,
        session=session,
        max_iterations=max_iterations,
        max_input_tokens=max_input_tokens,
        on_progress=on_progress,
    )

    # Wrap send_with_tools once, on this provider instance, so both
    # `Agent.run` and `Agent.continue_chat` see the stop check + thinking hook.
    orig_send = provider.send_with_tools

    def wrapped_send(**kw):
        if stop_event.is_set():
            raise StopFitError("Stop requested by user")
        response = orig_send(**kw)
        if show_thinking and response.thinking_text:
            state.log.append({
                "role": "assistant",
                "content": thinking_block(response.thinking_text),
            })
            push()
        return response

    provider.send_with_tools = wrapped_send  # type: ignore[method-assign]

    # Wrap _invoke_tool to push UI updates after each tool dispatch.
    orig_invoke = agent._invoke_tool

    def wrapped_invoke(tc):
        block = orig_invoke(tc)

        last_turn = session.turns[-1]
        result = last_turn.result
        elapsed = last_turn.elapsed_s

        state.log.append({
            "role": "assistant",
            "content": tool_event_line(tc.name, tc.args, result, elapsed),
        })

        if is_image_result(result):
            b64 = result.get("image_base64", "")
            if b64:
                state.image = _b64_to_pil(b64)

        sid = session.pyirena_session_id
        if tc.name in _PARAM_CHANGING_TOOLS and sid:
            pr = dispatch("get_model_parameters", {"session_id": sid})
            state.params_md = params_to_markdown(pr)

        cost = estimate_cost_usd(
            session.model,
            session.input_tokens,
            session.output_tokens,
        )
        state.token_md = token_line(
            session.input_tokens,
            session.output_tokens,
            cost,
        )
        push()
        return block

    agent._invoke_tool = wrapped_invoke  # type: ignore[method-assign]
    return agent


def _pump_queue(
    thread: threading.Thread,
    q: queue.Queue,
    state: UIState,
    to_tuple=lambda s: s.as_tuple(),
) -> Generator[tuple, None, None]:
    """Yield UI tuples from `q` until `thread` exits and the queue drains.

    `to_tuple` lets callers swap between `UIState.as_tuple` (Fit, 5 outputs)
    and `UIState.as_chat_tuple` (Chat, 6 outputs).
    """
    while thread.is_alive() or not q.empty():
        try:
            s = q.get(timeout=0.4)
            yield to_tuple(s)
        except queue.Empty:
            yield to_tuple(state.clone())
    thread.join()
    # Final yield so the very last state is always sent.
    yield to_tuple(state.clone())
