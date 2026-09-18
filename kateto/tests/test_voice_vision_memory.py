from __future__ import annotations

from pathlib import Path

import pytest
from loguru import logger

from kateto.core import PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import VisionDescribeResultData
from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin
from kateto.voices.base import VoiceAgent

from kateto.tests.conversation_support import StreamingFixtureProvider, write_references


def _describe_result() -> VisionDescribeResultData:
    return VisionDescribeResultData(
        text="terminal with code on screen",
        frame_count=5,
        kept_count=3,
        dropped=0,
        window_start=10.0,
        window_end=15.0,
        source="screen",
        via="recap",
    )


@pytest.mark.asyncio
async def test_voice_receives_and_remembers_vision_result(tmp_path: Path) -> None:
    # Given: an enabled voice (subscribed via on_vision_describe_result)
    write_references(tmp_path)
    manager = PluginManager()
    from kateto.voices.factory import _PROFILES

    jane = VoiceAgent(
        profile=_PROFILES["jane"],
        config_dir=tmp_path,
        provider=StreamingFixtureProvider(),
    )
    await manager.enable_plugin(jane)

    # When: a describe result is broadcast (e.g. after the model's own request)
    await manager.emit("vision_describe_result", _describe_result(), source="static_vision")
    await manager.wait_for_idle(timeout=5)

    # Then: the description lands in the voice's memory as a look-at message
    memories = [m.content for m in jane._event_messages]
    assert any(
        "[look-at screen 5s]" in content and "terminal with code" in content
        for content in memories
    ), memories

    await manager.close()


@pytest.mark.asyncio
async def test_vision_enable_warns_without_optin_or_backend() -> None:
    # Given: vision enabled with no opted-in voice and no VLM endpoint
    manager = PluginManager()
    plugin = StaticVisionPlugin(PluginSettings(enabled=True))
    manager.register_plugin(plugin)

    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        # When: enabling
        await manager.enable_plugin(plugin)
    finally:
        logger.remove(handler_id)

    # Then: actionable warnings name the missing pieces
    joined = "\n".join(messages)
    assert "vision_periodic=true" in joined
    assert "video-rag" in joined

    await manager.close()


@pytest.mark.asyncio
async def test_vision_enable_quiet_with_optin_and_backend(tmp_path: Path) -> None:
    # Given: an opted-in voice and a primary VLM endpoint
    manager = PluginManager()
    plugin = StaticVisionPlugin(
        PluginSettings(enabled=True, vision_endpoint="http://127.0.0.1:8092/v1", vision_model="vlm"),
        opted_in=(("jane", "30s"),),
        config_dir=tmp_path,
    )
    manager.register_plugin(plugin)

    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        await manager.enable_plugin(plugin)
    finally:
        logger.remove(handler_id)

    # Then: no vision warnings (scheduler may error on unknown voice, which is fine)
    assert not [m for m in messages if m.startswith("[vision]")]

    await manager.close()
