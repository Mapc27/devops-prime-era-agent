import os
from functools import lru_cache
from pathlib import Path

from opscrew.config import ROOT

PERSONA_DIR = Path(os.getenv("OPSCREW_PERSONA_DIR", str(ROOT / "persona")))


@lru_cache
def persona(*names: str) -> str:
    return "\n\n".join((PERSONA_DIR / f"{n}.md").read_text() for n in names)


@lru_cache
def prompt(name: str) -> str:
    return (ROOT / "prompts" / f"{name}.md").read_text()
