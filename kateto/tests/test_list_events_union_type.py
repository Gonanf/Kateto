import json

import pytest

from kateto.core.event import GenerateData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.voices.tools import VoiceToolExecutor


class _Stub(Plugin):
    async def on_generate(self, data: GenerateData) -> None:
        return None


@pytest.mark.asyncio
async def test_list_events_survives_union_type_annotations(tmp_path):
    # Given: an event contract with `str | None` fields (types.UnionType, no __name__)
    manager = PluginManager()
    await manager.enable_plugin(_Stub("stub"))
    manager.register_event("generate", GenerateData)

    executor = VoiceToolExecutor(config_dir=tmp_path)
    executor.set_manager(manager)

    # When: list_events inspects the contract fields
    result = json.loads(await executor.execute("list_events", {}))

    # Then: it renders the union types instead of raising AttributeError
    assert result["events"], "expected at least one registered event"
    generate = next(event for event in result["events"] if event["name"] == "generate")
    assert generate["fields"]["prompt"]["type"] == "str | None"
