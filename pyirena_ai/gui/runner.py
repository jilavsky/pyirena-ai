"""Background-thread agent runner with a queue-based streaming bridge to Gradio.

The agent loop is synchronous (blocking LLM calls). Gradio's streaming
requires a Python generator. The bridge:

  1. A `GradioRunner` starts the agent in a `threading.Thread`.
  2. After each tool dispatch or LLM turn, the thread puts a `UIUpdate`
     onto a `queue.Queue`.
  3. The Gradio generator method (`stream`) polls the queue and yields
     the current `UIState` to Gradio after each update.
  4. Pressing **Stop** sets a `threading.Event`; the agent's
     `hooks.should_stop` sees it before each LLM call and raises
     `AgentStopped` (aliased here as `StopFitError`).

`UIState` carries exactly the values Gradio needs to update the five output
components: image, parameter-table markdown, chatbot messages, token line,
status text.

All observation of the agent goes through `AgentHooks` (see
`core/agent.py`) — no methods are monkey-patched.
"""

from __future__ import annotations

import base64
import queue
import threading
import traceback
from collections.abc import Generator
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from pyirena_ai.core.agent import Agent, AgentHooks, AgentStopped
from pyirena_ai.core.models import FitModel
from pyirena_ai.core.run_setup import RunConfig, build_run, finish_run
from pyirena_ai.core.session import RunSession
from pyirena_ai.core.tools import MUTATING_TOOLS, dispatch, is_image_result
from pyirena_ai.gui.formatting import (
    clean_llm_text,
    params_to_markdown,
    sizes_config_to_markdown,
    thinking_block,
    token_line,
    tool_event_line,
)
from pyirena_ai.llm.pricing import estimate_cost_usd

# Backwards-compatible alias — the loop now raises core.agent.AgentStopped.
StopFitError = AgentStopped


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

    # NOTE (thread-safety): `clone()` copies the lists but shares the dict
    # entries inside them. This is safe only because entries are append-only
    # and never mutated after being added — keep it that way.
    def clone(self) -> UIState:
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
        self._session: RunSession | None = None

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
        model_key: str = "unified_fit",
    ) -> None:
        """Runs in a background thread. Mutates `state` and puts copies on the queue."""

        def push(status: str | None = None) -> None:
            if status:
                state.status = status
            self._q.put(state.clone())

        try:
            config = RunConfig(
                file_path=file_path,
                provider_name=provider_name,
                model_id=model_id,
                base_url=base_url,
                strategy=strategy,
                model_key=model_key,
                user_context=user_context,
                include_strategy=include_strategy,
                include_skills=include_skills,
                show_thinking=show_thinking,
            )
            try:
                bundle = build_streaming_run(
                    config,
                    state=state,
                    push=push,
                    stop_event=self._stop,
                    show_thinking=show_thinking,
                )
            except KeyError as e:
                state.log.append({"role": "assistant", "content": f"⚠ {e}"})
                push("error: bad configuration")
                return

            self._session = bundle.session

            user_prompt = (
                f"Fit the dataset at:\n  {bundle.session.input_file}\n\n"
                f"When done, save the result with "
                f"{bundle.fit_model.save_tool}(session_id, output_path=None) "
                f"to overwrite the source file.\n\n"
                "Follow the staged fitting workflow from your system prompt. "
                "Return a plain-English summary as your final message."
            )

            state.log.append({
                "role": "user",
                "content": (
                    f"🚀 Starting fit — provider: **{bundle.provider_name}** · "
                    f"model: **{bundle.model_id}** · "
                    f"tools exposed: **{len(bundle.tool_schemas)}** · "
                    f"max iterations: **{bundle.max_iterations}** · "
                    f"input token cap: **{bundle.max_input_tokens:,}**"
                ),
            })
            push("running")
            final = bundle.agent.run(user_prompt)

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
            # Always write audit trail + release the pyirena session.
            if self._session:
                try:
                    audit_path = finish_run(self._session)
                    state.log.append({
                        "role": "assistant",
                        "content": f"📄 Audit trail: `{audit_path}`",
                    })
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
        model_key: str = "unified_fit",
    ) -> Generator[tuple, None, None]:
        """Start the background thread and yield UIState tuples until done."""
        self._stop.clear()
        state = UIState(status="starting…")

        t = threading.Thread(
            target=self._run,
            args=(file_path, provider_name, model_id, base_url, strategy,
                  user_context, include_strategy, include_skills, show_thinking,
                  state, model_key),
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


def make_streaming_hooks(
    *,
    session: RunSession,
    state: UIState,
    push,                                      # callable: push(status=None) → None
    stop_event: threading.Event,
    show_thinking: bool,
    fit_model: FitModel | None = None,
) -> AgentHooks:
    """AgentHooks that stream UIState updates as the agent runs.

    * Stop button: `should_stop` reflects `stop_event`; the loop raises
      `AgentStopped` (`StopFitError`) which the runner catches.
    * Thinking display: when `show_thinking` is True, `thinking_text` is
      appended to `state.log` as a collapsible block.
    * Tool instrumentation: after each tool call, append a one-line event
      to `state.log`, refresh the parameter table on state-changing tools,
      capture fit images, and update the token counter.

    Shared by `GradioRunner` (one-shot fit) and `ChatRunner` (multi-turn).
    """

    def on_response(response) -> None:
        if show_thinking and response.thinking_text:
            state.log.append({
                "role": "assistant",
                "content": thinking_block(response.thinking_text),
            })
            push()

    def on_tool_end(tc, result, elapsed) -> None:
        state.log.append({
            "role": "assistant",
            "content": tool_event_line(tc.name, tc.args, result, elapsed),
        })

        if is_image_result(result):
            b64 = result.get("image_base64", "")
            if b64:
                state.image = _b64_to_pil(b64)

        sid = session.pyirena_session_id
        if tc.name in MUTATING_TOOLS and sid:
            state_tool = (fit_model.state_tool if fit_model else "get_model_parameters")
            pr = dispatch(state_tool, {"session_id": sid})
            if state_tool == "get_sizes_config":
                state.params_md = sizes_config_to_markdown(pr)
            else:
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

    return AgentHooks(
        should_stop=stop_event.is_set,
        on_response=on_response,
        on_tool_end=on_tool_end,
    )


def build_streaming_run(
    config: RunConfig,
    *,
    state: UIState,
    push,
    stop_event: threading.Event,
    show_thinking: bool,
):
    """`core.run_setup.build_run` wired with the streaming GUI hooks.

    Two-step construction because the hooks need the `RunSession` and
    `FitModel`, which `build_run` creates: build once to obtain them, then
    attach hooks to the same agent instance.
    """

    def on_progress(msg: str) -> None:
        if "calling LLM" in msg or msg.startswith("warning:"):
            state.log.append({"role": "user", "content": f"🤖 {msg}"})
            push()

    bundle = build_run(config, on_progress=on_progress)
    bundle.agent.hooks = make_streaming_hooks(
        session=bundle.session,
        state=state,
        push=push,
        stop_event=stop_event,
        show_thinking=show_thinking,
        fit_model=bundle.fit_model,
    )
    return bundle


def attach_streaming_hooks(
    agent: Agent,
    *,
    session: RunSession,
    state: UIState,
    push,
    stop_event: threading.Event,
    show_thinking: bool,
    fit_model: FitModel | None = None,
) -> Agent:
    """Attach streaming hooks to an already-built agent (ChatRunner path)."""
    agent.hooks = make_streaming_hooks(
        session=session,
        state=state,
        push=push,
        stop_event=stop_event,
        show_thinking=show_thinking,
        fit_model=fit_model,
    )
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
