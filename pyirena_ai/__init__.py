"""pyirena-ai — AI-driven SAXS/USAXS fitting on top of pyirena.

The public entry point is the `pyirena-ai` command-line tool. As a Python
library, the most useful imports are:

    from pyirena_ai.core.agent import Agent
    from pyirena_ai.llm.registry import build_provider
    from pyirena_ai.core.tools import TOOL_SCHEMAS, dispatch

See ``README.md`` and ``planning/ai-agent/`` for design and roadmap.
"""

from __future__ import annotations

__version__ = "0.0.1"
__all__ = ["__version__"]
