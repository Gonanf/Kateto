from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, Self, override

from kateto.core.config import LoadedConfig, PluginSettings, VoiceSettings
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.audio_input import MeetAudioInput, MicrophoneAudioInput
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
from kateto.plugins.audio_processor import WhisperAudioProcessor
from kateto.plugins.audio_output.base import AudioOutputFactory
from kateto.plugins.audio_output.player import AudioOutputPlayer
from kateto.plugins.audio_output.zonos import ZonosAudioOutput
from kateto.plugins.connector.cli import CliConnector
from kateto.plugins.executor import ClassifierExecutor, InterruptExecutor, TodoListExecutor
from kateto.plugins.work.backlog import BacklogOwner
from kateto.providers import ClassifierProvider, WhisperProvider
from kateto.voices import Conquest, Doktor, Jane, OpenAICompatibleProvider, VoiceAgent


_VOICE_TYPES: Final[tuple[tuple[str, type[VoiceAgent]], ...]] = (
    ("jane", Jane),
    ("doktor", Doktor),
    ("conquest", Conquest),
)


@dataclass(frozen=True, slots=True)
class LiveAssemblyConfigurationError(Exception):
    field: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"live assembly requires {self.field}: {self.reason}"


class ManagedProvider(Protocol):
    @property
    def is_closed(self) -> bool: ...

    async def __aenter__(self) -> Self: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class LiveDependencies:
    vad: VoiceActivityDetector
    capture_factory: CaptureFactory | None = None
    player_factory: AudioOutputFactory | None = None


class LiveConversation:
    def __init__(
        self,
        *,
        manager: PluginManager,
        plugins: tuple[Plugin, ...],
        input_plugins: tuple[Plugin, ...],
        providers: tuple[ManagedProvider, ...],
    ) -> None:
        self.manager: PluginManager = manager
        self._plugins: tuple[Plugin, ...] = plugins
        self._input_plugins: tuple[Plugin, ...] = input_plugins
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
            for plugin in self._plugins:
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


def build_live_conversation(
    config: LoadedConfig,
    *,
    dependencies: LiveDependencies | None = None,
    silero_model_loader: SileroModelLoader | None = None,
) -> LiveConversation:
    resolved_dependencies = (
        _default_dependencies(config, silero_model_loader=silero_model_loader)
        if dependencies is None
        else dependencies
    )
    settings = config.settings
    whisper = WhisperProvider(_required_plugin(config, "audio_processor_whisper"))
    classifier = ClassifierProvider(_required_plugin(config, "executor_classifier"))
    voice_provider = _voice_provider(_required_plugin(config, "voice_llm"))
    inputs = _audio_inputs(config, resolved_dependencies)
    voices = _voices(config.paths.config_dir, settings.voice, voice_provider)
    plugins = (
        InterruptExecutor(),
        WhisperAudioProcessor(provider=whisper),
        ClassifierExecutor(classifier=classifier),
        TodoListExecutor(config_dir=config.paths.config_dir, voice="doktor"),
        CliConnector(settings=settings.cli, working_directory=config.paths.config_dir),
        BacklogOwner(backlog_path=config.paths.config_dir / "product_backlog.json"),
        *voices,
        ZonosAudioOutput(_required_plugin(config, "audio_output_zonos")),
        AudioOutputPlayer(
            _required_plugin(config, "audio_output_player"),
            player_factory=resolved_dependencies.player_factory,
        ),
        *inputs,
    )
    return LiveConversation(
        manager=PluginManager(),
        plugins=plugins,
        input_plugins=inputs,
        providers=(whisper, classifier),
    )


def _default_dependencies(
    config: LoadedConfig,
    *,
    silero_model_loader: SileroModelLoader | None = None,
) -> LiveDependencies:
    input_settings = next(
        settings
        for name in ("audio_input_mic", "audio_input_meet")
        if (settings := config.settings.plugin.get(name)) is not None and settings.enabled
    )
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
    return LiveDependencies(vad=SileroVad(model, threshold=threshold))


def _required_plugin(config: LoadedConfig, name: str) -> PluginSettings:
    settings = config.settings.plugin.get(name)
    if settings is None:
        raise LiveAssemblyConfigurationError(field=f"plugin.{name}", reason="must be configured")
    if not settings.enabled:
        raise LiveAssemblyConfigurationError(field=f"plugin.{name}.enabled", reason="must be true")
    return settings


def _audio_inputs(config: LoadedConfig, dependencies: LiveDependencies) -> tuple[Plugin, ...]:
    plugins: list[Plugin] = []
    mic_settings = config.settings.plugin.get("audio_input_mic")
    if mic_settings is not None and mic_settings.enabled:
        plugins.append(
            MicrophoneAudioInput(
                mic_settings,
                vad=dependencies.vad,
                capture_factory=dependencies.capture_factory,
            ),
        )
    meet_settings = config.settings.plugin.get("audio_input_meet")
    if meet_settings is not None and meet_settings.enabled:
        plugins.append(
            MeetAudioInput(
                meet_settings,
                vad=dependencies.vad,
                capture_factory=dependencies.capture_factory,
            ),
        )
    if not plugins:
        raise LiveAssemblyConfigurationError(
            field="plugin.audio_input_mic or plugin.audio_input_meet",
            reason="at least one configured input must be enabled",
        )
    return tuple(plugins)


def _voice_provider(settings: PluginSettings) -> OpenAICompatibleProvider:
    model = settings.model
    if model is None or not model.strip():
        raise LiveAssemblyConfigurationError(field="plugin.voice_llm.model", reason="must be configured")
    return OpenAICompatibleProvider(model=model, endpoint=settings.endpoint)


def _voices(
    config_dir: Path,
    settings_by_name: dict[str, VoiceSettings],
    provider: OpenAICompatibleProvider,
) -> tuple[Plugin, ...]:
    voices: list[Plugin] = []
    for name, voice_type in _VOICE_TYPES:
        settings = settings_by_name.get(name)
        if settings is not None and settings.enabled:
            voices.append(voice_type(config_dir=config_dir, provider=provider, settings=settings))
    if not voices:
        raise LiveAssemblyConfigurationError(field="voice", reason="at least one P0 voice must be enabled")
    return tuple(voices)
