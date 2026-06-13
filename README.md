# pyirena-ai

**AI-driven SAXS/USAXS fitting on top of [pyirena](https://github.com/jilavsky/pyirena).**

Status: **alpha — Phase 1–3 complete, Phase 4 in progress**

`pyirena-ai` is a separate, opt-in package that lets a large language model
autonomously fit small-angle scattering datasets using the analysis machinery
that ships with `pyirena`. Phase 1 covers Unified Fit (Beaucage) through a
command-line agent loop; future phases add a GUI, folder/batch mode, and
support for more pyirena models.

See [planning/ai-agent/](planning/ai-agent/) for the full design.

---

## What it does today (Phase 1)

```
$ pyirena-ai fit my_scan.h5
```

- Opens a NXcanSAS HDF5 file
- Runs a tool-use agent loop that drives `pyirena.api.control` (Unified Fit)
- Picks a fitting strategy (background → Rg + G → power-law → extra level)
- Writes the result back to HDF5
- Emits a JSON audit trail (`my_scan.audit.json`) listing every tool call,
  intermediate result, token usage, and estimated cost

Supports four LLM providers, all with custom `base_url` (for institutional
proxy endpoints):

| Provider  | Default base URL                       |
|-----------|----------------------------------------|
| anthropic | `https://api.anthropic.com`            |
| openai    | `https://api.openai.com/v1`            |
| lmstudio  | `http://localhost:1234/v1`             |
| ollama    | `http://localhost:11434/v1`            |

---

## Installation

### From PyPI (when published)

```bash
pip install pyirena-ai[anthropic]      # or [openai], or [all]
```

### From GitHub (current)

```bash
pip install "pyirena-ai[anthropic] @ git+https://github.com/jilavsky/pyirena-ai.git"
```

### Conda (development)

```bash
git clone https://github.com/jilavsky/pyirena-ai.git
cd pyirena-ai
conda env create -f environment.yml
conda activate pyirena-ai
```

`pyirena-ai` requires Python 3.10+ and depends on `pyirena>=0.8.2`.

---

## Quick start

```bash
# 1. Store your API key (uses the OS keyring; shared with pyirena's in-GUI AI advisor)
pyirena-ai set-key anthropic

# 2. List configured providers and their endpoints
pyirena-ai providers

# 3. Fit a NXcanSAS HDF5 file
pyirena-ai fit path/to/data.h5 --provider anthropic --verbose
```

Useful flags:

```
--provider anthropic|openai|lmstudio|ollama
--model-id MODEL          LLM model (e.g. claude-opus-4-7, gpt-4o)
--base-url URL            Override default endpoint (Argonne / proxied users)
--audit-out PATH          Audit-trail JSON path (default: <input>.audit.json)
--save-out PATH           Where to save fitted HDF5 (default: overwrites input)
```

---

## Configuration

Per-user config lives in `~/.pyirena-ai/config.toml` (auto-created on first
run). Example:

```toml
[provider.anthropic]
model    = "claude-opus-4-7"
base_url = ""                                    # default

[provider.openai]
model    = "gpt-4o"
base_url = "https://api.openai.com/v1"

[provider.lmstudio]
model    = "local-model"
base_url = "http://localhost:1234/v1"

[provider.ollama]
model    = "llama3.1"
base_url = "http://localhost:11434/v1"
```

API keys are stored in the OS keyring under service name `pyirena-ai` — the
same store used by `pyirena`'s in-GUI AI advisor, so if you've already
configured a key there, this tool picks it up automatically.

---

## Status and roadmap

| Phase | Scope | State |
|-------|-------|-------|
| 1 | Headless CLI, single file, Unified Fit, 4 providers, audit trail | ✅ done |
| 2 | Gradio GUI — Fit tab (one-shot), Chat tab (multi-turn), provider/model switching | ✅ done |
| 3 | Strategy + skills system (markdown-based, runtime-reloadable), extended thinking support | ✅ done |
| 4 | Local model support (LMStudio/Ollama, vision, tool-use, long timeouts), UX polish | in progress |
| 5 | Folder/batch mode + watcher | planned |
| 6 | Distribution polish (PyPI packaging, cost guardrails, broader model testing) | planned |

See [planning/ai-agent/02-standalone-ai-app.md](planning/ai-agent/02-standalone-ai-app.md)
for full detail and [planning/ai-agent/00-overall-plan.md](planning/ai-agent/00-overall-plan.md)
for how this fits into the broader pyirena + AI initiative.

---

## License

MIT — see [LICENSE](LICENSE).
