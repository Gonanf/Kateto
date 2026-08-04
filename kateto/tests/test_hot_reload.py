from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from kateto.core.hot_reload import HotReloadController
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin


def _write_config(config_dir: Path, *, extra: str = "") -> Path:
    config_path = config_dir / "config.toml"
    config_path.write_text(
        """
[kateto]

[plugin.audio_output_player]
enabled = true

[plugin.executor_classifier]
enabled = true
model_endpoint = "http://127.0.0.1:8091"
model = "fixture-classifier"

[plugin.audio_input_mic]
enabled = true
sample_rate = 16000
silence_timeout = 0.1
vad_model = "silero"

[plugin.voice_llm]
enabled = true
endpoint = "http://127.0.0.1:8092/v1"
model = "fixture-voice"

[plugin.executor_todo_list]
enabled = true

[plugin.audio_output_zonos]
enabled = true
endpoint = "http://127.0.0.1:8093"

[plugin.audio_processor_whisper]
enabled = true
endpoint = "http://127.0.0.1:8090"

[plugin.executor_interrupt]
enabled = true

[voice.doktor]
enabled = true

[cli]
allowlist = ["echo"]
"""
        + extra
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _make_controller(tmp_path: Path) -> HotReloadController:
    from kateto.core.config import load_config
    from kateto.core.discovery import DiscoveryContext, discover_plugins

    shared: dict[str, object] = {}
    config = load_config(config_dir=tmp_path)
    manager = PluginManager()
    shared["manager"] = manager
    registry = discover_plugins(DiscoveryContext(config=config, shared=shared))
    return HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        config=config,
        shared=shared,
    ), tuple(registry.plugins)


@pytest.mark.asyncio
async def test_hot_reload_ignores_non_watched_suffix(tmp_path: Path) -> None:
    # Given: a controller over a temp config dir
    controller, _ = _make_controller(tmp_path)
    # When: a non-watched file changes
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    await controller.handle_change(tmp_path / "notes.txt")
    # Then: nothing crashes and no reload occurred
    assert controller._config is not None


@pytest.mark.asyncio
async def test_hot_reload_purges_module_for_changed_py(tmp_path: Path) -> None:
    # Given: a fake module registered in sys.modules pointing at a temp file
    controller, _ = _make_controller(tmp_path)
    module_path = tmp_path / "plugin.py"
    module_path.write_text("VALUE = 1\n", encoding="utf-8")
    module = ModuleType("_hot_reload_fake_plugin")
    module.__file__ = str(module_path)
    sys.modules["_hot_reload_fake_plugin"] = module
    # When: the module's source file changes
    purged = controller._purge_plugins(module_path)
    # Then: the module is purged so re-import picks up the new code
    assert purged is True
    assert "_hot_reload_fake_plugin" not in sys.modules
    sys.modules.pop("_hot_reload_fake_plugin", None)


@pytest.mark.asyncio
async def test_hot_reload_does_not_purge_unrelated_modules(tmp_path: Path) -> None:
    # Given: a controller and an unrelated module
    controller, _ = _make_controller(tmp_path)
    module = ModuleType("_hot_reload_unrelated")
    module.__file__ = str(tmp_path / "unrelated.py")
    sys.modules["_hot_reload_unrelated"] = module
    other = tmp_path / "other.py"
    other.write_text("", encoding="utf-8")
    # When: a different file changes
    purged = controller._purge_plugins(other)
    # Then: the unrelated module is untouched
    assert purged is False
    assert "_hot_reload_unrelated" in sys.modules
    sys.modules.pop("_hot_reload_unrelated", None)


@pytest.mark.asyncio
async def test_hot_reload_keeps_unchanged_plugin_instances(tmp_path: Path) -> None:
    # Given: plugins discovered from config and enabled
    controller, plugins = _make_controller(tmp_path)
    for plugin in plugins:
        await controller.manager.enable_plugin(plugin)
    enabled = [plugin for plugin in controller.manager.get_plugins() if plugin.enabled]
    assert enabled
    # When: the same config file is touched (no class change)
    await controller.handle_change(tmp_path / "config.toml")
    # Then: plugin instances are not replaced (bug #15: no unnecessary replacement)
    current = {plugin.name: plugin for plugin in controller.manager.get_plugins()}
    for plugin in enabled:
        assert current[plugin.name] is plugin


@pytest.mark.asyncio
async def test_hot_reload_emits_error_on_missing_config(tmp_path: Path) -> None:
    # Given: a controller whose config file is deleted
    controller, _ = _make_controller(tmp_path)
    (tmp_path / "config.toml").unlink()
    received: list[object] = []
    manager = controller.manager

    class _Collector(Plugin):
        def __init__(self) -> None:
            super().__init__("collector")

        async def on_error(self, data: object) -> None:
            received.append(data)

    collector = _Collector()
    await manager.enable_plugin(collector)
    # When: the missing config file "changes"
    await controller.handle_change(tmp_path / "config.toml")
    await manager.wait_for_idle(timeout=5)
    # Then: an error event is emitted and the bus stays up
    assert len(received) == 1
    assert "config.toml" in str(received[0])
