from __future__ import annotations

from typing import Protocol

from kateto.core.hot_reload import HotReloadController
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.workflow import WorkflowCatalog
from kateto.core.workflow_engine import WorkflowEngine


class TuiMcpServer(Protocol):
    @property
    def server_name(self) -> str: ...

    @property
    def voice_name(self) -> str: ...

    @property
    def pending_wait_count(self) -> int: ...


class TuiRuntime(Protocol):
    @property
    def manager(self) -> PluginManager: ...

    @property
    def runtime_plugins(self) -> tuple[Plugin, ...]: ...

    @property
    def mcp_servers(self) -> tuple[TuiMcpServer, ...]: ...

    @property
    def workflow_catalog(self) -> WorkflowCatalog: ...

    @property
    def workflow_engine(self) -> WorkflowEngine: ...

    @property
    def workflow_voices(self) -> tuple[str, ...]: ...

    @property
    def hot_reload_controller(self) -> HotReloadController | None: ...

    @property
    def is_started(self) -> bool: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...
