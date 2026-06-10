"""Gradio Blocks layout for the pyirena-ai Unified Fit agent GUI.

Compatible with Gradio 6.x (theme/css moved to launch()).

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

    # One runner instance per Gradio app lifetime.  A new runner is
    # created each time build_app() is called (i.e. each server start).
    runner = GradioRunner()

    # -----------------------------------------------------------------------
    # Layout
    # -----------------------------------------------------------------------
    with gr.Blocks(title="pyirena-ai · Unified Fit Agent") as demo:
        gr.Markdown(
            "# pyirena-ai · Unified Fit Agent\n"
            "Upload a NXcanSAS HDF5 file and let the AI drive the Unified Fit workflow."
        )

        with gr.Row():
            # ---- Left column — controls ----
            with gr.Column(scale=1, min_width=280):
                file_input = gr.File(
                    label="NXcanSAS HDF5 file",
                    file_types=[".h5", ".hdf5"],
                    type="filepath",
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
                    label="Base URL (leave blank for default or configured value)",
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
                    info="Sample description or expected structure. "
                         "Appended to the system prompt for this run only.",
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
                        value="_Select a file and press Fit._",
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

        def on_provider_change(name: str):
            """Populate model-id hint from config when provider changes."""
            try:
                p = settings.get(name)
                return gr.update(placeholder=f"e.g. {p.model}")
            except KeyError:
                return gr.update()

        provider_dd.change(on_provider_change, inputs=provider_dd, outputs=model_txt)

        def on_fit(file_path, provider, model_id, base_url, strategy, user_context):
            if not file_path:
                yield None, "_No file selected._", [], "", "error: no file"
                return
            for state_tuple in runner.stream(
                file_path, provider, model_id or "", base_url or "",
                strategy, user_context or "",
            ):
                yield state_tuple

        fit_btn.click(
            fn=on_fit,
            inputs=[file_input, provider_dd, model_txt, base_url_txt,
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
