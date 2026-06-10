"""Expert fitting guidance, user instructions, and full system-prompt assembly.

## Three layers, assembled in order:

1. **Strategy** — the workflow: what tools to call, in what order, and the
   hard rules.  Lives in `pyirena_ai/config/strategies/<name>.md` (bundled)
   or `~/.pyirena-ai/strategies/<name>.md` (user override).
   Loaded by `core/strategy.py:load_strategy()`.

2. **Skills** — per-tool expert knowledge: parameter interpretation, residual
   pattern recognition, common mistakes, Q-range advice.  Designed to be
   updated independently of the workflow strategy.
   Search order (first match wins):
     a. `~/.pyirena-ai/skills/<tool_name>.md`   (user override)
     b. `pyirena_ai/config/skills/<tool_name>.md` (bundled, synced from pyirena)

3. **User / lab instructions** — persistent per-installation customisation.
   Read from `~/.pyirena-ai/instructions.md` if the file exists.
   A commented template is created on first call if the file is absent.

4. **Per-fit context** — one-shot text passed from the CLI `--context` flag or
   the GUI "Additional context" textbox.  Not persisted.

`build_system_prompt()` concatenates all four layers in that order.
"""

from __future__ import annotations

from pathlib import Path

from pyirena_ai.config.settings import CONFIG_DIR

# ---------------------------------------------------------------------------
# Bundled skills directory (inside the installed package)
# ---------------------------------------------------------------------------
_BUNDLED_SKILLS_DIR = Path(__file__).resolve().parent.parent / "config" / "skills"

_INSTRUCTIONS_TEMPLATE = """\
# pyirena-ai — user / lab instructions
#
# This file is appended to every system prompt. Use it to encode:
#   - Your lab's naming conventions or instrument calibration notes
#   - Sample-class–specific advice ("all our samples are in D₂O")
#   - Preferred reporting style
#   - Any behaviour you want the AI to always or never do
#
# Lines starting with # are NOT sent to the AI (they are stripped before use).
# Edit this file in any plain-text editor. Changes take effect on the next run.
#
# Example:
#   Our SAXS data are collected at the Advanced Photon Source 9-ID-C beamline
#   using 21 keV X-rays. Rg values are in Å. Volume fractions refer to the
#   dry mass volume fraction unless otherwise stated. Always report the P value
#   and comment on whether it is consistent with the expected morphology.
"""


def load_skills(tool_name: str) -> str:
    """Return the skills text for *tool_name*, or empty string if not found.

    Search order: user override → bundled package file.
    """
    candidates = [
        CONFIG_DIR / "skills" / f"{tool_name}.md",
        _BUNDLED_SKILLS_DIR / f"{tool_name}.md",
    ]
    for p in candidates:
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8")
            except OSError:
                pass
    return ""


def load_user_instructions() -> str:
    """Read `~/.pyirena-ai/instructions.md`, stripping comment lines.

    Creates a commented template on first call if the file is absent.
    Returns empty string if the file exists but contains only comments/blanks.
    """
    path = CONFIG_DIR / "instructions.md"
    if not path.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(_INSTRUCTIONS_TEMPLATE, encoding="utf-8")
        return ""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""

    active = [ln for ln in lines if not ln.startswith("#")]
    return "\n".join(active).strip()


def build_system_prompt(
    strategy_text: str,
    tool_name: str = "unified_fit",
    extra_context: str = "",
) -> str:
    """Assemble the full system prompt from all four layers.

    Parameters
    ----------
    strategy_text:
        Content of the loaded strategy file (workflow + hard rules).
    tool_name:
        Name of the pyirena tool being fitted (e.g. ``"unified_fit"``).
        Used to look up the matching skills file.
    extra_context:
        One-shot per-fit text from the CLI ``--context`` flag or the GUI
        "Additional context" textbox (not persisted).
    """
    parts = [strategy_text.strip()]

    skills = load_skills(tool_name).strip()
    if skills:
        parts.append(
            "\n## Expert fitting guidance\n\n" + skills
        )

    user_instr = load_user_instructions().strip()
    if user_instr:
        parts.append(
            "\n## User / lab instructions\n\n" + user_instr
        )

    if extra_context and extra_context.strip():
        parts.append(
            "\n## Context for this fit\n\n" + extra_context.strip()
        )

    return "\n\n".join(parts)
