from __future__ import annotations

from pathlib import Path

import pytest

from kateto.core.soul_store import (
    JsonlAuditBackend,
    ZodBackend,
    open_soul_snapshot_store,
)
from kateto.voices.base import VoiceAgent
from kateto.voices.memory import VoiceMemory

from kateto.tests.conversation_support import StreamingFixtureProvider, write_references


@pytest.mark.asyncio
async def test_zod_backend_snapshot_and_rollback(tmp_path: Path) -> None:
    # Given: a ZODB snapshot backend for voice "jane"
    backend = ZodBackend(tmp_path)
    # When: two snapshots are taken
    backend.snapshot("jane", "soul", "first")
    backend.snapshot("jane", "soul", "second")
    # Then: rollback restores the previous content, twice
    assert backend.rollback("jane", "soul") == "second"
    assert backend.rollback("jane", "soul") == "first"
    assert backend.rollback("jane", "soul") is None


@pytest.mark.asyncio
async def test_zod_backend_caps_stack_depth(tmp_path: Path) -> None:
    # Given: a ZODB backend with max_depth=2
    backend = ZodBackend(tmp_path, max_depth=2)
    # When: three snapshots are taken
    backend.snapshot("jane", "soul", "v1")
    backend.snapshot("jane", "soul", "v2")
    backend.snapshot("jane", "soul", "v3")
    # Then: only the two most recent are retained
    assert backend.rollback("jane", "soul") == "v3"
    assert backend.rollback("jane", "soul") == "v2"
    assert backend.rollback("jane", "soul") is None


@pytest.mark.asyncio
async def test_zod_backend_isolates_keys(tmp_path: Path) -> None:
    # Given: a ZODB backend
    backend = ZodBackend(tmp_path)
    # When: soul and journal snapshots are interleaved
    backend.snapshot("jane", "soul", "s1")
    backend.snapshot("jane", "journal", "j1")
    # Then: rollback of one key does not affect the other
    assert backend.rollback("jane", "soul") == "s1"
    assert backend.rollback("jane", "journal") == "j1"


@pytest.mark.asyncio
async def test_jsonl_backend_snapshot_and_rollback(tmp_path: Path) -> None:
    # Given: a JSONL audit backend
    backend = JsonlAuditBackend(tmp_path)
    # When: two snapshots are taken
    backend.snapshot("jane", "soul", "first")
    backend.snapshot("jane", "soul", "second")
    # Then: rollback replays the last snapshot
    assert backend.rollback("jane", "soul") == "second"
    # And: a second rollback replays the one before
    assert backend.rollback("jane", "soul") == "first"


@pytest.mark.asyncio
async def test_open_soul_snapshot_store_prefers_zodb(tmp_path: Path) -> None:
    # Given: zodb is importable in the environment
    # When: the factory is asked for the default backend
    backend = open_soul_snapshot_store(tmp_path)
    # Then: it returns a ZODB backend
    assert isinstance(backend, ZodBackend)


@pytest.mark.asyncio
async def test_write_soul_snapshots_previous_content(tmp_path: Path) -> None:
    # Given: voice memory over a temp config dir
    memory = VoiceMemory.for_voice(config_dir=tmp_path, voice="jane")
    # When: the soul is written twice
    await memory.write_soul("v1")
    await memory.write_soul("v2")
    # Then: rollback restores the previous content and persists it
    restored = await memory.rollback_soul()
    assert restored == "v1"
    assert await memory.read_soul() == "v1"


@pytest.mark.asyncio
async def test_append_journal_snapshots_previous_content(tmp_path: Path) -> None:
    # Given: voice memory over a temp config dir
    memory = VoiceMemory.for_voice(config_dir=tmp_path, voice="jane")
    # When: journal entries are appended
    await memory.append_journal("entry one")
    await memory.append_journal("entry two")
    # Then: rollback restores the previous journal
    restored = await memory.rollback_journal()
    assert restored == "entry one"
    assert await memory.read_journal() == "entry one"


@pytest.mark.asyncio
async def test_memory_rollback_isolates_soul_and_journal(tmp_path: Path) -> None:
    # Given: voice memory over a temp config dir
    memory = VoiceMemory.for_voice(config_dir=tmp_path, voice="jane")
    # When: soul and journal are both updated twice
    await memory.write_soul("soul-v1")
    await memory.write_soul("soul-v2")
    await memory.append_journal("journal-v1")
    await memory.append_journal("journal-v2")
    # Then: rolling back the soul does not touch the journal
    assert await memory.rollback_soul() == "soul-v1"
    assert await memory.rollback_journal() == "journal-v1"


@pytest.mark.asyncio
async def test_messages_for_rolls_back_empty_soul(tmp_path: Path) -> None:
    # Given: a voice with a valid soul followed by an empty write
    write_references(tmp_path)
    from kateto.voices.factory import _PROFILES
    voice = VoiceAgent(
        profile=_PROFILES["jane"],
        config_dir=tmp_path,
        provider=StreamingFixtureProvider(),
    )
    await voice._memory.write_soul("my real soul")
    await voice._memory.write_soul("")
    # When: the prompt context is built
    messages = await voice._messages_for("hi", workflow=None, phase_id=None)
    # Then: the soul is restored from the snapshot, not empty
    joined = "\n".join(message.content for message in messages)
    assert "my real soul" in joined
