from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import watchfiles

from kateto.core.config import ConfigError, LoadedConfig, load_config
from kateto.core.discovery import DiscoveryContext, discover_plugins
from kateto.core.event import PluginErrorData
from kateto.core.plugin import Plugin
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin

_WATCHED_SUFFIXES: Final = frozenset({".py", ".toml"})
_DEBOUNCE_MS: Final = 300


class HotReloadController:
    """Watches plugin/config files and swaps changed plugins on the live bus.

    Modules are reloaded in-place in sys.modules and cascade-rebound to importers;
    plugins are replaced only when their class changed.
    """

    def __init__(
        self,
        *,
        manager: PluginManager,
        watched_root: Path,
        source_roots: tuple[Path, ...] = (),
        config: LoadedConfig | None = None,
        shared: dict[str, Any] | None = None,
        debounce_ms: int = _DEBOUNCE_MS,
    ) -> None:
        self.manager = manager
        self.watched_root = watched_root.resolve()
        self.source_roots = tuple(root.resolve() for root in source_roots)
        self._config = config
        self._shared = shared or {}
        self._debounce_ms = debounce_ms
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._watch())

    async def close(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            await task

    async def _watch(self) -> None:
        roots = (self.watched_root, *self.source_roots)
        async for changes in watchfiles.awatch(
            *roots,
            debounce=self._debounce_ms,
            stop_event=self._stop,
        ):
            for _, raw_path in changes:
                await self.handle_change(Path(raw_path))

    async def handle_change(self, path: Path) -> None:
        if path.suffix.casefold() not in _WATCHED_SUFFIXES:
            return
        try:
            config = self._reload_config(path)
            changed = self._reload_plugins(path)
            if not changed and config is None:
                return
            await self._refresh(config)
        except Exception as error:
            await self._emit_error(error)

    def _reload_config(self, path: Path) -> LoadedConfig | None:
        if path.name != "config.toml":
            return self._config
        config_path = self.watched_root / "config.toml"
        if not config_path.is_file():
            raise ConfigError("config.toml is missing after change")
        self._config = load_config(config_dir=self.watched_root)
        return self._config

    def _reload_plugins(self, path: Path) -> bool:
        if path.suffix.casefold() != ".py":
            return False
        importlib.invalidate_caches()
        target = path.resolve()
        matching_mods: list[ModuleType] = []
        for name in tuple(sys.modules):
            mod = sys.modules.get(name)
            if mod is None:
                continue
            module_file = getattr(mod, "__file__", None)
            if isinstance(module_file, str):
                try:
                    if Path(module_file).resolve() == target:
                        matching_mods.append(mod)
                except (OSError, ValueError):
                    continue
        if not matching_mods:
            return False
        for mod in matching_mods:
            self._reload_module(mod)
            self._cascade_reload(mod)
        return True

    def _reload_module(self, mod: ModuleType) -> None:
        importlib.invalidate_caches()
        file_path = getattr(mod, "__file__", None)
        if file_path:
            # importlib.reload compara mtime+size del bytecode cacheado: dos guardados en el mismo
            # segundo con el mismo tamano se saltean. Invalidar el .pyc fuerza recompilar.
            try:
                Path(importlib.util.cache_from_source(file_path)).unlink(missing_ok=True)
            except OSError:
                pass
        importlib.reload(mod)

    def _cascade_reload(self, target_mod: ModuleType) -> None:
        target_name = getattr(target_mod, "__name__", None)
        if not target_name:
            return
        importers_to_reload: list[ModuleType] = []
        for name in tuple(sys.modules):
            if not name or name == target_name or name == "kateto.core" or name.startswith("kateto.core."):
                continue
            mod = sys.modules.get(name)
            if mod is None or not isinstance(mod, ModuleType):
                continue
            stale = False
            for attr_val in getattr(mod, "__dict__", {}).values():
                if getattr(attr_val, "__module__", None) == target_name:
                    qualname = getattr(attr_val, "__qualname__", getattr(attr_val, "__name__", None))
                    if isinstance(qualname, str):
                        curr: Any = target_mod
                        for part in qualname.split("."):
                            curr = getattr(curr, part, None)
                            if curr is None:
                                break
                        if curr is not None and curr is not attr_val:
                            stale = True
                            break
            if stale:
                importers_to_reload.append(mod)

        parent_name = target_name.rpartition(".")[0]
        if parent_name and parent_name in sys.modules:
            parent_mod = sys.modules.get(parent_name)
            if (
                parent_mod is not None
                and isinstance(parent_mod, ModuleType)
                and parent_mod not in importers_to_reload
                and not parent_name.startswith("kateto.core")
            ):
                importers_to_reload.append(parent_mod)

        for importer in importers_to_reload:
            try:
                importlib.reload(importer)
            except Exception:
                pass

        for name in tuple(sys.modules):
            if not name or name == target_name or name == "kateto.core" or name.startswith("kateto.core."):
                continue
            mod = sys.modules.get(name)
            if mod is None or not isinstance(mod, ModuleType):
                continue
            for attr_name, attr_val in list(getattr(mod, "__dict__", {}).items()):
                if getattr(attr_val, "__module__", None) == target_name:
                    qualname = getattr(attr_val, "__qualname__", getattr(attr_val, "__name__", None))
                    if isinstance(qualname, str):
                        curr = target_mod
                        for part in qualname.split("."):
                            curr = getattr(curr, part, None)
                            if curr is None:
                                break
                        if curr is not None and curr is not attr_val:
                            setattr(mod, attr_name, curr)

    async def _refresh(self, config: LoadedConfig | None) -> None:
        loaded = config if config is not None else self._config
        if loaded is None:
            return
        registry = discover_plugins(
            DiscoveryContext(config=loaded, shared=self._shared),
        )
        desired = {plugin.name: plugin for plugin in registry.plugins}
        for active in self.manager.get_plugins():
            replacement = desired.pop(active.name, None)
            if replacement is None:
                await self.manager.disable_plugin(active.name)
            elif type(replacement) is not type(active):
                await self.manager.replace_plugin(active, replacement)
        for plugin in desired.values():
            if self._config_enabled(plugin):
                await self.manager.enable_plugin(plugin)
            else:
                self.manager.register_plugin(plugin)

    def _config_enabled(self, plugin: Plugin) -> bool:
        config = self._config
        if config is None:
            return True
        plugin_settings = config.settings.plugin.get(plugin.name)
        if plugin_settings is not None:
            return plugin_settings.enabled
        voice_settings = config.settings.voice.get(plugin.name)
        if voice_settings is not None:
            return voice_settings.enabled
        return True

    async def _emit_error(self, error: BaseException) -> None:
        await self.manager.emit(
            "error",
            PluginErrorData(
                plugin="hot_reload",
                event_name="reload",
                error_type=type(error).__name__,
                message=str(error),
            ),
            source="hot_reload",
        )
