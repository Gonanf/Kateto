from __future__ import annotations

import re
import shutil
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


def ensure_shared_skill(config_dir: Path, name: str) -> Path:
    """Copy-missing backfill of one bundled shared skill into an existing config dir.

    `bootstrap_config` early-returns when `config.toml` exists, so existing users
    never receive new default files from bootstrap alone. The vision plugin calls
    this from `initialize()` as a narrow exception to that rule.
    # ponytail: copies the single SKILL.md only, never the whole tree; existing-user
    # voice.skills lists stay manual (docs step), add auto-merge when wanted.
    """
    if _SKILL_NAME.fullmatch(name) is None:
        raise SkillLoadError(name=name, reason="name is not a safe declarative skill identifier")
    target = config_dir / "skills" / name / "SKILL.md"
    if target.is_file():
        return target
    from kateto.core.config import default_config_dir

    source = default_config_dir() / "skills" / name / "SKILL.md"
    if not source.is_file():
        raise SkillLoadError(name=name, reason="bundled skill is missing from defaults")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    except OSError as error:
        raise SkillLoadError(name=name, reason=f"backfill failed: {error}") from error
    return target
