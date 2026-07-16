from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from kateto.core.storage import PathIsolationError, VoiceFileStore, atomic_write_text


@pytest.mark.asyncio
async def test_atomic_write_keeps_concurrent_payloads_whole_and_releases_lock(tmp_path: Path) -> None:
    # Given: many competing complete payloads for one file.
    target = tmp_path / "product_backlog.json"
    payloads = [f'{{"writer": {index}, "body": "{"x" * 16_384}"}}\n' for index in range(24)]

    # When: writers race through the bounded per-file async lock.
    await asyncio.wait_for(
        asyncio.gather(*(atomic_write_text(target, payload) for payload in payloads)),
        timeout=5,
    )

    # Then: the final file is one complete write and no temporary artifacts remain.
    assert target.read_text(encoding="utf-8") in payloads
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


@pytest.mark.asyncio
async def test_voice_store_rejects_cross_voice_path_and_preserves_other_voice_file(tmp_path: Path) -> None:
    # Given: a Jane-scoped store and an existing Doktor private file.
    doktor_soul = tmp_path / "voices" / "Doktor" / "SOUL.md"
    doktor_soul.parent.mkdir(parents=True)
    doktor_soul.write_text("doktor-private", encoding="utf-8")
    jane_store = VoiceFileStore.for_voice(config_dir=tmp_path, voice="Jane")

    # When: Jane attempts a traversal into Doktor's directory.
    with pytest.raises(PathIsolationError):
        await jane_store.write_text("../Doktor/SOUL.md", "overwrite")

    # Then: Doktor's file remains unchanged while Jane can write only her own file.
    assert doktor_soul.read_text(encoding="utf-8") == "doktor-private"
    await jane_store.write_text("SOUL.md", "jane-private")
    assert (tmp_path / "voices" / "Jane" / "SOUL.md").read_text(encoding="utf-8") == "jane-private"


@pytest.mark.asyncio
async def test_voice_store_rejects_symlinked_voice_root_outside_config(tmp_path: Path) -> None:
    # Given: a voice directory symlinked to a location outside the config root.
    config_dir = tmp_path / "config"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    voice_link = config_dir / "voices" / "Jane"
    voice_link.parent.mkdir(parents=True)
    try:
        voice_link.symlink_to(outside_dir, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink fixture unavailable: {error}")

    # When: Jane attempts to write through the symlinked store.
    with pytest.raises(PathIsolationError):
        await VoiceFileStore.for_voice(config_dir=config_dir, voice="Jane").write_text("SOUL.md", "escaped")

    # Then: the outside location never receives the attempted private file.
    assert not (outside_dir / "SOUL.md").exists()
