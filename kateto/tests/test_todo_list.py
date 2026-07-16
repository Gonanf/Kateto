from __future__ import annotations

from pathlib import Path

import pytest

from kateto.core import PluginManager
from kateto.core.event import Classification, ClassificationData, TodoItemData
from kateto.plugins.executor import TodoListExecutor


@pytest.mark.asyncio
async def test_todo_executor_without_voice_uses_shared_storage_and_event_voice(tmp_path: Path) -> None:
    # Given: a TODO executor assembled without a voice-specific production setting.
    manager = PluginManager()
    executor = TodoListExecutor(config_dir=tmp_path)
    await manager.enable_plugin(executor)
    try:
        # When: an executable TODO classification is received.
        await manager.emit(
            "classification",
            ClassificationData(text="plan shared task", category=Classification.EXECUTE),
            source="executor_classifier",
        )
        await manager.wait_for_idle()

        # Then: the shared TODO surface and typed event carry the same neutral identity.
        assert (tmp_path / "voices" / "shared" / "TODO.md").read_text(encoding="utf-8") == (
            "# TODO\n\n- [ ] shared task\n"
        )
        updates = [event.data for event in manager.get_events() if event.name == "todo_updated"]
        assert updates == [TodoItemData(voice="shared", task="shared task", completed=False)]
    finally:
        await manager.close()
