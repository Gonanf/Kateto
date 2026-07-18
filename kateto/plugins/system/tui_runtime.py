from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class TuiPluginConfiguration:
    plugin: str
    microphone: str | None = None
    speaker: str | None = None
    values: tuple[tuple[str, str], ...] = ()


@runtime_checkable
class TuiConfigurationRuntime(Protocol):
    @property
    def plugin_configurations(self) -> tuple[TuiPluginConfiguration, ...]: ...

    def plugin_configuration(self, name: str) -> TuiPluginConfiguration | None: ...

    async def configure_plugin(self, name: str, configuration: TuiPluginConfiguration) -> None: ...



