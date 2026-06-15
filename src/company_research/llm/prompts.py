from __future__ import annotations

import re
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "prompts"


def load(name: str, **kwargs: str) -> str:
    """Load a prompt template by name and substitute {{ key }} placeholders."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    template = path.read_text(encoding="utf-8")
    # Strip frontmatter
    template = re.sub(r"^---\n.*?\n---\n", "", template, flags=re.DOTALL)
    # Substitute placeholders
    for key, value in kwargs.items():
        template = template.replace("{{ " + key + " }}", value)
        template = template.replace("{{" + key + "}}", value)
    return template.strip()


def prompt_version(name: str) -> str:
    """Return the version string from a prompt's frontmatter."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        return "unknown"
    content = path.read_text(encoding="utf-8")
    m = re.search(r'^version:\s*"?([^"\n]+)"?', content, re.MULTILINE)
    return m.group(1).strip() if m else "unknown"
