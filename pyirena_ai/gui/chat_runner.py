"""Persistent multi-turn agent runner for the GUI Chat tab.

Unlike :class:`pyirena_ai.gui.runner.GradioRunner` (one-shot fit), the
``ChatRunner`` keeps a single :class:`Agent` + :class:`RunSession` + open
pyirena session alive across many user messages. Each user turn is streamed
via the same ``UIState`` / queue bridge as the one-shot runner — only the
output shape differs (chat mode adds a dialogue list).

Lifecycle:

  1. ``start_session(...)``  → opens the dataset, builds the system prompt
     under the chosen toggles, constructs the agent, seeds a "ready" log
     entry. Streams UI updates while it does so.
  2. ``send(message)``       → appends a user message, runs one LLM-loop
     to completion (tool calls included), streams updates, finishes with
     the assistant text appended to the chat dialogue.
  3. ``request_stop()``      → interrupts the current ``send`` mid-loop.
  4. ``end_session()``       → writes the audit JSON, releases the
     pyirena session.
"""

from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path
from typing import Generator, Optional

from pyirena_ai.config.keyring_io import get_api_key
from pyirena_ai.config.settings import load_settings
from pyirena_ai.core.agent import Agent
from pyirena_ai.core.audit import write_audit_json
from pyirena_ai.core.models import get_model
from pyirena_ai.core.session import RunSession
from pyirena_ai.core.skills import build_system_prompt
from pyirena_ai.core.strategy import load_strategy
from pyirena_ai.core.tools import dispatch
from pyirena_ai.gui.formatting import (
    clean_llm_text,
    params_to_markdown,
    sizes_config_to_markdown,
    token_line,
)
from pyirena_ai.gui.runner import (
    StopFitError,
    UIState,
    _pump_queue,
    build_streaming_agent,
)
from pyirena_ai.llm.pricing import estimate_cost_usd
from pyirena_ai.llm.registry import agent_defaults, build_provider


