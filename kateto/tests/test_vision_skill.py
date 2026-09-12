"""Todo-8 tests: look-at SKILL.md plus existing-user backfill.

Covers the source-selection doc contract, fresh-bootstrap presence, the
copy-missing backfill from vision plugin initialize(), and the adversarial
probes (missing file -> SkillLoadError, underscore name rejected, idempotent).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from kateto.core.config import bootstrap_config, default_config_dir
from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin
from kateto.voices.skills import SkillLoadError, ensure_shared_skill, load_skills


def _defaults_skill() -> Path:
    return default_config_dir() / "skills" / "look-at" / "SKILL.md"


def test_skill_doc_contract() -> None:
    # Given: the bundled look-at skill doc
    text = _defaults_skill().read_text(encoding="utf-8")
    # Then: plain markdown (no frontmatter) with the source/window/periodic contract
    assert not text.startswith("---")
    assert 'source="auto"' in text
    assert "5s" in text
    assert "periodic" in text.lower()
    assert "camera" in text and "screen" in text


def test_default_voices_list_look_at() -> None:
    # Given: the bundled default config
    raw = tomllib.loads((default_config_dir() / "config.toml").read_text(encoding="utf-8"))
    # Then: all four voices opt into the skill
    for voice in ("jane", "doktor", "conquest", "whisperer"):
        assert "look-at" in raw["voice"][voice]["skills"]
    assert "executor_vision" in raw["plugin"]


def test_bootstrap_contains_look_at_skill(tmp_path: Path) -> None:
    # Given: a fresh target dir bootstrapped from defaults
    target = tmp_path / "cfg"
    # When: bootstrapping
    bootstrap_config(config_dir=target, defaults_dir=default_config_dir())
    # Then: the skill lands with the expected heading
    skill = target / "skills" / "look-at" / "SKILL.md"
    assert skill.is_file()
    assert skill.read_text(encoding="utf-8").startswith("# Look At")


@pytest.mark.asyncio
async def test_backfill_copies_missing_skill(tmp_path: Path) -> None:
    # Given: a pre-existing config dir (bootstrap would early-return) without the skill
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "config.toml").write_text('[kateto]\nname = "existing"\n', encoding="utf-8")
    # When: the vision plugin initializes
    await StaticVisionPlugin(config_dir=cfg).initialize()
    # Then: exactly the skill file appears, nothing else touched
    assert (cfg / "skills" / "look-at" / "SKILL.md").is_file()
    files = {p.relative_to(cfg) for p in cfg.rglob("*") if p.is_file()}
    assert files == {Path("config.toml"), Path("skills/look-at/SKILL.md")}
    loaded = load_skills(config_dir=cfg, names=("look-at",))
    assert loaded[0].instructions.startswith("# Look At")


@pytest.mark.asyncio
async def test_backfill_idempotent(tmp_path: Path) -> None:
    # Given: a config dir that already gained the skill via backfill
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "config.toml").write_text('[kateto]\nname = "existing"\n', encoding="utf-8")
    await StaticVisionPlugin(config_dir=cfg).initialize()
    skill = cfg / "skills" / "look-at" / "SKILL.md"
    before = (skill.stat().st_mtime_ns, skill.read_bytes())
    # When: initializing again
    await StaticVisionPlugin(config_dir=cfg).initialize()
    # Then: second run is a no-op (content + mtime untouched)
    assert (skill.stat().st_mtime_ns, skill.read_bytes()) == before


@pytest.mark.asyncio
async def test_backfill_preserves_existing_file(tmp_path: Path) -> None:
    # Given: a user-customized skill file already in place
    cfg = tmp_path / "cfg"
    skill = cfg / "skills" / "look-at"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Mine\n", encoding="utf-8")
    (cfg / "config.toml").write_text('[kateto]\nname = "existing"\n', encoding="utf-8")
    # When: backfilling (direct helper + plugin path)
    ensure_shared_skill(cfg, "look-at")
    await StaticVisionPlugin(config_dir=cfg).initialize()
    # Then: the custom file is never overwritten
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == "# Mine\n"


@pytest.mark.asyncio
async def test_backfill_disabled_without_config_dir(tmp_path: Path) -> None:
    # Given: the plugin without a config dir (backfill disabled via flag)
    plugin = StaticVisionPlugin()
    # When: initializing (must not raise, must not touch the real user config)
    await plugin.initialize()
    # Then: load still fails loudly, documenting why backfill runs first
    with pytest.raises(SkillLoadError):
        load_skills(config_dir=tmp_path, names=("look-at",))


def test_missing_skill_raises(tmp_path: Path) -> None:
    # Given: a voice listing look-at without the file on disk
    (tmp_path / "skills").mkdir()
    # Then: the strict loader surfaces SkillLoadError
    with pytest.raises(SkillLoadError):
        load_skills(config_dir=tmp_path, names=("look-at",))


def test_underscore_name_rejected(tmp_path: Path) -> None:
    # Given: the underscore spelling of the skill name
    # Then: the [a-z][a-z0-9-]* regex rejects it
    with pytest.raises(SkillLoadError):
        load_skills(config_dir=tmp_path, names=("look_at",))
