# Changelog

All notable changes to `pyirena-ai` will be documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

## [0.0.1] — unreleased
First scaffolding release; not yet on PyPI.
