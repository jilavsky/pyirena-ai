# Using pyirena-ai

## CLI

```bash
pyirena-ai fit FILE [options]     # run one autonomous fit
pyirena-ai gui                    # launch the Gradio GUI
pyirena-ai providers              # show configured providers + key status
pyirena-ai set-key PROVIDER       # store an API key in the OS keyring
pyirena-ai strategies             # list available fitting strategies
```

### `fit` — the important options

```
--model unified|sizes       pyirena model: Unified Fit (default) or Size Distribution
--provider NAME             anthropic | openai | lmstudio | ollama
--model-id ID               LLM model override (else config.toml default)
--base-url URL              endpoint override (proxy, remote local server)
--strategy NAME|PATH        fitting strategy (else the model's default)
--context "TEXT"            one-shot sample context appended to the system prompt
--save-out PATH             fitted HDF5 output (default: overwrite input)
--audit-out PATH            audit JSON (default: <data_dir>/pyirena-ai/<file>.audit.json)
--max-iterations N          cap on LLM↔tool round-trips (default 30 commercial / 150 local)
--all-tools                 expose all 51 control tools instead of the model's subset
--show-thinking             print model reasoning when available
--no-strategy / --no-skills diagnostic: strip prompt layers
--verbose                   stream progress to stderr
```

Examples:

```bash
# Unified Fit with Claude, sample context supplied
pyirena-ai fit scan.h5 --provider anthropic \
    --context "silica spheres in water, expect Rg ~ 40 Å" --verbose

# Size Distribution with a local Gemma via LM Studio
pyirena-ai fit scan.h5 --model sizes --provider lmstudio \
    --model-id gemma-3-27b-it --verbose
```

## GUI

`pyirena-ai gui` starts a local Gradio app (default `http://127.0.0.1:7860`)
with two tabs. Paste the full path to the NXcanSAS HDF5 file — the fitted
result is saved back to that file, the audit JSON to
`<data_folder>/pyirena-ai/`.

- **Fit** — one-shot: pick fit model + provider, press ▶ Fit, watch the tool
  calls, live fit image, and parameter table stream in. Stop aborts before
  the next LLM call.
- **Chat** — persistent session: the dataset is opened once, then you
  converse with the agent ("fit a Guinier at low Q", "why is level 2 B so
  high?", "now save it"). Token counts and the audit accumulate across the
  whole session. *Reload prompt* re-reads edited strategy/skill markdown
  files without restarting the session.

Toggles on both tabs: include strategy, include skills (diagnostic), show
thinking.

## Customizing the prompts

The system prompt is assembled from four layers (see
`pyirena_ai/core/skills.py`):

1. **Strategy** — the staged workflow. Bundled in
   `pyirena_ai/config/strategies/`; a file with the same name in
   `~/.pyirena-ai/strategies/` overrides it. `--strategy` also accepts a
   direct `.md` path.
2. **Skills** — per-model expert guidance. Bundled in
   `pyirena_ai/config/skills/`; override in `~/.pyirena-ai/skills/`.
3. **User / lab instructions** — `~/.pyirena-ai/instructions.md`, appended
   to every prompt (created as a commented template on first run). Put
   beamline conventions, units, reporting preferences here.
4. **Per-fit context** — `--context` / the GUI "Additional context" box.

## The audit trail

Every run writes `<data_dir>/pyirena-ai/<file>.audit.json`
(`<stem>.chat.audit.json` for GUI chat sessions): schema
`pyirena-ai/audit/v1`, containing versions, the full system prompt, every
tool call with arguments/results/timing (image payloads redacted), token
usage, estimated cost, final χ², and the save path. It is the record of what
the AI actually did — keep it next to the data.

## What the agent is allowed to do

The agent can only call pyirena's control-surface functions (open/fit/save
on the named file); it has no shell, filesystem, or network tools. Hard caps
bound each run: iteration limit, cumulative input-token limit (warning at
80 %), and per-turn output limit. A failing tool call is returned to the
model as a structured error so it can adjust and continue rather than abort.
Only the two newest fit images are kept in the conversation to keep prompts
compact.
