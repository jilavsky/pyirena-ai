#!/usr/bin/env python
"""End-to-end smoke test against a real LLM.

Not part of CI. Run manually after `pyirena-ai set-key anthropic`:

    python scripts/smoke_fit.py /path/to/file.h5

You can also override the provider / model with environment variables:

    SMOKE_PROVIDER=anthropic
    SMOKE_MODEL=claude-opus-4-7
    SMOKE_BASE_URL=                  (empty = provider default)

Writes a `<file>.audit.json` next to the input and overwrites the input
with the fitted result (just like `pyirena-ai fit ...` would).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pyirena_ai.cli.main import main as cli_main


def _usage() -> int:
    print(__doc__)
    return 2


def main() -> int:
    if len(sys.argv) != 2:
        return _usage()

    target = Path(sys.argv[1]).resolve()
    if not target.is_file():
        print(f"error: file not found: {target}", file=sys.stderr)
        return 2

    argv = [
        "fit",
        str(target),
        "--provider", os.environ.get("SMOKE_PROVIDER", "anthropic"),
        "--verbose",
    ]
    if model := os.environ.get("SMOKE_MODEL"):
        argv += ["--model-id", model]
    if base_url := os.environ.get("SMOKE_BASE_URL"):
        argv += ["--base-url", base_url]

    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
