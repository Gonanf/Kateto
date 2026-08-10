from __future__ import annotations

from pathlib import Path

from kateto.cli.agency_convert import convert_agency_pack

_AGENT_MD = """---
name: Code Reviewer
description: Expert code reviewer who provides constructive, actionable feedback.
color: purple
emoji: 👁️
vibe: Reviews code like a mentor, not a gatekeeper.
---

# Code Reviewer Agent

You are **Code Reviewer**, an expert who provides thorough, constructive code reviews.
"""


def _agency_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    division = repo / "engineering"
    division.mkdir(parents=True)
    (division / "engineering-code-reviewer.md").write_text(_AGENT_MD, encoding="utf-8")
    (division / "engineering-software-engineer.md").write_text(
        "---\nname: Software Engineer\ndescription: Builds robust systems.\n---\n\n# Software Engineer Agent\n\nWrites production code.\n",
        encoding="utf-8",
    )
    return repo


def test_convert_agency_pack_writes_voice_and_skill(tmp_path: Path) -> None:
    # Given: an agency-agents style repo and an empty out dir.
    repo = _agency_repo(tmp_path)
    out = tmp_path / "out"

    # When: the pack is converted.
    converted = convert_agency_pack(repo, out)

    # Then: ids drop the division prefix and both files exist with expected content.
    assert converted == ["code-reviewer", "software-engineer"]
    soul = out / "voices" / "code-reviewer" / "SOUL.md"
    skill = out / "skills" / "code-reviewer" / "SKILL.md"
    assert soul.is_file()
    assert skill.is_file()
    assert "You are **Code Reviewer**" in soul.read_text(encoding="utf-8")
    skill_text = skill.read_text(encoding="utf-8")
    assert skill_text.startswith("---\nname: code-reviewer\n---\n")
    assert "Expert code reviewer" in skill_text


def test_convert_agency_pack_skips_existing_unless_force(tmp_path: Path) -> None:
    # Given: a converted pack whose voice already exists.
    repo = _agency_repo(tmp_path)
    out = tmp_path / "out"
    converted = convert_agency_pack(repo, out)
    assert converted == ["code-reviewer", "software-engineer"]
    soul = out / "voices" / "code-reviewer" / "SOUL.md"
    soul.write_text("original", encoding="utf-8")

    # When: converted again without force, then with force.
    assert convert_agency_pack(repo, out) == []
    assert soul.read_text(encoding="utf-8") == "original"
    assert convert_agency_pack(repo, out, force=True) == ["code-reviewer", "software-engineer"]
    assert "You are **Code Reviewer**" in soul.read_text(encoding="utf-8")
