from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Self

from kateto.core.config import LoadedConfig
from kateto.core.discovery import (
    DiscoveryContext,
    DiscoveryDependencies,
    LiveAssemblyConfigurationError,
    PcmStreamingProvider,
    PluginRegistry,
    create_voice_provider,
    discover_plugins,
    first_enabled_input_settings,
    required_plugin_settings,
)
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.audio_input.base import (
    DEFAULT_VAD_THRESHOLD,
    CaptureFactory,
    SileroVad,
    VoiceActivityDetector,
)
from kateto.plugins.audio_input.silero import (
    SileroModelLoader,
    load_silero_model,
)
from kateto.plugins.audio_output.base import AudioOutputFactory
from kateto.providers import ClassifierProvider, WhisperProvider


EventRuntimeConfigurationError = LiveAssemblyConfigurationError


__all__ = [
    "EventRuntimeConfigurationError",
    "EventRuntime",
    "EventRuntimeDependencies",
    "ManagedProvider",
    "build_event_runtime",
]


class ManagedProvider(Protocol):
    @property
    def is_closed(self) -> bool: ...

    async def __aenter__(self) -> Self: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class EventRuntimeDependencies:
    vad: VoiceActivityDetector
    capture_factory: CaptureFactory | None = None
    player_factory: AudioOutputFactory | None = None
    zonos_provider: PcmStreamingProvider | None = None


class EventRuntime:
    def __init__(
        self,
        *,
        manager: PluginManager,
        registry: PluginRegistry,
        providers: tuple[ManagedProvider, ...],
    ) -> None:
        self.manager: PluginManager = manager
        self._plugins: frozenset[Plugin] = registry.plugins
        self._input_plugins: frozenset[Plugin] = registry.input_plugins
        self._providers: tuple[ManagedProvider, ...] = providers
        self._started: bool = False

    @property
    def providers(self) -> tuple[ManagedProvider, ...]:
        return self._providers

    async def start(self) -> None:
        if self._started:
            return
        try:
            for provider in self._providers:
                _ = await provider.__aenter__()
            for plugin in self._plugins - self._input_plugins:
                await self.manager.enable_plugin(plugin)
            for plugin in self._input_plugins:
                await self.manager.enable_plugin(plugin)
        except BaseException:  # noqa: BROAD_EXCEPT_OK
            await self.stop()
            raise
        self._started = True

    async def stop(self) -> None:
        for plugin in self._input_plugins:
            await self.manager.disable_plugin(plugin.name)
        await self.manager.close()
        for provider in reversed(self._providers):
            await provider.aclose()
        self._started = False


def build_event_runtime(
    config: LoadedConfig,
    *,
    dependencies: EventRuntimeDependencies | None = None,
    silero_model_loader: SileroModelLoader | None = None,
) -> EventRuntime:
    resolved_dependencies = (
        _default_dependencies(config, silero_model_loader=silero_model_loader)
        if dependencies is None
        else dependencies
    )
    whisper = WhisperProvider(required_plugin_settings(config, "audio_processor_whisper"))
    classifier = ClassifierProvider(required_plugin_settings(config, "executor_classifier"))
    registry = discover_plugins(
        DiscoveryContext(
            config=config,
            dependencies=DiscoveryDependencies(
                vad=resolved_dependencies.vad,
                capture_factory=resolved_dependencies.capture_factory,
                player_factory=resolved_dependencies.player_factory,
                whisper_provider=whisper,
                classifier=classifier,
                voice_provider=create_voice_provider(config),
                zonos_provider=resolved_dependencies.zonos_provider,
            ),
        ),
    )
    return EventRuntime(
        manager=PluginManager(),
        registry=registry,
        providers=(whisper, classifier),
    )


def _default_dependencies(
    config: LoadedConfig,
    *,
    silero_model_loader: SileroModelLoader | None = None,
) -> EventRuntimeDependencies:
    input_settings = first_enabled_input_settings(config)
    threshold = (
        DEFAULT_VAD_THRESHOLD
        if input_settings.vad_threshold is None
        else input_settings.vad_threshold
    )
    model = (
        load_silero_model()
        if silero_model_loader is None
        else silero_model_loader.load_model()
    )
    return EventRuntimeDependencies(vad=SileroVad(model, threshold=threshold))