class ChatRunner:
    """Manages one persistent chat session across many user turns."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._q: queue.Queue[UIState] = queue.Queue()
        self._session: Optional[RunSession] = None
        self._agent: Optional[Agent] = None
        self._state: UIState = UIState(status="idle")
        self._file_path: str = ""
        self._session_params: dict = {}  # Store params for reload_system_prompt()

    # ------------------------------------------------------------------ control

    def request_stop(self) -> None:
        self._stop.set()

    def is_active(self) -> bool:
        return self._agent is not None

    # ------------------------------------------------------------------ session

    def start_session(
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
        model_key: str = "unified_fit",
    ) -> Generator[tuple, None, None]:
        """Open the dataset, build the agent, seed the conversation."""
        self._stop.clear()
        self._state = UIState(status="starting…")

        def push(status: str | None = None) -> None:
            if status:
                self._state.status = status
            self._q.put(self._state.clone())

        t = threading.Thread(
            target=self._do_start,
            args=(file_path, provider_name, model_id, base_url, strategy,
                  user_context, include_strategy, include_skills, show_thinking,
                  push, model_key),
            daemon=True,
        )
        t.start()
        yield from _pump_queue(t, self._q, self._state,
                               to_tuple=lambda s: s.as_chat_tuple())

    def _do_start(
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
        push,
        model_key: str = "unified_fit",
    ) -> None:
        try:
            file_path = file_path.strip().strip("'\"")
            if not file_path:
                self._state.log.append({"role": "assistant", "content": "⚠ No file path provided."})
                push("error: no file")
                return

            settings = load_settings()
            prov_cfg = settings.get(provider_name)
            model_id = model_id or prov_cfg.model
            base_url = base_url or prov_cfg.base_url
            api_key = get_api_key(provider_name)

            provider = build_provider(
                provider_name,
                api_key=api_key,
                model=model_id,
                base_url=base_url,
                enable_thinking=show_thinking,
            )

            try:
                strategy_text = load_strategy(strategy) if include_strategy else ""
            except KeyError as e:
                self._state.log.append({"role": "assistant", "content": f"⚠ {e}"})
                push("error: strategy not found")
                return

            fit_model = get_model(model_key)

            system_prompt = build_system_prompt(
                strategy_text,
                tool_name=fit_model.skill,
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
            self._file_path = file_path
            self._session_params = {
                "strategy": strategy,
                "user_context": user_context,
                "include_strategy": include_strategy,
                "include_skills": include_skills,
                "model_key": model_key,
            }

            # Open the dataset directly (no LLM round-trip — we know the path).
            import time
            t0 = time.monotonic()
            open_result = dispatch("open_dataset", {"file_path": file_path})
            self._session.add_tool_use(
                tool="open_dataset",
                args={"file_path": file_path},
                result=open_result,
                elapsed_s=time.monotonic() - t0,
            )
            if "error" in open_result:
                self._state.log.append({
                    "role": "assistant",
                    "content": f"❌ open_dataset failed: {open_result.get('error')}",
                })
                push("error: open_dataset failed")
                return
            sid = open_result.get("session_id", "")
            n_points = open_result.get("n_points", "?")
            self._session.pyirena_session_id = sid

            prov_defaults = agent_defaults(provider_name)
            self._agent = build_streaming_agent(
                provider=provider,
                system_prompt=system_prompt,
                session=self._session,
                state=self._state,
                push=push,
                stop_event=self._stop,
                show_thinking=show_thinking,
                max_iterations=prov_defaults["max_iterations"],
                max_input_tokens=prov_defaults["max_input_tokens"],
                fit_model=fit_model,
            )

            # Seed the conversation: tell the agent which dataset is open,
            # what tools are available, and that the user will now ask
            # questions. Append as a no-reply user message that the model
            # will see on the first real turn.
            self._agent.messages.append({
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": (
                        f"You are now connected to dataset {file_path!r} "
                        f"(pyirena session_id={sid!r}, n_points={n_points}). "
                        "The user will ask follow-up questions. Use the "
                        "available tools (open_dataset is already done — pass "
                        "the session_id above to subsequent calls). Wait for "
                        "the user's first request before doing anything."
                    ),
                }],
            })
            self._agent.messages.append({
                "role": "assistant",
                "content": [{
                    "type": "text",
                    "text": "Ready — what would you like to do?",
                }],
            })

            toggles = []
            toggles.append(f"strategy={'on' if include_strategy else 'off'}")
            toggles.append(f"skills={'on' if include_skills else 'off'}")
            toggles.append(f"thinking={'on' if show_thinking else 'off'}")
            self._state.log.append({
                "role": "user",
                "content": (
                    f"🟢 Chat session started — provider: **{provider_name}** · "
                    f"model: **{model_id}** · {' · '.join(toggles)}"
                ),
            })
            self._state.log.append({
                "role": "assistant",
                "content": (
                    f"📂 **open_dataset** → session `{sid[:8]}…`  {n_points} pts"
                ),
            })
            self._state.chat_messages.append({
                "role": "assistant",
                "content": (
                    f"Ready — dataset `{Path(file_path).name}` loaded "
                    f"({n_points} points). Ask me anything."
                ),
            })
            push("ready")

        except Exception:
            tb = traceback.format_exc()
            self._state.log.append({
                "role": "assistant",
                "content": f"❌ Error starting session:\n```\n{tb}\n```",
            })
            push("error")

    # ------------------------------------------------------------------ send

    def send(self, user_message: str) -> Generator[tuple, None, None]:
        """Append a user message, run the loop, stream UI updates."""
        self._stop.clear()
        user_message = (user_message or "").strip()
        if not user_message:
            yield self._state.clone().as_chat_tuple()
            return
        if self._agent is None:
            self._state.log.append({
                "role": "assistant",
                "content": "⚠ No active chat session — press *Start session* first.",
            })
            yield self._state.clone().as_chat_tuple()
            return

        self._state.chat_messages.append({"role": "user", "content": user_message})
        self._state.status = "thinking…"
        self._q.put(self._state.clone())

        def push(status: str | None = None) -> None:
            if status:
                self._state.status = status
            self._q.put(self._state.clone())

        t = threading.Thread(
            target=self._do_send,
            args=(user_message, push),
            daemon=True,
        )
        t.start()
        yield from _pump_queue(t, self._q, self._state,
                               to_tuple=lambda s: s.as_chat_tuple())

    def _do_send(self, user_message: str, push) -> None:
        try:
            response = self._agent.continue_chat(user_message)
            reply = clean_llm_text(response.text) or "(no text returned)"
            self._state.chat_messages.append({"role": "assistant", "content": reply})

            cost = estimate_cost_usd(
                self._session.model,
                self._session.input_tokens,
                self._session.output_tokens,
            )
            self._state.token_md = token_line(
                self._session.input_tokens,
                self._session.output_tokens,
                cost,
            )

            # Refresh params (best-effort) so the right column reflects any
            # parameter mutations the agent did this turn.
            sid = self._session.pyirena_session_id
            if sid:
                _model_key = self._session_params.get("model_key", "unified_fit")
                _fit_model = get_model(_model_key)
                pr = dispatch(_fit_model.state_tool, {"session_id": sid})
                if "error" not in pr:
                    if _fit_model.state_tool == "get_sizes_config":
                        self._state.params_md = sizes_config_to_markdown(pr)
                    else:
                        self._state.params_md = params_to_markdown(pr)

            push("ready")
        except StopFitError:
            self._state.chat_messages.append({
                "role": "assistant",
                "content": "⏹ Stopped by user.",
            })
            push("stopped")
        except Exception:
            tb = traceback.format_exc()
            err = f"❌ Error:\n```\n{tb}\n```"
            self._state.chat_messages.append({"role": "assistant", "content": err})
            self._state.log.append({"role": "assistant", "content": err})
            push("error")

    # ------------------------------------------------------------------ reload

    def reload_system_prompt(self) -> str:
        """Reload strategy and skills files, rebuild system prompt.

        Returns a status message. Call this when .md files have changed
        to apply updates without restarting the session.
        """
        if self._agent is None or self._session is None:
            return "⚠ No active session — start a session first."

        try:
            params = self._session_params
            strategy = params.get("strategy", "")
            user_context = params.get("user_context", "")
            include_strategy = params.get("include_strategy", True)
            include_skills = params.get("include_skills", True)
            model_key = params.get("model_key", "unified_fit")

            fit_model = get_model(model_key)
            strategy_text = load_strategy(strategy) if include_strategy else ""
            system_prompt = build_system_prompt(
                strategy_text,
                tool_name=fit_model.skill,
                extra_context=user_context,
                include_strategy=include_strategy,
                include_skills=include_skills,
            )

            self._agent.system_prompt = system_prompt
            self._session.system_prompt = system_prompt
            return f"✓ System prompt reloaded (strategy: {strategy})"
        except KeyError as e:
            return f"⚠ Strategy not found: {e}"
        except Exception as e:
            return f"❌ Error reloading: {e}"

    # ------------------------------------------------------------------ end

    def end_session(self) -> tuple:
        """Write audit, close pyirena session, return final chat tuple."""
        audit_path_str = ""
        if self._session:
            try:
                cost = estimate_cost_usd(
                    self._session.model,
                    self._session.input_tokens,
                    self._session.output_tokens,
                )
                self._session.cost_usd_estimate = cost
                audit_path = _chat_audit_path(Path(self._file_path))
                write_audit_json(self._session, audit_path)
                audit_path_str = str(audit_path)
                self._state.log.append({
                    "role": "assistant",
                    "content": f"📄 Audit trail: `{audit_path}`",
                })
                sid = self._session.pyirena_session_id
                if sid:
                    dispatch("close_session", {"session_id": sid})
            except Exception:
                pass

        self._state.chat_messages.append({
            "role": "assistant",
            "content": (
                f"🔚 Session ended. Audit: `{audit_path_str}`" if audit_path_str
                else "🔚 Session ended."
            ),
        })
        self._state.status = "ended"
        self._agent = None
        self._session = None
        return self._state.clone().as_chat_tuple()


def _chat_audit_path(input_path: Path) -> Path:
    """Audit path for a chat session — sibling folder, distinguishable name."""
    folder = input_path.parent / "pyirena-ai"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{input_path.stem}.chat.audit.json"
