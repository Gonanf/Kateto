"""Todo-8 tests: look-at SKILL.md plus existing-user backfill.

Covers the source-selection doc contract, fresh-bootstrap presence, the
backfill from vision plugin initialize() (copy-missing + refresh-with-backup
when the bundle diverged), and the adversarial probes (missing file ->
SkillLoadError, underscore name rejected, idempotent).
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
    # Then: second run is a no-op (content + mtime untouched, no backup)
    assert (skill.stat().st_mtime_ns, skill.read_bytes()) == before
    assert list((skill.parent).glob("SKILL.md.bak.*")) == []


def _capture_logs() -> tuple[list[str], int]:
    from loguru import logger

    messages: list[str] = []
    handler_id = logger.add(lambda record: messages.append(record.rstrip("\n")), format="{message}")
    return messages, handler_id


def _stop_capture(handler_id: int) -> None:
    from loguru import logger

    logger.remove(handler_id)


def test_backfill_refreshes_stale_bundled_skill(tmp_path: Path) -> None:
    # Given: a user config holding an outdated bundled skill
    cfg = tmp_path / "cfg"
    skill_dir = cfg / "skills" / "look-at"
    skill_dir.mkdir(parents=True)
    stale = skill_dir / "SKILL.md"
    stale.write_text("# Mine\n", encoding="utf-8")
    messages, handler_id = _capture_logs()
    try:
        result = ensure_shared_skill(cfg, "look-at")
    finally:
        _stop_capture(handler_id)
    # Then: refreshed to the bundled bytes, old content kept in a backup, logged
    assert result == stale
    assert stale.read_bytes() == _defaults_skill().read_bytes()
    backups = sorted(skill_dir.glob("SKILL.md.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "# Mine\n"
    assert "[skills] refreshed look-at (bundled changed)" in messages


def test_backfill_identical_skill_untouched(tmp_path: Path) -> None:
    # Given: a user config whose bundled skill already matches the bundle
    cfg = tmp_path / "cfg"
    skill_dir = cfg / "skills" / "look-at"
    skill_dir.mkdir(parents=True)
    skill = skill_dir / "SKILL.md"
    skill.write_bytes(_defaults_skill().read_bytes())
    before = (skill.stat().st_mtime_ns, skill.read_bytes())
    messages, handler_id = _capture_logs()
    try:
        ensure_shared_skill(cfg, "look-at")
    finally:
        _stop_capture(handler_id)
    # Then: nothing touched, no backup, silent
    assert (skill.stat().st_mtime_ns, skill.read_bytes()) == before
    assert list(skill_dir.glob("SKILL.md.bak.*")) == []
    assert not [message for message in messages if "refreshed look-at" in message]


@pytest.mark.asyncio
async def test_backfill_leaves_user_skill_intact(tmp_path: Path) -> None:
    # Given: a voice-created skill with no bundled source, plus a stale look-at
    cfg = tmp_path / "cfg"
    user_skill = cfg / "skills" / "my-notes" / "SKILL.md"
    user_skill.parent.mkdir(parents=True)
    user_skill.write_text("# My notes\n", encoding="utf-8")
    stale = cfg / "skills" / "look-at" / "SKILL.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("# Mine\n", encoding="utf-8")
    (cfg / "config.toml").write_text('[kateto]\nname = "existing"\n', encoding="utf-8")
    # When: backfilling (direct helper rejects the user skill, plugin path runs)
    with pytest.raises(SkillLoadError):
        ensure_shared_skill(cfg, "my-notes")
    await StaticVisionPlugin(config_dir=cfg).initialize()
    # Then: the user skill is intact (no backup beside it), look-at refreshed
    assert user_skill.read_text(encoding="utf-8") == "# My notes\n"
    assert list(user_skill.parent.glob("SKILL.md.bak.*")) == []
    assert stale.read_bytes() == _defaults_skill().read_bytes()


def test_refresh_is_idempotent(tmp_path: Path) -> None:
    # Given: a stale bundled skill refreshed once already
    cfg = tmp_path / "cfg"
    skill_dir = cfg / "skills" / "look-at"
    skill_dir.mkdir(parents=True)
    skill = skill_dir / "SKILL.md"
    skill.write_text("# Mine\n", encoding="utf-8")
    ensure_shared_skill(cfg, "look-at")
    before = (skill.stat().st_mtime_ns, skill.read_bytes())
    backups_before = sorted(skill_dir.glob("SKILL.md.bak.*"))
    assert len(backups_before) == 1
    # When: running the backfill again twice
    messages, handler_id = _capture_logs()
    try:
        ensure_shared_skill(cfg, "look-at")
        ensure_shared_skill(cfg, "look-at")
    finally:
        _stop_capture(handler_id)
    # Then: no extra backups, content untouched, silent
    assert (skill.stat().st_mtime_ns, skill.read_bytes()) == before
    assert sorted(skill_dir.glob("SKILL.md.bak.*")) == backups_before
    assert not [message for message in messages if "refreshed look-at" in message]


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
