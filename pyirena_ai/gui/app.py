"""Gradio Blocks layout for the pyirena-ai agent GUI.

Compatible with Gradio 6.x (theme/css moved to launch()).

Two tabs:

  * **Fit**  — one-shot driver: paste a path → press ▶ Fit → watch the
    canned "Fit the dataset at …" prompt run to completion.
  * **Chat** — persistent multi-turn session: open the dataset once, then
    converse with the agent. Useful for probing what each model can see,
    what tools it picks unprompted, and how the strategy / skills layers
    of the system prompt change its behavior.

Both tabs share three toggles:

  * **Include fitting strategy** — drops the staged-workflow markdown
    file from the system prompt when off. Used to test how an agent
    behaves with only tool descriptions + expert skills.
  * **Include expert skills**   — drops the per-tool expert-guidance
    markdown when off.
  * **Show agent thinking**     — for Anthropic Claude models, enables
    extended thinking and renders the reasoning blocks inline. For
    Magistral-family local models served via lmstudio/ollama, extracts
    `<|channel>…<channel|>` reasoning content the model emits anyway.
    Models without any reasoning surface (most OpenAI chat models, plain
    local models) simply show no thinking block.

File input design: a plain path textbox rather than gr.File. Gradio's
file-upload widget copies files to a temp directory that is inaccessible
on macOS (/private/var/folders/…). Using a path textbox means the runner
works directly on the user's actual file, saves the fitted result back
to the same path, and puts the audit JSON in a <data_dir>/pyirena-ai/
subfolder the user can easily reach in Finder or Explorer.

Launch via:
    pyirena-ai gui
or:
    python -m pyirena_ai.gui.app
"""

from __future__ import annotations

from pyirena_ai.config.settings import load_settings
from pyirena_ai.core.strategy import list_strategies
from pyirena_ai.llm.registry import known_providers


