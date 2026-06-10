# Contributing to pyirena-ai

Thanks for your interest. This project is in early alpha — the API surface,
agent loop, and CLI shape are all subject to change as we learn from real
fitting runs. Issues and small PRs welcome.

## Development setup

```bash
git clone https://github.com/jilavsky/pyirena-ai.git
cd pyirena-ai
conda env create -f environment.yml
conda activate pyirena-ai
pip install -e ".[dev,anthropic]"
pytest
```

Python 3.10+ is required. The package depends on a published `pyirena>=0.8.2`
from PyPI; for parallel development against an unreleased pyirena check-out,
do `pip install -e /path/to/pyirena` after the conda env is created.

## Running tests

```bash
pytest                          # unit tests, no network
pytest -m "not requires_llm"    # skip tests that need an LLM key (default)
```

A real-LLM smoke test lives at `scripts/smoke_fit.py` and is not part of
CI. Run it manually to validate end-to-end behavior against a live model.

## Code style

- English comments, explicit names, no clever one-liners.
- Avoid adding dependencies. The base package depends only on `pyirena` and
  `httpx`. LLM SDKs go behind optional extras.
- Errors that cross the agent boundary must be `{"error", "code",
  "suggestion"}` dicts, never raised exceptions — that contract is enforced
  by the agent loop and the audit trail.

## What needs work upstream in pyirena

When you hit a missing capability in `pyirena.api` / `pyirena.api.control`,
open an issue in **this** repo first (so we keep the dependency in one
place), then we'll mirror it upstream. Current known asks are listed in
`planning/ai-agent/01-api-and-mcp-extensions.md`.
