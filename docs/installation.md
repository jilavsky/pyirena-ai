# Installation and first run

`pyirena-ai` requires Python 3.10–3.13 and depends on
[`pyirena`](https://github.com/jilavsky/pyirena) (installed automatically).
The recommended setup uses conda.

## Install with conda (recommended)

```bash
git clone https://github.com/jilavsky/pyirena-ai.git
cd pyirena-ai
conda env create -f environment.yml
conda activate pyirena-ai
```

The environment file installs Python, matplotlib, and httpx from conda-forge,
then pip-installs `pyirena-ai` in editable mode with all extras
(`-e ".[all]"`), which pulls in `pyirena` (and through it numpy/scipy/h5py),
the `anthropic` and `openai` SDKs, `keyring`, and the Gradio GUI.

Verify:

```bash
pyirena-ai --version
pyirena-ai providers
```

The first `providers` call auto-creates the per-user config at
`~/.pyirena-ai/config.toml` (see [providers.md](providers.md)).

## First fit

```bash
# Commercial provider: store the API key once (OS keyring)
pyirena-ai set-key anthropic

# Fit a NXcanSAS HDF5 file with the Unified Fit model
pyirena-ai fit path/to/data.h5 --provider anthropic --verbose

# Or launch the GUI
pyirena-ai gui
```

For local models (LM Studio / Ollama) no key is needed — see
[providers.md](providers.md) for setup, including the important `vision`
flag.

## Updating

```bash
cd pyirena-ai
git pull
conda activate pyirena-ai
pip install -e ".[all]"      # refresh dependencies if they changed
```

If `pyirena` itself changed significantly, `pip install -U pyirena` inside
the activated environment.

## Alternative: pip only

```bash
pip install "pyirena-ai[all] @ git+https://github.com/jilavsky/pyirena-ai.git"
```

Extras can be picked individually: `[anthropic]`, `[openai]`, `[keyring]`,
`[gui]`, or `[dev]` (pytest, ruff, build tools).

## Running the tests

```bash
conda activate pyirena-ai
pytest
```

Tests that need pyirena's `testData/` folder or a live LLM key skip
automatically. Point `PYIRENA_AI_TEST_H5` at any NXcanSAS HDF5 file to enable
the tool-bridge round-trip test.