def build_app():
    try:
        import gradio as gr  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError(
            "Gradio is not installed. Run: pip install \"pyirena-ai[gui]\""
        ) from e

    from pyirena_ai.gui.chat_runner import ChatRunner
    from pyirena_ai.gui.runner import GradioRunner

    settings = load_settings()
    fit_runner = GradioRunner()

    # -----------------------------------------------------------------------
    # Layout
    # -----------------------------------------------------------------------
    with gr.Blocks(title="pyirena-ai · Unified Fit Agent") as demo:
        gr.Markdown(
            "# pyirena-ai · Unified Fit Agent\n"
            "Paste the path to a NXcanSAS HDF5 file. "
            "The fitted result is saved back to the same file; "
            "the audit log goes to `<data_folder>/pyirena-ai/`."
        )

        # Per-provider memory of (model_id, base_url) text-field values for the
        # current GUI session. Each entry remembers exactly what the user typed
        # while that provider was active, so switching providers restores their
        # last input rather than clearing the field. Empty string = use the
        # default from ~/.pyirena-ai/config.toml. Survives provider switches
        # but not GUI restarts.
        provider_memory = gr.State(
            {p: {"model": "", "base_url": ""} for p in known_providers()}
        )

        with gr.Tabs():
            # ============================================================
            # Tab 1 — Fit (one-shot)
            # ============================================================
            with gr.Tab("Fit"):
                with gr.Row():
                    # ---- Left column — controls ----
                    with gr.Column(scale=1, min_width=300):
                        fit_file_path = gr.Textbox(
                            label="HDF5 file path",
                            placeholder="/path/to/your/scan.h5",
                            info=(
                                "Paste the full path to the NXcanSAS HDF5 file. "
                                "The fit is saved back to this file in-place."
                            ),
                            lines=2,
                        )

                        fit_provider = gr.Dropdown(
                            label="LLM provider",
                            choices=known_providers(),
                            value="anthropic",
                        )
                        fit_model = gr.Textbox(
                            label="Model ID (leave blank for configured default)",
                            placeholder="e.g. claude-opus-4-7",
                        )
                        fit_base_url = gr.Textbox(
                            label="Base URL (leave blank for configured default)",
                            placeholder="https://your-proxy/v1",
                        )
                        fit_strategy = gr.Dropdown(
                            label="Fitting strategy",
                            choices=list_strategies() or ["unified_fit_default"],
                            value="unified_fit_default",
                        )
                        fit_context = gr.Textbox(
                            label="Context for this fit (optional)",
                            placeholder=(
                                "e.g. polymer brush in D₂O, expect 2 levels;\n"
                                "Rg ~50 Å and ~500 Å"
                            ),
                            lines=3,
                            info=(
                                "Sample description or expected structure — appended "
                                "to the system prompt for this run only."
                            ),
                        )

                        fit_inc_strategy = gr.Checkbox(
                            label="Include fitting strategy",
                            value=True,
                            info="When off, the staged workflow / hard rules are dropped from the system prompt.",
                        )
                        fit_inc_skills = gr.Checkbox(
                            label="Include expert skills",
                            value=True,
                            info="When off, the per-tool expert-guidance block is dropped.",
                        )
                        fit_show_thinking = gr.Checkbox(
                            label="Show agent thinking (Anthropic / Magistral)",
                            value=False,
                            info="Enables Anthropic extended thinking; extracts Magistral channel reasoning.",
                        )

                        with gr.Row():
                            fit_btn  = gr.Button("▶ Fit",  variant="primary")
                            fit_stop_btn = gr.Button("⏹ Stop", variant="stop")

                        fit_status = gr.Textbox(
                            label="Status",
                            value="idle",
                            interactive=False,
                            max_lines=1,
                        )

                    # ---- Right column — results ----
                    with gr.Column(scale=3):
                        with gr.Row():
                            fit_image = gr.Image(
                                label="Fit (data + model + residuals)",
                                type="pil",
                                height=520,
                            )
                            fit_params = gr.Markdown(
                                value="_Enter a file path and press ▶ Fit._",
                                label="Parameter table",
                                min_height=300,
                            )

                        fit_log = gr.Chatbot(
                            label="Agent log",
                            height=320,
                            autoscroll=True,
                        )

                        fit_token = gr.Markdown(value="", label="Token / cost")

            # ============================================================
            # Tab 2 — Chat (persistent multi-turn)
            # ============================================================
            with gr.Tab("Chat"):
                # Holds the per-page ChatRunner across button clicks.
                chat_runner_state = gr.State(None)

                with gr.Row():
                    # ---- Left column — controls ----
                    with gr.Column(scale=1, min_width=300):
                        chat_file_path = gr.Textbox(
                            label="HDF5 file path",
                            placeholder="/path/to/your/scan.h5",
                            lines=2,
                        )
                        chat_provider = gr.Dropdown(
                            label="LLM provider",
                            choices=known_providers(),
                            value="anthropic",
                        )
                        chat_model = gr.Textbox(
                            label="Model ID (leave blank for configured default)",
                            placeholder="e.g. claude-opus-4-7",
                        )
                        chat_base_url = gr.Textbox(
                            label="Base URL (leave blank for configured default)",
                            placeholder="https://your-proxy/v1",
                        )
                        chat_strategy = gr.Dropdown(
                            label="Fitting strategy",
                            choices=list_strategies() or ["unified_fit_default"],
                            value="unified_fit_default",
                        )
                        chat_context = gr.Textbox(
                            label="Context for this session (optional)",
                            placeholder="Sample description, instrument, etc.",
                            lines=3,
                        )
                        chat_inc_strategy = gr.Checkbox(
                            label="Include fitting strategy",
                            value=True,
                            info="When off, the staged workflow / hard rules are dropped from the system prompt.",
                        )
                        chat_inc_skills = gr.Checkbox(
                            label="Include expert skills",
                            value=True,
                            info="When off, the per-tool expert-guidance block is dropped.",
                        )
                        chat_show_thinking = gr.Checkbox(
                            label="Show agent thinking (Anthropic / Magistral)",
                            value=False,
                            info="Enables Anthropic extended thinking; extracts Magistral channel reasoning.",
                        )

                        with gr.Row():
                            chat_start_btn = gr.Button("▶ Start session", variant="primary")
                            chat_end_btn   = gr.Button("⏹ End session", variant="stop")

                        chat_stop_btn = gr.Button("⏸ Stop current turn", variant="secondary")
                        chat_status = gr.Textbox(
                            label="Status",
                            value="idle",
                            interactive=False,
                            max_lines=1,
                        )

                    # ---- Right column — conversation + results ----
                    with gr.Column(scale=3):
                        chat_dialogue = gr.Chatbot(
                            label="Conversation",
                            height=380,
                            autoscroll=True,
                            render_markdown=True,
                            sanitize_html=False,    # <details> for thinking
                        )

                        with gr.Row():
                            chat_input = gr.Textbox(
                                label="Your message",
                                placeholder="e.g. show me the data; what do you see?",
                                lines=2,
                                scale=4,
                            )
                            chat_send_btn = gr.Button("Send", variant="primary", scale=1)

                        with gr.Accordion("Tool & state panel", open=True):
                            with gr.Row():
                                chat_image = gr.Image(
                                    label="Most recent image",
                                    type="pil",
                                    height=380,
                                )
                                chat_params = gr.Markdown(
                                    value="_No session yet._",
                                    label="Parameter table",
                                    min_height=200,
                                )
                            chat_log = gr.Chatbot(
                                label="Agent event log (tool calls)",
                                height=200,
                                autoscroll=True,
                                render_markdown=True,
                                sanitize_html=False,
                                )
                            chat_token = gr.Markdown(value="", label="Token / cost")

        # -----------------------------------------------------------------------
        # Events — shared
        # -----------------------------------------------------------------------

        def on_provider_change(name: str, memory: dict):
            """Restore the (model, base_url) values the user last typed for this provider."""
            entry = memory.get(name, {"model": "", "base_url": ""})
            try:
                config_model = settings.get(name).model
            except KeyError:
                config_model = ""
            model_placeholder = f"e.g. {config_model}" if config_model else ""
            return (
                gr.update(value=entry.get("model", ""), placeholder=model_placeholder),
                gr.update(value=entry.get("base_url", "")),
            )

        def remember_model(model_value: str, provider: str, memory: dict):
            memory.setdefault(provider, {"model": "", "base_url": ""})
            memory[provider]["model"] = model_value or ""
            return memory

        def remember_base_url(url_value: str, provider: str, memory: dict):
            memory.setdefault(provider, {"model": "", "base_url": ""})
            memory[provider]["base_url"] = url_value or ""
            return memory

        # Fit-tab provider memory wiring
        fit_provider.change(
            on_provider_change,
            inputs=[fit_provider, provider_memory],
            outputs=[fit_model, fit_base_url],
        )
        fit_model.change(
            remember_model,
            inputs=[fit_model, fit_provider, provider_memory],
            outputs=[provider_memory],
        )
        fit_base_url.change(
            remember_base_url,
            inputs=[fit_base_url, fit_provider, provider_memory],
            outputs=[provider_memory],
        )

        # Chat-tab provider memory wiring (uses the same shared provider_memory state)
        chat_provider.change(
            on_provider_change,
            inputs=[chat_provider, provider_memory],
            outputs=[chat_model, chat_base_url],
        )
        chat_model.change(
            remember_model,
            inputs=[chat_model, chat_provider, provider_memory],
            outputs=[provider_memory],
        )
        chat_base_url.change(
            remember_base_url,
            inputs=[chat_base_url, chat_provider, provider_memory],
            outputs=[provider_memory],
        )

        # -----------------------------------------------------------------------
        # Events — Fit tab
        # -----------------------------------------------------------------------

        def on_fit(file_path, provider, model_id, base_url, strategy,
                   user_context, inc_strategy, inc_skills, show_thinking):
            file_path = (file_path or "").strip()
            if not file_path:
                yield None, "_No file path entered._", [], "", "error: no file"
                return
            for state_tuple in fit_runner.stream(
                file_path, provider, model_id or "", base_url or "",
                strategy, user_context or "",
                include_strategy=inc_strategy,
                include_skills=inc_skills,
                show_thinking=show_thinking,
            ):
                yield state_tuple

        fit_btn.click(
            fn=on_fit,
            inputs=[fit_file_path, fit_provider, fit_model, fit_base_url,
                    fit_strategy, fit_context, fit_inc_strategy, fit_inc_skills,
                    fit_show_thinking],
            outputs=[fit_image, fit_params, fit_log, fit_token, fit_status],
        )
        fit_stop_btn.click(fn=fit_runner.request_stop, inputs=[], outputs=[])

        # -----------------------------------------------------------------------
        # Events — Chat tab
        # -----------------------------------------------------------------------

        def on_chat_start(
            runner, file_path, provider, model_id, base_url, strategy,
            user_context, inc_strategy, inc_skills, show_thinking,
        ):
            # Always create a fresh ChatRunner per Start click — that way
            # repeated Start clicks don't reuse a stale session.
            new_runner = ChatRunner()
            for tup in new_runner.start_session(
                file_path, provider, model_id or "", base_url or "",
                strategy, user_context or "",
                inc_strategy, inc_skills, show_thinking,
            ):
                image, params, log, token, status, chat = tup
                yield image, params, log, token, status, chat, new_runner

        chat_start_btn.click(
            fn=on_chat_start,
            inputs=[chat_runner_state, chat_file_path, chat_provider,
                    chat_model, chat_base_url, chat_strategy, chat_context,
                    chat_inc_strategy, chat_inc_skills, chat_show_thinking],
            outputs=[chat_image, chat_params, chat_log, chat_token,
                     chat_status, chat_dialogue, chat_runner_state],
        )

        def on_chat_send(runner, message):
            if runner is None:
                yield (None, "_No session._", [], "", "error: no session",
                       [{"role": "assistant",
                         "content": "⚠ Start a session first."}],
                       runner, "")
                return
            for tup in runner.send(message):
                image, params, log, token, status, chat = tup
                yield image, params, log, token, status, chat, runner, ""

        chat_send_btn.click(
            fn=on_chat_send,
            inputs=[chat_runner_state, chat_input],
            outputs=[chat_image, chat_params, chat_log, chat_token,
                     chat_status, chat_dialogue, chat_runner_state, chat_input],
        )
        chat_input.submit(
            fn=on_chat_send,
            inputs=[chat_runner_state, chat_input],
            outputs=[chat_image, chat_params, chat_log, chat_token,
                     chat_status, chat_dialogue, chat_runner_state, chat_input],
        )

        def on_chat_stop(runner):
            if runner is not None:
                runner.request_stop()

        chat_stop_btn.click(
            fn=on_chat_stop,
            inputs=[chat_runner_state],
            outputs=[],
        )

        def on_chat_end(runner):
            if runner is None:
                return None, "_No session._", [], "", "idle", [], None
            tup = runner.end_session()
            image, params, log, token, status, chat = tup
            return image, params, log, token, status, chat, None

        chat_end_btn.click(
            fn=on_chat_end,
            inputs=[chat_runner_state],
            outputs=[chat_image, chat_params, chat_log, chat_token,
                     chat_status, chat_dialogue, chat_runner_state],
        )

    return demo


def launch(
    host: str = "127.0.0.1",
    port: int = 7860,
    share: bool = False,
) -> None:
    demo = build_app()
    demo.launch(
        server_name=host,
        server_port=port,
        share=share,
        theme="soft",
    )


if __name__ == "__main__":
    launch()
