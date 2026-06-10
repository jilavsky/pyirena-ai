"""In-memory record of one agent run, for the audit trail.

The agent appends a `Turn` each time something happens (assistant text,
tool_use + tool_result, error). At the end of the run the CLI hands the
session to `audit.write_audit_json`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Turn:
    i:          int
    type:       str                          # "assistant_text" | "tool_use" | "error"
    text:       str = ""                     # for assistant_text / error
    tool:       str = ""                     # for tool_use
    args:       dict[str, Any] = field(default_factory=dict)
    result:     dict[str, Any] = field(default_factory=dict)
    elapsed_s:  float = 0.0
    timestamp:  str = field(default_factory=_now)


@dataclass
class RunSession:
    input_file:    str = ""
    provider:      str = ""
    model:         str = ""
    base_url:      str = ""
    strategy:      str = ""
    system_prompt: str = ""
    started_at:    str = field(default_factory=_now)
    finished_at:   str = ""

    turns:         list[Turn] = field(default_factory=list)
    input_tokens:  int = 0
    output_tokens: int = 0

    final_chi_squared: float | None = None
    saved_to:          str = ""
    cost_usd_estimate: float | None = None

    # Track which session_id we last saw open_dataset return, so the CLI
    # can look up chi-squared and decide save path without re-parsing turns.
    pyirena_session_id: str = ""

    def add_assistant_text(self, text: str) -> None:
        self.turns.append(Turn(i=len(self.turns), type="assistant_text", text=text))

    def add_tool_use(
        self,
        *,
        tool: str,
        args: dict,
        result: dict,
        elapsed_s: float,
    ) -> None:
        self.turns.append(Turn(
            i=len(self.turns),
            type="tool_use",
            tool=tool,
            args=args,
            result=result,
            elapsed_s=elapsed_s,
        ))

    def add_error(self, text: str) -> None:
        self.turns.append(Turn(i=len(self.turns), type="error", text=text))

    def tool_use_count(self) -> int:
        return sum(1 for t in self.turns if t.type == "tool_use")
