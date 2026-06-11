"""Gradio Blocks layout for the pyirena-ai Unified Fit agent GUI.

Compatible with Gradio 6.x (theme/css moved to launch()).

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

    from pyirena_ai.gui.runner import GradioRunner

    settings = load_settings()
    runner = GradioRunner()

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

        with gr.Row():
            # ---- Left column — controls ----
            with gr.Column(scale=1, min_width=300):
                file_path_txt = gr.Textbox(
                    label="HDF5 file path",
                    placeholder="/path/to/your/scan.h5",
                    info=(
                        "Paste the full path to the NXcanSAS HDF5 file. "
                        "The fit is saved back to this file in-place."
                    ),
                    lines=2,
                )

                provider_dd = gr.Dropdown(
                    label="LLM provider",
                    choices=known_providers(),
                    value="anthropic",
                )
                model_txt = gr.Textbox(
                    label="Model ID (leave blank for configured default)",
                    placeholder="e.g. claude-opus-4-7",
                )
                base_url_txt = gr.Textbox(
                    label="Base URL (leave blank for configured default)",
                    placeholder="https://your-proxy/v1",
                )
                strategy_dd = gr.Dropdown(
                    label="Fitting strategy",
                    choices=list_strategies() or ["unified_fit_default"],
                    value="unified_fit_default",
                )
                context_txt = gr.Textbox(
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

                with gr.Row():
                    fit_btn  = gr.Button("▶ Fit",  variant="primary")
                    stop_btn = gr.Button("⏹ Stop", variant="stop")

                status_txt = gr.Textbox(
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
                    params_md = gr.Markdown(
                        value="_Enter a file path and press ▶ Fit._",
                        label="Parameter table",
                        min_height=300,
                    )

                log_bot = gr.Chatbot(
                    label="Agent log",
                    height=320,
                    autoscroll=True,
                )

                token_md = gr.Markdown(value="", label="Token / cost")

        # -----------------------------------------------------------------------
        # Events
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

        provider_dd.change(
            on_provider_change,
            inputs=[provider_dd, provider_memory],
            outputs=[model_txt, base_url_txt],
        )

        def remember_model(model_value: str, provider: str, memory: dict):
            memory.setdefault(provider, {"model": "", "base_url": ""})
            memory[provider]["model"] = model_value or ""
            return memory

        def remember_base_url(url_value: str, provider: str, memory: dict):
            memory.setdefault(provider, {"model": "", "base_url": ""})
            memory[provider]["base_url"] = url_value or ""
            return memory

        model_txt.change(
            remember_model,
            inputs=[model_txt, provider_dd, provider_memory],
            outputs=[provider_memory],
        )
        base_url_txt.change(
            remember_base_url,
            inputs=[base_url_txt, provider_dd, provider_memory],
            outputs=[provider_memory],
        )

        def on_fit(file_path, provider, model_id, base_url, strategy, user_context):
            file_path = (file_path or "").strip()
            if not file_path:
                yield None, "_No file path entered._", [], "", "error: no file"
                return
            for state_tuple in runner.stream(
                file_path, provider, model_id or "", base_url or "",
                strategy, user_context or "",
            ):
                yield state_tuple

        fit_btn.click(
            fn=on_fit,
            inputs=[file_path_txt, provider_dd, model_txt, base_url_txt,
                    strategy_dd, context_txt],
            outputs=[fit_image, params_md, log_bot, token_md, status_txt],
        )

        stop_btn.click(fn=runner.request_stop, inputs=[], outputs=[])

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
