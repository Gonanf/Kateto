from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final


_SKILL_NAME: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9-]*")


@dataclass(frozen=True, slots=True)
class SkillLoadError(Exception):
    name: str
    reason: str

    def __str__(self) -> str:
        return f"unable to load skill {self.name!r}: {self.reason}"


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    name: str
    path: Path
    instructions: str


def load_skills(*, config_dir: Path, names: tuple[str, ...]) -> tuple[LoadedSkill, ...]:
    root = config_dir.resolve()
    skill_root = (root / "skills").resolve()
    if not skill_root.is_relative_to(root):
        raise SkillLoadError(name="<root>", reason="skills directory escapes config root")
    loaded: list[LoadedSkill] = []
    for name in names:
        if _SKILL_NAME.fullmatch(name) is None:
            raise SkillLoadError(name=name, reason="name is not a safe declarative skill identifier")
        path = (skill_root / name / "SKILL.md").resolve()
        if not path.is_relative_to(skill_root):
            raise SkillLoadError(name=name, reason="document escapes skills directory")
        if not path.is_file():
            raise SkillLoadError(name=name, reason="SKILL.md does not exist")
        loaded.append(LoadedSkill(name=name, path=path, instructions=path.read_text(encoding="utf-8")))
    return tuple(loaded)
