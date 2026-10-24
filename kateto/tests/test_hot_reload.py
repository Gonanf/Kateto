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


@pytest.mark.asyncio
async def test_hot_reload_default_source_roots_include_plugins_and_voices(tmp_path: Path) -> None:
    # Given: default_source_roots and a controller without explicit source_roots
    from kateto.core.hot_reload import default_source_roots

    defaults = default_source_roots()
    assert len(defaults) == 2
    for root in defaults:
        assert root.is_dir()
        assert root.exists()

    manager = PluginManager()
    controller = HotReloadController(manager=manager, watched_root=tmp_path)

    # Then: controller.source_roots resolves default_source_roots with plugins and voices
    assert controller.source_roots == tuple(root.resolve() for root in defaults)
    assert any(root.name == "plugins" for root in controller.source_roots)
    assert any(root.name == "voices" for root in controller.source_roots)


@pytest.mark.asyncio
async def test_hot_reload_run_mode_source_roots_include_plugins_and_voices(tmp_path: Path) -> None:
    # Given: default_source_roots and RuntimeOwner configured with hot_reload = true
    from kateto.core.config import load_config
    from kateto.core.hot_reload import default_source_roots
    from kateto.run_mode import RuntimeComponents, RuntimeOwner

    expected_roots = tuple(root.resolve() for root in default_source_roots())
    assert len(expected_roots) == 2
    for root in expected_roots:
        assert root.is_dir()
        assert root.exists()

    _write_config(tmp_path)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        cfg_file.read_text(encoding="utf-8").replace("[kateto]", "[kateto]\nhot_reload = true\n"),
        encoding="utf-8",
    )
    config = load_config(config_dir=tmp_path)
    manager = PluginManager()
    components = RuntimeComponents(plugins=(), mcp_servers=(), workflow_voices=())
    owner = RuntimeOwner(
        manager=manager,
        plugins=(),
        components=components,
        config=config,
    )

    # When: RuntimeOwner starts with hot_reload enabled
    await owner.start()
    try:
        # Then: controller created in run_mode references default_source_roots by behavior
        assert owner._hot_reload is not None
        assert owner._hot_reload.source_roots == expected_roots
        for root in owner._hot_reload.source_roots:
            assert root.is_dir()
            assert root.exists()
    finally:
        await owner.stop()


@pytest.mark.asyncio
async def test_hot_reload_ignores_toml_that_is_not_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a controller with discover_plugins spy
    _write_config(tmp_path)
    controller, _ = _make_controller(tmp_path)
    notes_file = tmp_path / "notes.toml"
    notes_file.write_text("title = 'Notes'\n", encoding="utf-8")

    calls = 0
    import kateto.core.hot_reload

    real_discover = kateto.core.hot_reload.discover_plugins

    def spy_discover(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_discover(*args, **kwargs)

    monkeypatch.setattr(kateto.core.hot_reload, "discover_plugins", spy_discover)

    # When: a .toml file that is not config changes
    await controller.handle_change(notes_file)

    # Then: discover_plugins is not triggered (0 calls)
    assert calls == 0


@pytest.mark.asyncio
async def test_hot_reload_voice_toml_change_reloads_config(tmp_path: Path) -> None:
    # Given: a controller with loaded config, and a voice.toml in voices/<voice>/
    _write_config(tmp_path)
    controller, _ = _make_controller(tmp_path)
    old_config = controller._config
    assert old_config is not None

    voice_dir = tmp_path / "voices" / "doktor"
    voice_dir.mkdir(parents=True, exist_ok=True)
    voice_toml = voice_dir / "voice.toml"
    voice_toml.write_text("[doktor]\nenabled = true\n", encoding="utf-8")

    # When: voice.toml changes and _reload_config is called
    new_config = controller._reload_config(voice_toml)

    # Then: a new LoadedConfig object is returned and controller._config is updated
    assert new_config is not None
    assert new_config is not old_config
    assert controller._config is new_config


@pytest.mark.asyncio
async def test_hot_reload_real_plugin_edit_replaces_live_instance(tmp_path: Path) -> None:
    import subprocess

    plugin_path = Path(__file__).resolve().parent.parent / "plugins" / "executor" / "todo_list.py"
    status = subprocess.run(
        ["git", "status", "--porcelain", str(plugin_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    if status.stdout.strip():
        pytest.skip(f"{plugin_path} has uncommitted changes, skipping live file test")

    original_text = plugin_path.read_text(encoding="utf-8")

    _write_config(tmp_path)
    controller, plugins = _make_controller(tmp_path)
    for p in plugins:
        await controller.manager.enable_plugin(p)

    active_before = next(
        (p for p in controller.manager.get_plugins() if p.name == "executor_todo_list"),
        None,
    )
    assert active_before is not None

    try:
        # When: append a comment to the real plugin source file
        plugin_path.write_text(
            original_text + "\n# hot reload test edit\n",
            encoding="utf-8",
        )
        await controller.handle_change(plugin_path)

        # Then: active plugin is replaced by an instance of a different class
        active_after = next(
            (p for p in controller.manager.get_plugins() if p.name == "executor_todo_list"),
            None,
        )
        assert active_after is not None
        assert active_after is not active_before
        assert type(active_after) is not type(active_before)
    finally:
        plugin_path.write_text(original_text, encoding="utf-8")
        controller._purge_plugins(plugin_path)
        restored_text = plugin_path.read_text(encoding="utf-8")
        if restored_text != original_text:
            pytest.fail(f"Failed to restore {plugin_path} to its original content")


@pytest.mark.asyncio
async def test_hot_reload_watcher_fires_on_source_root_edit(tmp_path: Path) -> None:
    import asyncio
    import subprocess

    plugin_path = Path(__file__).resolve().parent.parent / "plugins" / "executor" / "todo_list.py"
    status = subprocess.run(
        ["git", "status", "--porcelain", str(plugin_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    if status.stdout.strip():
        pytest.skip(f"{plugin_path} has uncommitted changes, skipping live file test")

    original_text = plugin_path.read_text(encoding="utf-8")

    _write_config(tmp_path)
    controller, plugins = _make_controller(tmp_path)
    for p in plugins:
        await controller.manager.enable_plugin(p)

    active_before = next(
        (p for p in controller.manager.get_plugins() if p.name == "executor_todo_list"),
        None,
    )
    assert active_before is not None

    await controller.start()
    await asyncio.sleep(0.5)
    try:
        # When: editing the real plugin in source_roots while awatch is running
        plugin_path.write_text(
            original_text + "\n# hot reload watcher test edit\n",
            encoding="utf-8",
        )

        # Wait up to 10s for the live instance to change class
        deadline = asyncio.get_event_loop().time() + 10.0
        reloaded = False
        while asyncio.get_event_loop().time() < deadline:
            active_now = next(
                (p for p in controller.manager.get_plugins() if p.name == "executor_todo_list"),
                None,
            )
            if active_now is not None and type(active_now) is not type(active_before):
                reloaded = True
                break
            await asyncio.sleep(0.1)

        assert reloaded, "Watcher did not trigger plugin reload within 10 seconds"
    finally:
        await controller.close()
        plugin_path.write_text(original_text, encoding="utf-8")
        controller._purge_plugins(plugin_path)
        restored_text = plugin_path.read_text(encoding="utf-8")
        if restored_text != original_text:
            pytest.fail(f"Failed to restore {plugin_path} to its original content")
