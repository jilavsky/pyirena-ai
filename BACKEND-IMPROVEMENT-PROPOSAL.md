# pyirena-ai — Backend Improvement Proposal (remaining work)

*Original review: 2026-07-10. Phase A + B and all changes not depending on the
pyirena-mcp expansion were implemented on the `backend-improvements` branch —
see CHANGELOG.md ([Unreleased]) for what was done. This file now lists only
the items still open, roughly in the order they are expected to pay off.*

## Deferred until the pyirena-mcp expansion

**ToolBackend protocol.** `core/tools.py` binds to pyirena in-process
(`from pyirena.api import control`). When additional pyirena MCP functions
arrive, define a small backend interface so the binding becomes pluggable:

```python
class ToolBackend(Protocol):
    def schemas(self) -> list[dict]: ...
    def dispatch(self, name: str, args: dict) -> dict: ...
    def versions(self) -> dict: ...   # pyirena / control-api versions
```

The current module becomes `InProcessBackend`; a future `McpClientBackend`
(driving a running pyirena-mcp server over stdio/HTTP) slots in without
touching the agent, audit, or frontends. The groundwork (tool groups,
traits, filtering) is already in place and backend-agnostic.

**Version handshake.** `CONTROL_API_VERSION` is recorded in the audit; add a
startup compatibility check with a clear message when the installed pyirena
is older/newer than what pyirena-ai's strategies and trait tables expect,
instead of failing mid-run with `UNKNOWN_TOOL`. Becomes important once the
control surface starts moving faster than this package.

**Schema-carried tool metadata.** `TOOL_GROUPS` / `MUTATING_TOOLS` /
`HARVEST_RULES` live in pyirena-ai and are guarded by tests that fail when a
new pyirena tool is unclassified. The cleaner long-term home is pyirena
itself: optional keys on each schema entry (e.g. `"x-group": "sizes"`,
`"x-mutates-state": true`) that pyirena-ai reads, so a new control function
carries its own metadata and needs zero edits here.

## Worth doing when convenient

**Incremental audit writing.** The audit is written once at the end (plus
partial-on-exception paths). A hard process kill — power loss, OOM during an
overnight batch — loses the trail. Writing each turn as a JSON-lines sidecar
(or rewriting the JSON after every tool call; the files are small) makes the
audit crash-proof and allows live tailing during batch runs. The `audit/v1`
schema stamp makes this a clean `v2`.

**Chat session persistence.** `Agent.messages` is a plain list of JSON-able
dicts; serializing it together with `RunSession` would enable "resume
yesterday's chat session". Keep in mind so nothing non-serializable creeps
into the message blocks.

**Pricing table externalization.** `llm/pricing.py` is hardcoded and will go
stale. Allow overrides from `config.toml` (e.g.
`[pricing."claude-..."] input = 15.0, output = 75.0`) so users on proxy
endpoints can correct costs without a release.

**Logging module.** Progress/warnings go through `print(..., file=sys.stderr)`
and callbacks. Adopting stdlib `logging` (`logging.getLogger("pyirena_ai")`)
matters when pyirena's GUI embeds this package — the host app can route or
silence output.

**OpenAI o-series reasoning.** `reasoning` / `reasoning_content` response
fields (noted in `openai_compat.py`) could populate `thinking_text` when
those endpoints are in scope.

**Synthetic NXcanSAS test fixture.** The tool-bridge round-trip test skips
without pyirena's `testData/`. A tiny h5py-generated NXcanSAS file in
`tests/` would let it run on CI too.

**Static typing.** The codebase is well annotated and now lint-clean; a
permissive mypy/pyright pass plus a `py.typed` marker would finish the job.
A pre-commit config (ruff) would keep contributors honest.

**Config writer round-tripping.** The hand-rolled TOML emitter in
`settings.py` drops unknown keys/comments a user adds by hand. If the config
grows beyond model/base_url/vision, switch to `tomlkit`.

**GUI tool-scope toggle.** The CLI has `--all-tools`; the GUI currently
always uses the per-model subset. If a GUI use case for the full surface
appears (e.g. cross-model comparisons in Chat), add a checkbox wired to
`RunConfig.all_tools`.
