from unittest.mock import MagicMock

import pytest

from kateto.core.event import TextChunk, TranscriptionData
from kateto.core.manager import PluginManager
from kateto.plugins.executor.memory_sink_plugin import MemorySinkPlugin


@pytest.mark.asyncio
async def test_memory_sink_stores_and_queries(tmp_path):
    manager = PluginManager()
    plugin = MemorySinkPlugin(config_dir=tmp_path)

    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()

    plugin.add_memory("Project release deadline is next Monday", voice="jane", event_type="transcription", dept="fun")
    plugin.add_memory("Database maintenance scheduled at midnight", voice="doktor", event_type="transcription", dept="management")

    results = plugin.query_memory("release deadline", top_k=2)
    assert len(results) >= 1
    assert "release deadline" in results[0]

    await manager.disable_plugin(plugin.name)
