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
from pyirena_ai.core.strategy import load_strategy
from pyirena_ai.core.tools import dispatch, is_image_result
from pyirena_ai.gui.formatting import params_to_markdown, token_line, tool_event_line
from pyirena_ai.llm.pricing import estimate_cost_usd
from pyirena_ai.llm.registry import build_provider


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
    image:       Any = None                   # PIL Image or None
    params_md:   str = "_Not started_"
    log:         list[dict] = field(default_factory=list)
    token_md:    str = ""
    status:      str = "idle"

    def clone(self) -> "UIState":
        return UIState(
            image=self.image,
            params_md=self.params_md,
            log=list(self.log),
            token_md=self.token_md,
            status=self.status,
        )

    def as_tuple(self) -> tuple:
        return (self.image, self.params_md, self.log, self.token_md, self.status)


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
        state: UIState,
    ) -> None:
        """Runs in a background thread. Mutates `state` and puts copies on the queue."""

        def push(status: str | None = None) -> None:
            if status:
                state.status = status
            self._q.put(state.clone())

        try:
            # ---- build provider -------------------------------------------
            settings = load_settings()
            prov_cfg = settings.get(provider_name)
            model_id  = model_id  or prov_cfg.model
            base_url  = base_url  or prov_cfg.base_url
            api_key   = get_api_key(provider_name)

            provider = build_provider(
                provider_name,
                api_key=api_key,
                model=model_id,
                base_url=base_url,
            )

            # ---- load strategy -------------------------------------------
            try:
                system_prompt = load_strategy(strategy)
            except KeyError as e:
                state.log.append({"role": "assistant", "content": f"⚠ {e}"})
                push("error: strategy not found")
                return

            self._session = RunSession(
                input_file=file_path,
                provider=provider_name,
                model=model_id,
                base_url=base_url,
                strategy=strategy,
                system_prompt=system_prompt,
            )

            # ---- build a subclass of Agent that:
            #       a) checks stop flag before each LLM call
            #       b) updates UIState after each tool dispatch
            # -----------------------------------------------------------------
            q_ref = self._q
            stop_ev = self._stop

            class StreamingAgent(Agent):
                def run(self_inner, user_prompt: str):
                    # Patch send_with_tools to check stop flag first
                    orig = self_inner.provider.send_with_tools

                    def checked(**kw):
                        if stop_ev.is_set():
                            raise StopFitError("Stop requested by user")
                        return orig(**kw)

                    self_inner.provider.send_with_tools = checked  # type: ignore[method-assign]
                    return super().run(user_prompt)

                def _invoke_tool(self_inner, tc):
                    block = super()._invoke_tool(tc)

                    # Unpack the tool result recorded on the session
                    last_turn = self_inner.session.turns[-1]
                    result = last_turn.result
                    elapsed = last_turn.elapsed_s

                    # Log line
                    line = tool_event_line(tc.name, tc.args, result, elapsed)
                    state.log.append({"role": "assistant", "content": line})

                    # Fit image
                    if is_image_result(result):
                        b64 = result.get("image_base64", "")
                        if b64:
                            state.image = _b64_to_pil(b64)

                    # Parameter table — re-query after state-changing tools
                    sid = self_inner.session.pyirena_session_id
                    if tc.name in _PARAM_CHANGING_TOOLS and sid:
                        pr = dispatch("get_model_parameters", {"session_id": sid})
                        state.params_md = params_to_markdown(pr)

                    # Token counter
                    cost = estimate_cost_usd(
                        self_inner.session.model,
                        self_inner.session.input_tokens,
                        self_inner.session.output_tokens,
                    )
                    state.token_md = token_line(
                        self_inner.session.input_tokens,
                        self_inner.session.output_tokens,
                        cost,
                    )
                    push()
                    return block

            def on_progress(msg: str) -> None:
                if "calling LLM" in msg:
                    state.log.append({"role": "user", "content": f"🤖 {msg}"})
                    push()

            agent = StreamingAgent(
                provider,
                system_prompt=system_prompt,
                session=self._session,
                on_progress=on_progress,
            )

            user_prompt = (
                f"Fit the dataset at:\n  {file_path}\n\n"
                f"When done, save the result with save_fit(session_id, output_path=None) "
                f"to overwrite the source file.\n\n"
                "Follow the staged fitting workflow from your system prompt. "
                "Return a plain-English summary as your final message."
            )

            push("running")
            final = agent.run(user_prompt)

            if final.text:
                state.log.append({"role": "assistant", "content": final.text})

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
    ) -> Generator[tuple, None, None]:
        """Start the background thread and yield UIState tuples until done."""
        self._stop.clear()
        state = UIState(status="starting…")

        t = threading.Thread(
            target=self._run,
            args=(file_path, provider_name, model_id, base_url, strategy, state),
            daemon=True,
        )
        t.start()

        while t.is_alive() or not self._q.empty():
            try:
                s = self._q.get(timeout=0.4)
                yield s.as_tuple()
            except queue.Empty:
                yield state.clone().as_tuple()

        t.join()
        # Final yield to make sure the last state is sent.
        yield state.clone().as_tuple()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _b64_to_pil(b64: str) -> Any:
    """Convert a base64 PNG string to a PIL Image (lazy import)."""
    from PIL import Image  # noqa: PLC0415
    data = base64.b64decode(b64)
    return Image.open(BytesIO(data))
