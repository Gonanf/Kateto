import asyncio
from unittest.mock import MagicMock

import pytest

from kateto.core.config import VoiceSettings
from kateto.core.event import InterruptData
from kateto.core.manager import PluginManager
from kateto.voices.base import VoiceAgent, VoiceProfile, VoiceRole


@pytest.mark.asyncio
async def test_dept_scoped_interrupt(tmp_path):
    manager = PluginManager()

    profile_fun = VoiceProfile(
        voice_id="jane",
        display_name="Jane",
        role=VoiceRole.ORCHESTRATOR,
        system_prompt="Fun voice",
        relevance_terms=frozenset({"fun"}),
        depts=("fun",),
    )
    profile_mgmt = VoiceProfile(
        voice_id="doktor",
        display_name="Doktor",
        role=VoiceRole.PROJECT_MANAGER,
        system_prompt="Management voice",
        relevance_terms=frozenset({"mgmt"}),
        depts=("management",),
    )

    voice_fun = VoiceAgent(
        profile=profile_fun,
        config_dir=tmp_path,
        provider=MagicMock(),
        settings=VoiceSettings(),
    )
    voice_mgmt = VoiceAgent(
        profile=profile_mgmt,
        config_dir=tmp_path,
        provider=MagicMock(),
        settings=VoiceSettings(),
    )

    await manager.enable_plugin(voice_fun)
    await manager.enable_plugin(voice_mgmt)

    # Set up dummy generation tasks for both voices
    async def long_generation():
        await asyncio.sleep(10)

    task_fun = asyncio.create_task(long_generation())
    task_mgmt = asyncio.create_task(long_generation())

    voice_fun._generation_task = task_fun
    voice_mgmt._generation_task = task_mgmt

    # Emit interrupt scoped to "fun"
    await manager.interrupt(reason="voice_activity", dept="fun")
    await asyncio.sleep(0.05)

    # Assert Fun voice task was cancelled while Management voice task is still running
    assert task_fun.cancelled() or task_fun.done()
    assert not task_mgmt.cancelled() and not task_mgmt.done()

    # Clean up management task
    task_mgmt.cancel()
    try:
        await task_mgmt
    except asyncio.CancelledError:
        pass
