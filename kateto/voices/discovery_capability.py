"""Discovery capability: voices, plugins, and event directory tools.

Injected into every pydantic-ai voice so any team member can discover the
runtime: which voices exist, which plugins are registered, and which events
are wired. Department filters reuse the bus's own `_validate_dept` authority
rules (a voice may only inspect departments it belongs to).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import FunctionToolset
from pydantic_ai.capabilities import Capability

from kateto.core.manager import PluginManager
from kateto.voices.tools import VoiceToolExecutor


def _manager_for(executor: VoiceToolExecutor) -> PluginManager | None:
    return getattr(executor, "_manager", None)


class DiscoveryToolset:
    def __init__(self, executor: VoiceToolExecutor) -> None:
        self._executor = executor
        ts = FunctionToolset()
        ts.add_function(
            self._directory_voices,
            name="directory_voices",
            description=(
                "List the voices on the team and their departments. Use before "
                "request_generation to pick the right target voice."
            ),
        )
        ts.add_function(
            self._directory_plugins,
            name="directory_plugins",
            description="List registered plugins (enabled and disabled) with their capabilities.",
        )
        ts.add_function(
            self._directory_events,
            name="directory_events",
            description="List the event contracts wired on the bus (names, receivers, and fields).",
        )
        self._toolset = ts

    def _normalize_dept(self, dept: str | None) -> tuple[str | None, str | None]:
        manager = _manager_for(self._executor)
        if dept is None or manager is None:
            return dept, None
        try:
            # Reuse the bus's anti-spoofing rule: a voice may only look into
            # departments it belongs to (plugins without a dept policy are free).
            return manager._validate_dept(dept, source=getattr(self._executor, "_voice_name", "")), None
        except ValueError as error:
            return None, str(error)

    async def _directory_voices(self, dept: str | None = None) -> str:
        manager = _manager_for(self._executor)
        if manager is None:
            return json.dumps({"voices": [], "error": "no plugin manager available"})
        normalized, error = self._normalize_dept(dept)
        if error is not None:
            return json.dumps({"voices": [], "error": error})
        voices = []
        for plugin in manager.get_all_plugins():
            if "voice" not in plugin.capabilities:
                continue
            if normalized is not None and normalized not in plugin.depts:
                continue
            profile = getattr(plugin, "profile", None)
            voices.append({
                "name": plugin.name,
                "display_name": getattr(profile, "display_name", plugin.name) if profile else plugin.name,
                "role": getattr(profile, "role", None) if profile else None,
                "depts": list(plugin.depts),
                "capabilities": list(plugin.capabilities),
                "enabled": plugin.enabled,
            })
        return json.dumps({"voices": voices})

    async def _directory_plugins(self, dept: str | None = None) -> str:
        manager = _manager_for(self._executor)
        if manager is None:
            return json.dumps({"plugins": [], "error": "no plugin manager available"})
        normalized, error = self._normalize_dept(dept)
        if error is not None:
            return json.dumps({"plugins": [], "error": error})
        plugins = []
        for plugin in manager.get_all_plugins():
            if normalized is not None and normalized not in plugin.depts:
                continue
            plugins.append({
                "name": plugin.name,
                "capabilities": list(plugin.capabilities),
                "depts": list(plugin.depts),
                "enabled": plugin.enabled,
            })
        return json.dumps({"plugins": plugins})

    async def _directory_events(self) -> str:
        return await self._executor.execute("list_events", {})

    @property
    def toolset(self) -> Any:
        return self._toolset


class DiscoveryCapability(Capability[None]):
    def __init__(self, executor: VoiceToolExecutor) -> None:
        super().__init__(
            toolsets=[DiscoveryToolset(executor).toolset],
            description="Discovery: list team voices, plugins, and event contracts.",
        )
