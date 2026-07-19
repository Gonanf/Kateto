from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import importlib
from os import fsdecode
import sys
from asyncio import AbstractEventLoop
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from .config import ConfigError, LoadedConfig, load_config
from .discovery import PluginRegistry, discovery_context_for, discover_plugins
from .event import PluginErrorData
from .manager import PluginManager
from .plugin import Plugin
from .workflow import WorkflowCatalog, WorkflowDefinitionError


_WATCHED_SUFFIXES: Final[frozenset[str]] = frozenset({".py", ".toml", ".md"})
_RELOAD_DEBOUNCE_SECONDS: Final[float] = 0.1


@dataclass(frozen=True, slots=True)
class ReloadContext:
    path: Path
    config: LoadedConfig | None
    plugin_type: type[Plugin] | None


@dataclass(frozen=True, slots=True)
class HotReloadReplacementError(Exception):
    path: Path
    reason: str

    def __str__(self) -> str:
        return f"unable to replace plugin after {self.path}: {self.reason}"


ReplacementFactory = Callable[[Plugin, ReloadContext], Plugin]
DiscoveryFactory = Callable[[LoadedConfig], PluginRegistry | None]


class HotReloadController:
    """Bridge watchdog's thread callbacks into the application's event loop."""

    def __init__(
        self,
        *,
        manager: PluginManager,
        watched_root: Path,
        source_roots: tuple[Path, ...] = (),
        loop: AbstractEventLoop | None = None,
        replacement_factory: ReplacementFactory | None = None,
        discovery_factory: DiscoveryFactory | None = None,
    ) -> None:
        self.manager = manager
        self.watched_root = watched_root.resolve()
        self.source_roots = tuple(root.resolve() for root in source_roots)
        self._observer: BaseObserver | None = None
        self._handler: _ReloadHandler | None = None
        self._reload_lock = asyncio.Lock()
        self._reload_tasks: set[asyncio.Task[None]] = set()
        self._closed = False
        self.loop = loop
        self._replacement_factory = replacement_factory
        self._discovery_factory = discovery_factory
        self._discovered_names = {
            plugin.name
            for plugin in manager.get_plugins()
            if discovery_context_for((plugin,)) is not None
        }

    async def start(self) -> None:
        if self._observer is not None:
            return
        if self.loop is None:
            msg = "hot reload requires the application's running event loop"
            raise RuntimeError(msg)
        observer = Observer()
        self._observer = observer
        handler = _ReloadHandler(self)
        self._handler = handler
        for root in (self.watched_root, *self.source_roots):
            if root.is_dir():
                observer.schedule(handler, str(root), recursive=True)
        observer.start()

    async def close(self) -> None:
        self._closed = True
        handler = self._handler
        self._handler = None
        if handler is not None:
            handler.close()
        await self._cancel_reload_tasks()
        observer = self._observer
        self._observer = None
        if observer is not None:
            observer.stop()
            observer.join(timeout=2)
        self.loop = None

    async def handle_change(self, path: Path) -> None:
        if self._closed:
            return
        resolved = path.resolve()
        if not self._is_watched(resolved):
            return
        if resolved.suffix.casefold() not in _WATCHED_SUFFIXES:
            return
        async with self._reload_lock:
            try:
                self._validate_workflows(resolved)
                config = self._load_config(resolved)
                if self._should_refresh(resolved) and config is not None and await self._refresh_discovered(config, path=resolved):
                    return
                for plugin in self._plugins_to_replace(resolved):
                    await self.manager.replace_plugin(plugin, self._replacement(plugin, path=resolved, config=config))
            except (
                ConfigError,
                HotReloadReplacementError,
                WorkflowDefinitionError,
            ) as error:
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

    def _start_reload(self, path: Path) -> None:
        if self._closed:
            return
        loop = self.loop
        if loop is None:
            return
        task = loop.create_task(self.handle_change(path), name=f"kateto-hot-reload-{path.name}")
        self._reload_tasks.add(task)
        task.add_done_callback(self._finish_reload)

    async def _cancel_reload_tasks(self) -> None:
        tasks = tuple(self._reload_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._reload_tasks.difference_update(tasks)

    def _finish_reload(self, task: asyncio.Task[None]) -> None:
        self._reload_tasks.discard(task)
        if not task.cancelled():
            task.exception()

    def _load_config(self, path: Path) -> LoadedConfig | None:
        config_path = self.watched_root / "config.toml"
        if path.name == "config.toml" and not config_path.is_file():
            raise HotReloadReplacementError(path=path, reason="config.toml is missing")
        if config_path.is_file():
            return load_config(config_dir=self.watched_root)
        return None

    def _should_refresh(self, path: Path) -> bool:
        return path.name == "config.toml" or self._discovery_factory is not None and path.suffix.casefold() == ".py"

    def _is_watched(self, path: Path) -> bool:
        return any(path.is_relative_to(root) for root in (self.watched_root, *self.source_roots))

    async def _refresh_discovered(self, config: LoadedConfig, *, path: Path) -> bool:
        factory = self._discovery_factory
        if factory is None:
            context = discovery_context_for(self.manager.get_plugins())
            if context is None:
                return False
            self._reload_module(path)
            registry = discover_plugins(replace(context, config=config))
        else:
            registry = factory(config)
        if registry is None:
            return False
        desired = {plugin.name: plugin for plugin in registry.plugins}
        self._discovered_names.update(
            plugin.name
            for plugin in self.manager.get_plugins()
            if discovery_context_for((plugin,)) is not None
        )
        self._discovered_names.update(desired)
        for active in self.manager.get_plugins():
            replacement = desired.pop(active.name, None)
            if replacement is None:
                if active.name in self._discovered_names:
                    await self.manager.disable_plugin(active.name)
            elif type(replacement) is not type(active):
                await self.manager.replace_plugin(active, replacement)
        self._discovered_names.intersection_update({plugin.name for plugin in registry.plugins})
        for replacement in desired.values():
            await self.manager.enable_plugin(replacement)
        return True

    @staticmethod
    def _reload_module(path: Path) -> None:
        importlib.invalidate_caches()
        for module in tuple(sys.modules.values()):
            module_path = getattr(module, "__file__", None)
            if isinstance(module_path, str) and Path(module_path).resolve() == path:
                importlib.reload(module)
                return

    def _plugins_to_replace(self, path: Path) -> tuple[Plugin, ...]:
        if path.name == "config.toml":
            return tuple(plugin for plugin in self.manager.get_plugins() if plugin.enabled)
        if path.suffix.casefold() != ".py":
            return ()
        return tuple(
            plugin
            for plugin in self.manager.get_plugins()
            if plugin.enabled and self._module_path(plugin) == path
        )

    def _replacement(self, plugin: Plugin, *, path: Path, config: LoadedConfig | None) -> Plugin:
        factory = self._replacement_factory
        if factory is None:
            raise HotReloadReplacementError(path=path, reason="replacement factory is not configured")
        return factory(
            plugin,
            ReloadContext(path=path, config=config, plugin_type=self._replacement_type(plugin, path)),
        )

    @staticmethod
    def _module_path(plugin: Plugin) -> Path | None:
        module = sys.modules.get(type(plugin).__module__)
        module_file = getattr(module, "__file__", None)
        if isinstance(module_file, str):
            return Path(module_file).resolve()
        return None

    def _replacement_type(self, plugin: Plugin, path: Path) -> type[Plugin] | None:
        if path.suffix.casefold() != ".py":
            return None
        module = sys.modules.get(type(plugin).__module__)
        if module is None or self._module_path(plugin) != path:
            return None
        importlib.invalidate_caches()
        reloaded = importlib.reload(module)
        candidate = vars(reloaded).get(type(plugin).__name__)
        if isinstance(candidate, type) and issubclass(candidate, Plugin):
            return candidate
        raise HotReloadReplacementError(path=path, reason="reloaded module does not define the active plugin class")

    def _validate_workflows(self, path: Path) -> None:
        if path.name != "workflow.py" and "workflows" not in path.parts:
            return
        catalog = WorkflowCatalog(config_dir=self.watched_root)
        for voice_dir in (self.watched_root / "voices").iterdir() if (self.watched_root / "voices").is_dir() else ():
            if voice_dir.is_dir():
                catalog.discover(voice=voice_dir.name)
        if (self.watched_root / "workflows").is_dir():
            catalog.discover(voice="Conquest")


class _ReloadHandler(FileSystemEventHandler):
    def __init__(self, controller: HotReloadController) -> None:
        self._controller = controller
        self._pending: asyncio.TimerHandle | None = None
        self._closed = False

    def on_any_event(self, event: FileSystemEvent) -> None:
        if self._closed or event.is_directory or event.event_type in ("opened", "closed"):
            return
        loop = self._controller.loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._schedule, Path(fsdecode(event.src_path)))

    def _schedule(self, path: Path) -> None:
        if self._closed:
            return
        loop = self._controller.loop
        if loop is None:
            return
        pending = self._pending
        if pending is not None:
            pending.cancel()
        self._pending = loop.call_later(_RELOAD_DEBOUNCE_SECONDS, self._reload, path)

    def _reload(self, path: Path) -> None:
        self._pending = None
        if self._closed:
            return
        self._controller._start_reload(path)

    def close(self) -> None:
        self._closed = True
        pending = self._pending
        self._pending = None
        if pending is not None:
            pending.cancel()
