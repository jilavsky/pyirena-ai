# CLAUDE.md

Orientation file for AI agents working in this repository. It tells you *where*
things are and *what rules apply*, not what every function does.

`pyirena-ai` lets an LLM autonomously fit small-angle scattering data using the
analysis machinery in [pyirena](https://github.com/jilavsky/pyirena). It is a
separate, opt-in package — pyirena must never depend on it. Status: alpha.

Scientific correctness outranks agent cleverness. A run that reaches a wrong fit
confidently is worse than one that stops and says it is stuck.

---

## 1. Commands

```bash
pip install -e ".[all]"       # dev install (anthropic + openai + keyring + gui)
pytest                        # full suite (tests/) — offline by default
ruff check pyirena_ai/        # lint (line-length 100)
pyirena-ai --help             # CLI agent
```

Two pytest markers gate the slow/external paths — respect them:

- `requires_pyirena_testdata` — skipped when pyirena's `testData/` isn't reachable
- `requires_llm` — skipped unless a real API key is present (manual smoke tests)

The default suite runs **offline**. Do not add a test that silently needs a
network or a live model.

---

## 2. Architecture

```
cli/  or  gui/          user surface
        │
     core/agent.py      the agent loop
        │
     core/tools.py      ← the ONLY module that imports pyirena
        │
     llm/               provider adapters (anthropic, openai-compatible)
```

| Path | Responsibility |
|---|---|
| `core/agent.py` | The loop: prompt → tool call → harvest → repeat |
| `core/tools.py` | Bridge to `pyirena.api.control`; schemas, dispatch, traits |
| `core/session.py`, `core/models.py` | `RunSession` state and data models |
| `core/strategy.py`, `core/skills.py` | Load the markdown strategy/skill prompts |
| `core/run_setup.py` | Assemble a run from config + dataset |
| `core/audit.py` | Audit trail of every tool call and result |
| `llm/base.py`, `llm/registry.py` | Provider abstraction and lookup |
| `llm/anthropic.py`, `llm/openai_compat.py` | The two adapters |
| `llm/pricing.py` | Token cost accounting |
| `config/settings.py`, `config/keyring_io.py` | Settings; API keys via keyring |
| `config/strategies/*.md`, `config/skills/*.md` | Prompt content, shipped as package data |
| `gui/` | Gradio app (`[gui]` extra) |

### Invariants — do not break these

1. **`core/tools.py` is the single integration point with pyirena.** The agent
   loop never imports `pyirena` directly — it sees only tool names and schemas.
   Verify: `grep -rl "import pyirena" pyirena_ai/` should name `core/tools.py`
   (and `core/run_setup.py` where it opens a dataset) and nothing in `llm/`.
2. **`dispatch` never raises.** Bad arguments from the model and unexpected
   exceptions alike become `{"error", "code", "suggestion"}` so the agent can
   see the failure and recover. Do not let an exception escape it.
3. **Tools are lifted from `pyirena.api.control` unchanged.** Do not reshape or
   rename them here — fix the surface upstream in pyirena instead. Tools pyirena
   adds that aren't yet in `TOOL_GROUPS` are treated as shared, so new
   functionality never silently disappears; keep that fallback.
4. **Trim the tool list per fit model** (`schemas_for_groups`). Small local LLMs
   degrade noticeably when offered too many tools, and local models at the
   beamline are a first-class target — not a fallback.
5. Prompt content lives in markdown under `config/`, never inline in Python.
   It is package data and must stay listed in `pyproject.toml`.

---

## 3. Conventions

**Code.** Python ≥3.10. Line length 100. `ruff` only — **remove `[tool.black]`
if you touch packaging**; the ecosystem standard is `ruff format`. Version is
dynamic from `pyirena_ai.__version__`.

**Scientific.** Q in Å⁻¹, intensity in cm⁻¹ where calibrated. Keep Irena
terminology and pyirena's parameter names exactly — the model is prompted with
them and renaming breaks strategies silently.

**Providers.** Any new provider implements `llm/base.py` and registers in
`llm/registry.py`. Never hardcode a provider in `core/`. API keys come from
keyring or env — never write a key to disk or into the audit trail.

**Testing.** New tool-bridge behaviour needs a test in `tests/`; the offline
agent-loop tests (`test_agent_loop_offline.py`) are the pattern to copy.

---

## 4. Where to look

| If you are… | Read |
|---|---|
| Getting oriented on design intent | `planning/ai-agent/00-overall-plan.md`, `planning/ai-agent/README.md` |
| Working on the tool bridge | `planning/ai-agent/01-api-and-mcp-extensions.md` |
| Working on the standalone app / GUI | `planning/ai-agent/02-standalone-ai-app.md`, `03-ai-advisor-in-gui.md` |
| Adding a fit model to the agent | `planning/ai-agent/phase-1-unified-fit-control.md`, `phase-2-size-distribution.md` |
| Configuring providers / local models | `docs/providers.md` (incl. the `vision` flag) |
| Installing or using | `docs/installation.md`, `docs/usage.md` |

Upstream pyirena's own `CLAUDE.md` describes the api/control layer this package
consumes — read it before changing anything in `core/tools.py`.

---

## 5. Maintaining this file

This is a map, not documentation. Update it when a top-level package appears
under `pyirena_ai/`, when an invariant in §2 changes, or when a command or
pytest marker in §1 changes.
