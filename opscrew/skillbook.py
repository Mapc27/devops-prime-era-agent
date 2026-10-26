"""Skills: SKILL.md files with frontmatter, loaded with progressive disclosure.

Only names + descriptions are shown to the router; the full body is loaded into the
investigator context when the skill is selected.
"""

from dataclasses import dataclass
from functools import lru_cache

import yaml

from opscrew.config import ROOT

SKILLS_DIR = ROOT / "skills"


@dataclass
class Skill:
    name: str
    description: str
    when_to_use: str
    body: str


@lru_cache
def all_skills() -> dict[str, Skill]:
    out = {}
    for p in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        txt = p.read_text()
        _, fm, body = txt.split("---", 2)
        meta = yaml.safe_load(fm)
        out[meta["name"]] = Skill(meta["name"], meta["description"], meta.get("when_to_use", ""), body.strip())
    return out


def criteria(include_none=True) -> dict[str, str]:
    """Choice criteria for the decision model (incident skills only)."""
    c = {s.name: f"{s.description}. Signals: {s.when_to_use}" for s in all_skills().values() if s.name != "write-postmortem"}
    if include_none:
        c["none"] = "None of the above fits"
    return c


def get(name: str) -> Skill | None:
    return all_skills().get(name)
