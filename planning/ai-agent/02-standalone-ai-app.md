# 02 — Standalone AI App (Main Product)

**Status:** Draft
**Last updated:** 2026-06-09
**Depends on:** [01 API & MCP extensions](01-api-and-mcp-extensions.md) — needs the full control surface
**Related:** [03 In-GUI AI advisor](03-ai-advisor-in-gui.md) — shares LLM provider layer

---

## Goal

A separate installable package (working name: **`pyirena-ai`**) that imports
pyirena and lets users have an LLM **autonomously fit datasets and folders**
of SAXS/USAXS data. The main product of this initiative.

Distinct from pyirena itself: pyirena is a focused scientific library; this
package is the AI-driven workflow consumer.

The set of pyirena tools this app drives is defined in
[00-overall-plan.md — Scope of pyirena tools supported](00-overall-plan.md#scope-of-pyirena-tools-supported).
Unified Fit is the test case; the app inherits whatever support
[01](01-api-and-mcp-extensions.md) ships.

> **Note:** detailed decisions for this subproject (GUI framework, package
> name, audit format, etc.) will be revisited once subprojects 1 and 3 are
> further along and we have real experience with the agent loop. The plan
> below is a placeholder structure.

---

## Primary user workflows

### Workflow A — Folder batch fitting
> "Fit all 50 USAXS scans in this folder with Unified Fit + size distribution."

User opens the app, drags in a folder, selects a strategy (or accepts the
default), presses go. AI fits each dataset, produces results, flags
outliers, generates a summary report.

### Workflow B — Live instrument-side fitting
> "Watch this folder; fit each new scan as it arrives."

Same as A but with a folder watcher. Files appear → AI fits → results
update. Useful at beamlines during data collection.

### Workflow C — Interactive AI co-pilot for one dataset
> "Help me fit this tricky dataset; I want to watch your reasoning."

User uploads a single dataset; conversation-style interface. AI shows its
tool calls, results, decisions. User can interject, correct, override.
Bridges into Workflow A by saving the conversation as a reusable strategy.

---

## Architecture

```
pyirena-ai/
├── pyproject.toml             # depends on pyirena, anthropic, gradio (or chosen GUI), ...
├── pyirena_ai/
│   ├── __init__.py
│   ├── core/
│   │   ├── agent.py           # tool-use loop (LLM-agnostic)
│   │   ├── tools.py           # JSON schemas + dispatch → pyirena.api
│   │   ├── strategy.py        # System prompts, fitting playbooks
│   │   ├── session.py         # Conversation + audit trail
│   │   └── watcher.py         # Folder-watch for live mode
│   ├── llm/
│   │   ├── base.py            # Provider interface
│   │   ├── anthropic.py
│   │   ├── openai.py
│   │   └── local.py           # Ollama / llama.cpp (later phase)
│   ├── config/
│   │   ├── settings.py        # API keys (via keyring), model, custom instructions
│   │   └── strategies/        # Built-in fitting playbooks (.md files)
│   ├── gui/
│   │   ├── app.py             # Gradio / Chainlit / Streamlit entry point
│   │   ├── plots.py           # Render pyirena results
│   │   ├── conversation.py    # Chat / agent-step display
│   │   └── components.py
│   └── cli/
│       └── main.py            # Headless CLI for batch / scripting
└── tests/
```

### Layers
1. **Provider layer (`llm/`)** — thin interface over Anthropic, OpenAI, local.
   Handles tool-use loop primitives (send message, receive tool calls, send
   tool results). The rest of the app is LLM-agnostic.
2. **Agent layer (`core/`)** — orchestrates the loop. Owns the conversation,
   dispatches tool calls to `pyirena.api`, manages sessions, writes audit
   trail.
3. **Tool layer (`core/tools.py`)** — registers each `pyirena.api` function
   as an LLM-callable tool with JSON schema. The single bridge between the
   AI world and the pyirena world.
4. **GUI / CLI layer** — two front-ends sharing the same agent core.
   Headless CLI for batch and scripting; GUI for interactive use.

---

## GUI framework decision

| Framework | Strengths for this app | Weaknesses |
|-----------|------------------------|------------|
| **Gradio** (recommended) | Built for AI/ML demos; native chat, streaming, tool calls, file upload, image display; deploys like Streamlit | Less flexible than Streamlit for complex non-chat layouts |
| **Chainlit** | Purpose-built for LLM chat; agent step visualization (every tool call shown); great for "watch AI fit" UX | Smaller community; chat-only shape |
| **Streamlit** | Familiar to user (uses elsewhere); large ecosystem | Rerun-on-interaction model fights against streaming chat / agent loops; more plumbing |
| **PySide/PyQt** | True desktop app; tighter integration with pyirena's existing Qt GUI possible | Slow to develop chat UIs; packaging painful (PyInstaller, code signing) |

**Leaning: Gradio.** Native chat + agent step visualization + image
rendering + simple deploy, with enough flexibility to add result tables and
folder-progress views. Falls back to Streamlit if Gradio's layout
constraints become limiting.

Final decision deferred until after building a 1-day spike in both.

---

## Phasing

### Phase 1 — Headless agent prototype (small)
**Goal:** prove the agent loop with no GUI distraction.

- CLI: `pyirena-ai fit data.h5 --model unified --strategy default.md`
- One LLM provider (Anthropic), one model (Unified Fit), one strategy
- Produces: fitted HDF5 + JSON transcript of all tool calls
- No multi-LLM, no GUI, no folder mode

Validates: agent loop works, tool granularity is right, system prompts make
sense. Useful immediately for power users.

### Phase 2 — Minimal GUI (medium)
**Goal:** chosen framework + basic interactive use.

- File upload → chat with AI → see plots/tables → export
- Display current parameters live as AI changes them
- Show each tool call as an "agent step" visible to user
- Cancel / pause / approve checkpoints

Validates: GUI framework choice, UX patterns.

### Phase 3 — Batch + folder mode (medium)
**Goal:** the primary product workflow.

- Folder picker; AI fits each file
- Progress display: which file is being fit, how many done, how many failed
- Final summary report with parameter trends across the folder
- Folder watcher mode for live instrument-side fitting

#### Detailed design (added 2026-06-11 after Phase 2 lessons)

User workflows envisioned:

- **A. One-shot folder batch.** User pastes a folder path. App lists
  matching `*.h5` files, user picks "all" or a subset, presses Fit.
  Each file is fitted in sequence; per-file audit is written to
  `<folder>/pyirena-ai/<filename>.audit.json`. A batch manifest
  (`<folder>/pyirena-ai/_batch.json`) lists each file's outcome.

- **B. Live folder watcher (beamline mode).** App watches a folder for new
  `*.h5` files; each new file is queued and fitted when the previous one
  finishes. Loop runs until the user stops it. Critical: files appearing
  on the watcher must be *quiet* (write complete) before fitting — the
  acquisition software may still be writing them.

##### Design implications of current (Phase 1–2) decisions

The current codebase is *folder-mode friendly* in most respects; the
big new piece is an orchestrator that loops over files. Specifically:

| Decision | Folder-mode impact |
|----------|-------------------|
| Audit subfolder `<dir>/pyirena-ai/<name>.audit.json` | ✅ Already folder-mode shaped: every file in a batch gets its own audit in the same place. |
| In-place HDF5 overwrite via plain path | ✅ Each file in a folder is written in place. Plus: file-watcher mode needs the actual path, so this is on the critical path. |
| `RunSession` is per-file (single `pyirena_session_id`) | ✅ One `RunSession` per file in the batch; collected in a `BatchSession` wrapper. Per-file audit unchanged. |
| `pyirena.api.control` supports multiple open sessions | ✅ But we will fit serially (one open at a time) to keep memory bounded and to avoid one fit's failure cascading. |
| Errors are dicts, never exceptions | ✅ Critical for batch mode — a per-file `{"error": …}` lets us continue to the next file rather than abort the batch. |
| `GradioRunner` wraps one `Agent` for one file | ⚠️ Needs a `BatchRunner` layer that loops, instantiates one `Agent` per file, and re-uses the same provider object so we don't recreate the HTTP client per file. |
| Stop button stops one `Agent` via `threading.Event` | ⚠️ For folder mode the semantics need to be "stop after current file" vs "stop immediately" — add a second `cancel_batch` flag. |
| `--context` / GUI context textbox = one-shot per-fit | ⚠️ For batch the context typically applies to *the whole folder* (one sample, many scans). Per-file context override is unlikely to be needed v1 — punt. |
| Strategy = one markdown file per agent run | ⚠️ Same strategy reused per file in batch. No change needed; just be aware that thousands of tokens of system prompt are re-paid per file. Cache-friendly providers (Anthropic prompt caching) mitigate this. |
| Cost transparency: tokens + USD per run | ⚠️ Batch-level totals (sum across files) need to be displayed too. |
| Per-fit `random_seed=42` baked into strategy | ✅ Reproducibility automatically applies per-file in batch. |

##### Code shape sketch (do not implement until Phase 3)

```
pyirena_ai/core/
  agent.py            # unchanged; one file per Agent run
  batch.py            # NEW: BatchRunner — orchestrates N Agent runs
  watcher.py          # NEW: folder watcher (watchdog) → enqueue → BatchRunner

pyirena_ai/gui/
  app.py              # accepts file OR folder path in the same textbox
  runner.py           # GradioRunner detects path type, dispatches to
                      #   single-file Agent or BatchRunner accordingly

pyirena_ai/cli/
  main.py             # `pyirena-ai fit FILE-or-FOLDER` (already takes a string)
                      # `pyirena-ai watch FOLDER --strategy ...`
```

`BatchRunner` API:

```python
class BatchRunner:
    def __init__(self, provider, *, system_prompt, on_file_start, on_file_done):
        ...
    def run(self, files: list[Path]) -> BatchSession:
        # for each file: build RunSession + Agent, call agent.run(),
        # collect into BatchSession; respect cancel flags
        ...
    def cancel_after_current(self): ...
    def cancel_now(self): ...
```

`BatchSession` adds, on top of per-file `RunSession`s:
- total tokens / cost across the batch
- list of (path, outcome, χ²ᵣ) for the manifest

##### Folder watcher specifics

- Use `watchdog` library (already widely-used standard).
- **Debounce**: a new-file event fires when the file is *opened* by the
  writer, not when it's done. Wait until: (a) file size stable for ≥2 s,
  AND (b) `h5py.File(..., 'r')` opens successfully and finds the
  expected NXcanSAS groups. Skip with a log line otherwise; the file
  will re-fire if it's renamed/touched later.
- **Restart safety**: on startup, scan the folder for any `*.h5` whose
  matching audit is missing (`pyirena-ai/<name>.audit.json` doesn't
  exist or is older than the HDF5). Fit those first, then watch.
- **Recovery**: if a fit crashes the agent, write a partial audit
  marking the file as `failed` (don't write the audit at all and we'll
  loop trying it again on restart).

##### Open questions for Phase 3 kickoff

1. Should the GUI show a per-file progress table (rows: filename,
   status, χ²ᵣ, time, cost)? Almost certainly yes; design then.
2. Cancel semantics: one button with three states (idle / cancel
   after current / cancel immediately) vs two buttons. Probably two
   buttons keeps it explicit.
3. Watcher loop in same Gradio process or a separate background
   daemon? Same-process is fine v1; revisit if it interferes with GUI
   responsiveness.
4. When a fit produces a poor χ²ᵣ in batch mode, should the agent be
   asked to retry with different starting conditions, or just flag and
   move on? Default: flag and move on; user opt-in retry.

### Phase 4 — Distribution polish (medium)
**Goal:** ship-ready for 10-100 users/month.

- Multi-LLM (OpenAI + Anthropic; local optional)
- API key management via OS keyring
- Custom instructions per lab (loaded from `~/.pyirena-ai/instructions.md`)
- Cost transparency (tokens / dollars per session)
- Audit trail format finalized (JSON sidecar alongside HDF5)
- Conda + pip packaging
- Installation and configuration docs

### Phase 5 — Strategy library (small, ongoing)
**Goal:** ship reusable fitting playbooks.

- Built-in strategies for common cases ("Unified Fit, 2 levels, mass
  fractal", "Sizes distribution, MaxEnt, log-spacing")
- User-saveable strategies from successful conversations
- Strategy = system prompt fragment + initial tool-call sequence

---

## Cross-cutting requirements

(Repeating items from `00-overall-plan.md` that apply specifically here.)

- **Audit trail**: every fit produces a JSON sidecar listing each tool call,
  arguments, results, χ² evolution. Stored next to the HDF5.
- **Multi-LLM from day one of phase 4**: don't lock to Anthropic-only.
- **Custom instructions**: lab-specific system prompts as a first-class
  config field.
- **Human-in-the-loop checkpoints**: agent can pause for confirmation on
  destructive actions or when it's uncertain.
- **Cost transparency**: tokens used + estimated cost per session/file.

---

## Open questions

| Question | Notes |
|----------|-------|
| Package name | `pyirena-ai`, `irena-copilot`, `saxs-agent`, ... |
| GUI framework final choice | Spike Gradio + Chainlit before committing |
| How to handle long-running fits | Streaming progress vs blocking? Likely OK to block initially since most pyirena fits are seconds-to-minutes |
| Audit trail format | JSON sidecar likely; could extend NXcanSAS schema instead |
| Where to store user strategies | `~/.pyirena-ai/strategies/` directory of markdown files |
| Folder watcher backend | `watchdog` library is the standard choice |
| How to handle fit failures in batch mode | Skip + log? Retry with different starting conditions? Ask AI to diagnose? |
| Cost guardrails | Per-session token cap? Per-user monthly budget warning? |
| Distribution channel | pip + conda? PyInstaller bundle for non-developers? |

---

## Out of scope

- Replacing pyirena's manual GUI
- Cloud-hosted SaaS (everything runs locally)
- Training custom models
- Multi-user / shared workspace features
- Real-time instrument control beyond reading the data folder

---

## Success criteria

1. User can install via `pip install pyirena-ai`
2. User can run `pyirena-ai fit folder/` and get reasonable fits for all files
3. User can open the GUI, drag a folder, watch the AI fit each file, and
   trust the results enough to use them
4. Every fit has an audit trail explaining how the AI arrived at the result
5. Cost per dataset is transparent and bounded
6. Works with at least Anthropic and OpenAI providers
