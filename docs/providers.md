# Configuring LLM providers

pyirena-ai ships with four provider slots:

| Provider    | Protocol            | Default model     | Default base URL                | Key needed |
|-------------|---------------------|-------------------|---------------------------------|------------|
| `anthropic` | Anthropic Messages  | `claude-opus-4-7` | (SDK default)                   | yes        |
| `openai`    | OpenAI chat/completions | `gpt-4o`      | `https://api.openai.com/v1`     | yes        |
| `lmstudio`  | OpenAI-compatible   | `local-model`     | `http://localhost:1234/v1`      | no         |
| `ollama`    | OpenAI-compatible   | `llama3.1`        | `http://localhost:11434/v1`     | no         |

`lmstudio`, `ollama`, and `openai` all use the same OpenAI-compatible HTTP
client — only the `base_url` differs. Any server or institutional proxy that
speaks that protocol can therefore be used through one of these slots.

## The config file

Per-user settings live in `~/.pyirena-ai/config.toml` (auto-created on first
run; set the `PYIRENA_AI_HOME` environment variable to relocate the whole
config folder). Each provider section has three keys:

```toml
[provider.lmstudio]
model    = "gemma-3-27b-it"
base_url = "http://localhost:1234/v1"
vision   = true
```

`model` and `base_url` can be overridden per run with `--model-id` and
`--base-url` (CLI) or the corresponding GUI text fields. Check the effective
configuration any time with:

```bash
pyirena-ai providers
```

## The `vision` flag — important for local models

During a fit the agent requests plot images (`get_fit_image`,
`get_sizes_fit_image`, residuals) and *looks at them* to judge the fit. This
visual feedback loop is a core part of the fitting strategies.

- **`vision = true`** — fit images are forwarded to the model (as `image_url`
  content on OpenAI-compatible endpoints; Anthropic always receives images).
- **`vision = false`** — images are replaced with a short text note. The
  agent then works from numerical diagnostics (`get_fit_quality`, χ²,
  residual statistics) only.

Defaults: `true` for `anthropic` and `openai`, **`false` for `lmstudio` and
`ollama`** — because a text-only local model errors out when it receives
image content.

**If your local model accepts images (e.g. the vision-capable Gemma builds
served by LM Studio or Ollama), set `vision = true`.** Without it the model
never sees the fit plots and fitting quality suffers noticeably. If you see
server errors mentioning image or multimodal content right after a
`get_fit_image` call, the loaded model is text-only — set `vision = false`.

Note: only the newest two images are kept in the conversation history; older
ones are replaced with a placeholder to keep prompts small (see
`keep_images` in `core/agent.py`).

## API keys

Keys are stored in the OS keyring under service name `pyirena-ai` (shared
with pyirena's in-GUI AI advisor — a key configured there is picked up
automatically):

```bash
pyirena-ai set-key anthropic     # prompts, input hidden
```

If the `keyring` package is unavailable, keys are read from environment
variables instead: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `LMSTUDIO_API_KEY`,
`OLLAMA_API_KEY`. Local servers usually ignore the key entirely.

Keys are **never** written to `config.toml` or the audit files.

## Notes for small local models (beamline use)

- **Tool count.** By default the agent only exposes the tools relevant to
  the selected fit model (35 for Unified Fit, 27 for Size Distribution,
  instead of the full 51). Small models degrade when offered too many
  tools, so keep this default; `--all-tools` restores the full surface if
  ever needed.
- **Caps.** Local providers get generous limits (150 iterations, 10 M input
  tokens) since they cost nothing; commercial providers are capped at 30
  iterations / 500 k input tokens. Override with `--max-iterations`.
- **Timeouts.** Local endpoints get a 600 s per-turn timeout (large prompts
  on modest hardware are slow); commercial endpoints 120 s.
- **Retries.** Transient failures (connection blips, 429/5xx) are retried
  automatically with backoff on all providers.
- **Reasoning display.** `--show-thinking` shows Anthropic extended thinking
  and Magistral-style `<|channel>` reasoning from local models.

## Using an institutional proxy / different endpoint

No new provider is needed — point an existing slot at the endpoint:

```toml
[provider.openai]
model    = "internal-model-name"
base_url = "https://ai-proxy.example.gov/v1"
```

or per run: `--provider openai --base-url https://... --model-id ...`.

## Adding a genuinely new provider

Only needed for a service that speaks neither the Anthropic nor the
OpenAI-compatible protocol, or that you want as its own named slot. Four
small edits:

1. **`pyirena_ai/llm/registry.py`** — add the name to `PROVIDER_CLASSES`,
   mapping to `OpenAICompatProvider` (or a new `LLMProvider` subclass), and
   to `LOCAL_PROVIDERS` *or* `COMMERCIAL_PROVIDERS` (controls iteration/token
   caps and timeout).
2. **`pyirena_ai/config/settings.py`** — add a `DEFAULT_PROVIDERS` entry
   (`model`, `base_url`, `vision`). Existing config files gain the section
   automatically on next load.
3. **`pyirena_ai/config/keyring_io.py`** — add entries to `KEY_NAMES` and
   `ENV_VARS`.
4. If the protocol is new, implement `LLMProvider.send_with_tools` in a new
   module under `pyirena_ai/llm/` (see `openai_compat.py` for the adapter
   pattern — the agent always speaks Anthropic-shaped content blocks).

A provider implementing a new protocol should honour `supports_vision`
(drop or forward tool-result images) and `enable_thinking` where applicable.
