# Changelog

All notable changes to `pyirena-ai` will be documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed — Size Distribution strategy & skill (broad-distribution fits)
- **Reframed the Size Distribution strategy and skill docs** so the agent treats
  the common case correctly: a **broad size distribution on a low-Q power law +
  high-Q flat background** (precipitates in metals; pores in rocks / minerals /
  solids) is the normal, expected use — not a disqualifier. Removed the "single
  dilute population / must have a Guinier knee" framing that made the agent refuse
  these routine datasets.
- **Suitability handling:** `suggest_sizes_setup`'s `suitable=false` and its
  "multiple knees / several levels" warnings are now advisory. The agent only
  defers to Unified Fit when there is genuinely no signal above background or the
  structure is clearly hierarchical with distinct populations to separate.
- **Q-range guidance:** documented the key rule — fit only where the particle
  signal is clearly above the complex background (I(Q) ≳ 2× background; less if
  weak) and keep the noisy, background-dominated high-Q tail out of the inversion
  even though the background is subtracted.
- **Power-law exponent convention:** fix P = 4 (Porod) for powders / discrete
  particles; let P float between 3 and 4 (never below 3) for solid / bulk
  materials. Added use of the new `flat_background` recommendation as a sanity
  check.

### Added — backend hardening & growth refactor (2026-07, `backend-improvements` branch)
- **Per-model tool filtering** (`core/tools.py:TOOL_GROUPS`,
  `schemas_for_groups`, `FitModel.tool_groups`): the LLM now sees only the
  tools relevant to the selected fit model — 35 tools for Unified Fit,
  27 for Size Distribution, instead of all 51. Small local models (Gemma
  et al.) handle fewer tools markedly better. Unclassified/new pyirena
  tools are always included so nothing silently disappears. CLI flag
  `--all-tools` restores the full surface.
- **Agent hooks** (`core/agent.py:AgentHooks`): first-class
  `should_stop` / `on_response` / `on_tool_end` callbacks replace all
  monkey-patching of `send_with_tools` / `_invoke_tool` in the CLI and
  GUI runners. Stop requests now raise `core.agent.AgentStopped`
  (`gui.runner.StopFitError` kept as an alias).
- **Shared run assembly** (`core/run_setup.py`): `RunConfig` → `build_run()`
  / `finish_run()` now implement the provider/strategy/system-prompt/session
  wiring and the cost/close/audit epilogue once; the CLI `fit` command,
  GUI Fit tab, and GUI Chat tab are thin adapters over it. Local providers
  get the 600 s timeout everywhere (previously GUI-only), and pasted paths
  are quote-stripped everywhere (previously inconsistent).
- **Declarative tool metadata** (`core/tools.py`): `MUTATING_TOOLS` (GUI
  parameter-panel refresh) and `HARVEST_RULES` (session_id / χ² / saved-path
  / seed capture) replace hardcoded tool-name checks scattered across the
  agent and runners. Tests fail loudly when a new pyirena tool is missing
  from the classification tables.
- **Conversation image pruning** (`core/agent.py`, `keep_images`, default 2):
  older fit images are replaced with a text placeholder in the message
  history instead of being re-sent (and re-billed / re-processed) on every
  subsequent LLM call. A progress warning fires at 80 % of the input-token
  budget.
- **Vision on OpenAI-compatible endpoints**: tool-result images are
  re-attached as `image_url` user messages when the per-provider
  `vision = true` config flag is set (new in `config.toml`; defaults:
  anthropic/openai true, lmstudio/ollama false). Previously fit images
  were silently dropped for all OpenAI-compatible providers, disabling
  the visual-feedback loop for local models.
- **CI test workflow** (`.github/workflows/tests.yml`): ruff + pytest on
  Python 3.10–3.13 for every push/PR. Ruff configuration added to
  `pyproject.toml`; codebase is lint-clean.
- New offline test modules: `tests/test_tool_traits_and_filtering.py`,
  `tests/test_agent_hooks_and_pruning.py` (hooks, pruning, harvest,
  filtering, dispatch hardening).

### Changed
- `core/tools.py:dispatch()` never raises: unexpected exceptions inside a
  control function now return a `TOOL_EXCEPTION` error dict (with traceback
  tail) so the model can recover mid-run instead of the whole fit aborting.
- Provider robustness: the Anthropic SDK client and the httpx client are
  created once and reused (connection pooling); the OpenAI-compatible
  provider retries transient failures (connection errors, 408/429/5xx)
  with exponential backoff and honours `Retry-After`; Anthropic uses SDK
  retries (`max_retries=3`). `api.openai.com` requests send
  `max_completion_tokens` (newer models reject `max_tokens`).
- Package version is single-sourced from `pyirena_ai.__version__`
  (`dynamic = ["version"]` in `pyproject.toml`).
- `RunSession.finished_at` is set by `finish_run()` for successful and
  failed runs alike.

### Removed
- Stray `unified_fit_default copy.md` / `copy2.md` strategy backups that
  shipped in the wheel and polluted the strategy list.

### Added
- Initial repository scaffolding: `pyproject.toml`, conda environment file,
  `conda/meta.yaml` recipe, GitHub Actions for tests and PyPI publishing.
- LLM provider abstraction (`pyirena_ai.llm`) with concrete implementations
  for Anthropic and OpenAI-compatible endpoints. The OpenAI-compatible
  client serves OpenAI, LM Studio, and Ollama and supports custom
  `base_url` overrides for proxied institutional endpoints.
- Tool bridge (`pyirena_ai.core.tools`) that wraps the full
  `pyirena.api.control` Unified Fit surface for LLM tool-use.
- Tool-use agent loop (`pyirena_ai.core.agent`) with hard iteration and
  token-budget caps.
- JSON audit-trail format (`pyirena-ai/audit/v1`) written next to the
  fitted HDF5 file.
- CLI entry point `pyirena-ai` with `fit`, `providers`, and `set-key`
  subcommands.
- Fit model registry (`pyirena_ai.core.models`) for multi-model support:
  unified-fit and size-distribution with separate strategy/skill configs.
- GUI chat interface with persistent session state, formatting controls
  (markdown/plain-text), and model selection dropdown.
- Size Distribution skill and strategy files with parameter reference guide
  and inversion interpretation.
- Enhanced CLI and agent with improved CLI argument parsing and agent-level
  strategy/skill loading.

## [0.0.1] — unreleased
First scaffolding release; not yet on PyPI.
