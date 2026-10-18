"""Finance playbooks as prompt files (`skills/*.md`). The agent loads one with the `skill` tool; they only name tools that exist."""

from __future__ import annotations

from pathlib import Path

DIR = Path(__file__).parent / "skills"


def names() -> list[str]:
    return sorted(p.stem for p in DIR.glob("*.md"))


def get(name: str) -> str | None:
    if name not in names():  # also blocks path tricks: only known file stems are read
        return None
    return (DIR / f"{name}.md").read_text(encoding="utf-8")
