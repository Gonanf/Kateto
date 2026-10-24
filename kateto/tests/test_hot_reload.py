from __future__ import annotations

import importlib
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
    # Given: a real importable module in sys.path
    controller, _ = _make_controller(tmp_path)
    module_path = tmp_path / "hr_fake_plugin.py"
    module_path.write_text("VALUE = 1\n", encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        module = importlib.import_module("hr_fake_plugin")
        # When: the module's source file changes
        module_path.write_text("VALUE = 2\n", encoding="utf-8")
        await controller.handle_change(module_path)
        # Then: the module remains in sys.modules as the same object and was reloaded in-place
        assert "hr_fake_plugin" in sys.modules
        assert sys.modules["hr_fake_plugin"] is module
        assert getattr(module, "VALUE") == 2
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("hr_fake_plugin", None)


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
    reloaded = controller._reload_plugins(other)
    # Then: the unrelated module is untouched
    assert reloaded is False
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


def _count_class_copies(module_name: str, qualname: str) -> set[int]:
    copies: set[int] = set()
    for mod in sys.modules.values():
        if mod is None:
            continue
        for obj in getattr(mod, "__dict__", {}).values():
            if (
                getattr(obj, "__module__", None) == module_name
                and getattr(obj, "__qualname__", None) == qualname
            ):
                copies.add(id(obj))
    return copies


@pytest.mark.asyncio
async def test_reload_leaves_a_single_copy_of_the_class(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a hermetic package pkg with module-level import in __init__.py and function import in create_plugins
    pkg_dir = tmp_path / "pkg_identity"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text(
        "from .plugin import DemoPlugin\n\n"
        "def create_plugins(ctx=None):\n"
        "    from .plugin import DemoPlugin\n"
        "    return [DemoPlugin()]\n",
        encoding="utf-8",
    )
    plugin_py = pkg_dir / "plugin.py"
    plugin_py.write_text(
        "from kateto.core.plugin import Plugin\n\n"
        "REGISTRY = []\n\n"
        "class DemoPlugin(Plugin):\n"
        "    def __init__(self):\n"
        "        super().__init__('demo_plugin')\n"
        "        self.registry = REGISTRY\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        import pkg_identity
        from kateto.core.discovery import PluginRegistry

        controller, _ = _make_controller(tmp_path)
        monkeypatch.setattr(
            "kateto.core.hot_reload.discover_plugins",
            lambda ctx: PluginRegistry(plugins=frozenset(pkg_identity.create_plugins(ctx))),
        )
        await controller._refresh(controller._config)

        # When: pkg_identity/plugin.py is edited and handle_change is called
        plugin_py.write_text(
            "from kateto.core.plugin import Plugin\n\n"
            "REGISTRY = []\n\n"
            "class DemoPlugin(Plugin):\n"
            "    def __init__(self):\n"
            "        super().__init__('demo_plugin')\n"
            "        self.registry = REGISTRY\n"
            "# edited\n",
            encoding="utf-8",
        )
        await controller.handle_change(plugin_py)

        # Then: exactly 1 copy of DemoPlugin exists across all sys.modules and isinstance is True
        copies = _count_class_copies("pkg_identity.plugin", "DemoPlugin")
        assert len(copies) == 1
        instancia_nueva = controller.manager.get_plugins()[0]
        assert isinstance(instancia_nueva, pkg_identity.DemoPlugin)
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("pkg_identity.plugin", None)
        sys.modules.pop("pkg_identity", None)


@pytest.mark.asyncio
async def test_reload_keeps_a_single_singleton(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a hermetic package pkg defining REGISTRY: list at module level
    pkg_dir = tmp_path / "pkg_singleton"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text(
        "from .plugin import DemoPlugin\n"
        "from .plugin import REGISTRY\n\n"
        "def create_plugins(ctx=None):\n"
        "    from .plugin import DemoPlugin\n"
        "    return [DemoPlugin()]\n",
        encoding="utf-8",
    )
    plugin_py = pkg_dir / "plugin.py"
    plugin_py.write_text(
        "from kateto.core.plugin import Plugin\n\n"
        "REGISTRY = []\n\n"
        "class DemoPlugin(Plugin):\n"
        "    def __init__(self):\n"
        "        super().__init__('demo_plugin')\n"
        "        self.registry = REGISTRY\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        import pkg_singleton
        from kateto.core.discovery import PluginRegistry

        controller, _ = _make_controller(tmp_path)
        monkeypatch.setattr(
            "kateto.core.hot_reload.discover_plugins",
            lambda ctx: PluginRegistry(plugins=frozenset(pkg_singleton.create_plugins(ctx))),
        )
        await controller._refresh(controller._config)

        # When: pkg_singleton/plugin.py is edited
        plugin_py.write_text(
            "from kateto.core.plugin import Plugin\n\n"
            "REGISTRY = []\n\n"
            "class DemoPlugin(Plugin):\n"
            "    def __init__(self):\n"
            "        super().__init__('demo_plugin')\n"
            "        self.registry = REGISTRY\n"
            "# edited\n",
            encoding="utf-8",
        )
        await controller.handle_change(plugin_py)

        # Then: cascade reload re-binds REGISTRY in the importer module to prevent duplicate singleton instances
        live_plugin = controller.manager.get_plugins()[0]
        assert live_plugin.registry is pkg_singleton.REGISTRY
        assert pkg_singleton.REGISTRY is sys.modules["pkg_singleton.plugin"].REGISTRY
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("pkg_singleton.plugin", None)
        sys.modules.pop("pkg_singleton", None)


@pytest.mark.asyncio
async def test_reload_survives_a_broken_intermediate_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a hermetic package pkg and active controller
    pkg_dir = tmp_path / "pkg_syntax"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text(
        "from .plugin import DemoPlugin\n\n"
        "def create_plugins(ctx=None):\n"
        "    from .plugin import DemoPlugin\n"
        "    return [DemoPlugin()]\n",
        encoding="utf-8",
    )
    plugin_py = pkg_dir / "plugin.py"
    plugin_py.write_text(
        "from kateto.core.plugin import Plugin\n\n"
        "REGISTRY = []\n\n"
        "class DemoPlugin(Plugin):\n"
        "    def __init__(self):\n"
        "        super().__init__('demo_plugin')\n"
        "        self.registry = REGISTRY\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        import pkg_syntax
        from kateto.core.discovery import PluginRegistry

        controller, _ = _make_controller(tmp_path)
        monkeypatch.setattr(
            "kateto.core.hot_reload.discover_plugins",
            lambda ctx: PluginRegistry(plugins=frozenset(pkg_syntax.create_plugins(ctx))),
        )
        await controller._refresh(controller._config)

        # When: writing broken syntax (simulating intermediate save)
        plugin_py.write_text("class DemoPlugin(Plugin):\n    def ((invalid\n", encoding="utf-8")
        # handle_change must NOT raise
        await controller.handle_change(plugin_py)

        # Then: module remains in sys.modules
        assert "pkg_syntax.plugin" in sys.modules

        # When: writing valid code afterwards
        plugin_py.write_text(
            "from kateto.core.plugin import Plugin\n\n"
            "REGISTRY = []\n\n"
            "class DemoPlugin(Plugin):\n"
            "    def __init__(self):\n"
            "        super().__init__('demo_plugin')\n"
            "        self.registry = REGISTRY\n"
            "# recovered\n",
            encoding="utf-8",
        )
        await controller.handle_change(plugin_py)

        # Then: plugin is loaded and class copy is unique again
        copies = _count_class_copies("pkg_syntax.plugin", "DemoPlugin")
        assert len(copies) == 1
        live_plugin = controller.manager.get_plugins()[0]
        assert isinstance(live_plugin, pkg_syntax.DemoPlugin)
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("pkg_syntax.plugin", None)
        sys.modules.pop("pkg_syntax", None)


@pytest.mark.asyncio
async def test_fifty_consecutive_edits_do_not_crash_or_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a hermetic package pkg and active controller
    pkg_dir = tmp_path / "pkg_fifty"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text(
        "from .plugin import DemoPlugin\n\n"
        "def create_plugins(ctx=None):\n"
        "    from .plugin import DemoPlugin\n"
        "    return [DemoPlugin()]\n",
        encoding="utf-8",
    )
    plugin_py = pkg_dir / "plugin.py"
    plugin_py.write_text(
        "from kateto.core.plugin import Plugin\n\n"
        "REGISTRY = []\n\n"
        "class DemoPlugin(Plugin):\n"
        "    def __init__(self):\n"
        "        super().__init__('demo_plugin')\n"
        "        self.registry = REGISTRY\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        import pkg_fifty
        from kateto.core.discovery import PluginRegistry

        controller, _ = _make_controller(tmp_path)
        monkeypatch.setattr(
            "kateto.core.hot_reload.discover_plugins",
            lambda ctx: PluginRegistry(plugins=frozenset(pkg_fifty.create_plugins(ctx))),
        )
        await controller._refresh(controller._config)

        # When: performing 50 consecutive edits
        for i in range(50):
            plugin_py.write_text(
                "from kateto.core.plugin import Plugin\n\n"
                f"REGISTRY = [{i}]\n\n"
                "class DemoPlugin(Plugin):\n"
                "    def __init__(self):\n"
                "        super().__init__('demo_plugin')\n"
                "        self.registry = REGISTRY\n"
                f"# edit {i}\n",
                encoding="utf-8",
            )
            await controller.handle_change(plugin_py)
            copies = _count_class_copies("pkg_fifty.plugin", "DemoPlugin")
            assert len(copies) == 1

        # Then: count remains 1 and live plugin has the latest registry
        live_plugin = controller.manager.get_plugins()[0]
        assert live_plugin.registry == [49]
        assert live_plugin.registry is sys.modules["pkg_fifty.plugin"].REGISTRY
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("pkg_fifty.plugin", None)
        sys.modules.pop("pkg_fifty", None)


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
        reload_fn = getattr(controller, "_reload_plugins", None) or getattr(controller, "_purge_plugins", None)
        if reload_fn:
            reload_fn(plugin_path)
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
        reload_fn = getattr(controller, "_reload_plugins", None) or getattr(controller, "_purge_plugins", None)
        if reload_fn:
            reload_fn(plugin_path)
        restored_text = plugin_path.read_text(encoding="utf-8")
        if restored_text != original_text:
            pytest.fail(f"Failed to restore {plugin_path} to its original content")
