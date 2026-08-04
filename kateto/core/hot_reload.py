from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any, Final

import watchfiles

from kateto.core.config import ConfigError, LoadedConfig, load_config
from kateto.core.discovery import DiscoveryContext, discover_plugins
from kateto.core.event import PluginErrorData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin

_WATCHED_SUFFIXES: Final = frozenset({".py", ".toml"})
_DEBOUNCE_MS: Final = 300


class HotReloadController:
    """Watches plugin/config files and swaps changed plugins on the live bus.

    Modules are purged from sys.modules (not reloaded) so sub-imports are
    re-resolved; plugins are replaced only when their class changed.
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
            changed = self._purge_plugins(path)
            if not changed and config is None:
                return
            await self._refresh(config)
        except ConfigError as error:
            await self._emit_error(error)

    def _reload_config(self, path: Path) -> LoadedConfig | None:
        if path.name != "config.toml":
            return self._config
        config_path = self.watched_root / "config.toml"
        if not config_path.is_file():
            raise ConfigError("config.toml is missing after change")
        self._config = load_config(config_dir=self.watched_root)
        return self._config

    def _purge_plugins(self, path: Path) -> bool:
        if path.suffix.casefold() != ".py":
            return False
        importlib.invalidate_caches()
        target = path.resolve()
        purged = False
        for name in tuple(sys.modules):
            module_file = getattr(sys.modules[name], "__file__", None)
            if isinstance(module_file, str) and Path(module_file).resolve() == target:
                del sys.modules[name]
                purged = True
        return purged

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
            await self.manager.enable_plugin(plugin)

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
