"""Load a system-prompt strategy from a markdown file.

Search order, first hit wins:

  1. `~/.pyirena-ai/strategies/<name>.md`   (user override)
  2. `pyirena_ai/config/strategies/<name>.md` (bundled)
  3. `name` itself, treated as an absolute or working-directory-relative
     path if it ends in `.md`.

Returns the file's text content. A `KeyError` is raised if no file matches.
"""

from __future__ import annotations

from pathlib import Path

from pyirena_ai.config.settings import CONFIG_DIR


def load_strategy(name: str) -> str:
    candidates: list[Path] = []

    user_dir = CONFIG_DIR / "strategies"
    if not name.endswith(".md"):
        candidates.append(user_dir / f"{name}.md")
        bundled = Path(__file__).resolve().parent.parent / "config" / "strategies" / f"{name}.md"
        candidates.append(bundled)
    else:
        candidates.append(Path(name))
        candidates.append(user_dir / name)
        bundled = Path(__file__).resolve().parent.parent / "config" / "strategies" / name
        candidates.append(bundled)

    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8")

    raise KeyError(
        f"Strategy {name!r} not found. Tried:\n  - "
        + "\n  - ".join(str(p) for p in candidates)
    )


def list_strategies() -> list[str]:
    """List the strategy names available (without the .md suffix)."""
    seen: dict[str, None] = {}

    bundled_dir = Path(__file__).resolve().parent.parent / "config" / "strategies"
    user_dir = CONFIG_DIR / "strategies"

    for d in (bundled_dir, user_dir):
        if d.is_dir():
            for p in sorted(d.glob("*.md")):
                seen.setdefault(p.stem, None)

    return list(seen)
