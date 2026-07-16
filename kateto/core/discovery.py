from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from weakref import WeakKeyDictionary
from typing import Final, Protocol, Self, override

from kateto.core.config import LoadedConfig, PluginSettings, VoiceSettings
from kateto.core.event import AudioData, AudioOutput, ClassificationData, TextChunk, TranscriptionData
from kateto.core.plugin import Plugin
from kateto.plugins.audio_input.base import CaptureFactory, VoiceActivityDetector
from kateto.plugins.audio_output.base import AudioOutputFactory
from kateto.voices.base import GenerationRequest, OpenAICompatibleProvider


class WhisperProvider(Protocol):
    async def transcribe(self, audio: AudioData) -> TranscriptionData: ...


class ClassifierProvider(Protocol):
    async def classify(self, text: str) -> ClassificationData: ...


class VoiceProvider(Protocol):
    def stream(self, request: GenerationRequest) -> AsyncIterator[str]: ...


class PcmStreamingProvider(Protocol):
    async def __aenter__(self) -> Self: ...

    async def aclose(self) -> None: ...

    def stream_sentence(self, sentence: TextChunk, *, voice_id: str) -> AsyncIterator[AudioOutput]: ...


@dataclass(frozen=True, slots=True)
class LiveAssemblyConfigurationError(Exception):
    field: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"live assembly requires {self.field}: {self.reason}"


@dataclass(frozen=True, slots=True)
class DiscoveryDependencies:
    vad: VoiceActivityDetector
    capture_factory: CaptureFactory | None
    player_factory: AudioOutputFactory | None
    whisper_provider: WhisperProvider
    classifier: ClassifierProvider
    voice_provider: VoiceProvider
    zonos_provider: PcmStreamingProvider | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryContext:
    config: LoadedConfig
    dependencies: DiscoveryDependencies

    def plugin_settings(self, name: str) -> PluginSettings:
        return required_plugin_settings(self.config, name)


@dataclass(frozen=True, slots=True)
class PluginRegistry:
    plugins: frozenset[Plugin]
    input_plugins: frozenset[Plugin]


type PluginFactory = Callable[[DiscoveryContext], Plugin]
type VoiceFactory = Callable[[DiscoveryContext, VoiceSettings], Plugin]


_DISCOVERY_CONTEXTS: WeakKeyDictionary[Plugin, DiscoveryContext] = WeakKeyDictionary()


@dataclass(frozen=True, slots=True)
class _PluginDefinition:
    name: str
    module_name: str
    factory: PluginFactory
    is_input: bool = False
    default_enabled: bool = False


@dataclass(frozen=True, slots=True)
class _VoiceDefinition:
    name: str
    module_name: str
    factory: VoiceFactory


_REQUIRED_PLUGIN_NAMES: Final[tuple[str, ...]] = (
    "audio_processor_whisper",
    "executor_classifier",
    "voice_llm",
    "audio_output_zonos",
    "audio_output_player",
)


def required_plugin_settings(config: LoadedConfig, name: str) -> PluginSettings:
    settings = config.settings.plugin.get(name)
    if settings is None:
        raise LiveAssemblyConfigurationError(field=f"plugin.{name}", reason="must be configured")
    if not settings.enabled:
        raise LiveAssemblyConfigurationError(field=f"plugin.{name}.enabled", reason="must be true")
    return settings


def create_voice_provider(config: LoadedConfig) -> OpenAICompatibleProvider:
    settings = required_plugin_settings(config, "voice_llm")
    model = settings.model
    if model is None or not model.strip():
        raise LiveAssemblyConfigurationError(field="plugin.voice_llm.model", reason="must be configured")
    return OpenAICompatibleProvider(model=model, endpoint=settings.endpoint)


def first_enabled_input_settings(config: LoadedConfig) -> PluginSettings:
    for name in ("audio_input_mic", "audio_input_meet"):
        settings = config.settings.plugin.get(name)
        if settings is not None and settings.enabled:
            return settings
    raise LiveAssemblyConfigurationError(
        field="plugin.audio_input_mic or plugin.audio_input_meet",
        reason="at least one configured input must be enabled",
    )


def discover_plugins(context: DiscoveryContext) -> PluginRegistry:
    for name in _REQUIRED_PLUGIN_NAMES:
        _ = context.plugin_settings(name)
    discovered: list[tuple[Plugin, bool]] = []
    for definition in _PLUGIN_DEFINITIONS:
        if not _is_enabled(context, definition):
            continue
        if not _module_is_available(definition.module_name):
            continue
        discovered.append((definition.factory(context), definition.is_input))
    for voice_name, settings in context.config.settings.voice.items():
        if not settings.enabled:
            continue
        definition = _voice_definition(voice_name)
        if definition is None:
            continue
        if not _module_is_available(definition.module_name):
            continue
        discovered.append((definition.factory(context, settings), False))
    plugin_names = {plugin.name for plugin, _ in discovered}
    if len(plugin_names) != len(discovered):
        raise LiveAssemblyConfigurationError(field="plugin", reason="plugin names must be unique")
    plugins = frozenset(plugin for plugin, _ in discovered)
    input_plugins = frozenset(plugin for plugin, is_input in discovered if is_input)
    if not input_plugins:
        raise LiveAssemblyConfigurationError(
            field="plugin.audio_input_mic or plugin.audio_input_meet",
            reason="at least one configured input must be enabled",
        )
    if not any(plugin.name in {definition.name for definition in _VOICE_DEFINITIONS} for plugin in plugins):
        raise LiveAssemblyConfigurationError(field="voice", reason="at least one P0 voice must be enabled")
    for plugin in plugins:
        _DISCOVERY_CONTEXTS[plugin] = context
    return PluginRegistry(plugins=plugins, input_plugins=input_plugins)


def discovery_context_for(plugins: tuple[Plugin, ...]) -> DiscoveryContext | None:
    for plugin in plugins:
        context = _DISCOVERY_CONTEXTS.get(plugin)
        if context is not None:
            return context
    return None


def _module_is_available(module_name: str) -> bool:
    module = import_module(module_name)
    module_file = getattr(module, "__file__", None)
    return isinstance(module_file, str) and Path(module_file).is_file()


def _is_enabled(context: DiscoveryContext, definition: _PluginDefinition) -> bool:
    settings = context.config.settings.plugin.get(definition.name)
    if settings is None:
        return definition.default_enabled
    return settings.enabled


def _voice_definition(name: str) -> _VoiceDefinition | None:
    for definition in _VOICE_DEFINITIONS:
        if definition.name == name:
            return definition
    return None


def _microphone_factory(context: DiscoveryContext) -> Plugin:
    from kateto.plugins.audio_input.mic import MicrophoneAudioInput

    return MicrophoneAudioInput(
        context.plugin_settings("audio_input_mic"),
        vad=context.dependencies.vad,
        capture_factory=context.dependencies.capture_factory,
    )


def _meet_factory(context: DiscoveryContext) -> Plugin:
    from kateto.plugins.audio_input.meet import MeetAudioInput

    return MeetAudioInput(
        context.plugin_settings("audio_input_meet"),
        vad=context.dependencies.vad,
        capture_factory=context.dependencies.capture_factory,
    )


def _whisper_factory(context: DiscoveryContext) -> Plugin:
    from kateto.plugins.audio_processor.whisper import WhisperAudioProcessor

    return WhisperAudioProcessor(provider=context.dependencies.whisper_provider)


def _classifier_factory(context: DiscoveryContext) -> Plugin:
    from kateto.plugins.executor.classifier import ClassifierExecutor

    return ClassifierExecutor(classifier=context.dependencies.classifier)


def _interrupt_factory(context: DiscoveryContext) -> Plugin:
    from kateto.plugins.executor.interrupt import InterruptExecutor

    del context
    return InterruptExecutor()


def _todo_factory(context: DiscoveryContext) -> Plugin:
    from kateto.plugins.executor.todo_list import TodoListExecutor

    return TodoListExecutor(config_dir=context.config.paths.config_dir)


def _cli_factory(context: DiscoveryContext) -> Plugin:
    from kateto.plugins.connector.cli import CliConnector

    return CliConnector(settings=context.config.settings.cli, working_directory=context.config.paths.config_dir)


def _backlog_factory(context: DiscoveryContext) -> Plugin:
    from kateto.plugins.work.backlog import BacklogOwner

    return BacklogOwner(backlog_path=context.config.paths.config_dir / "product_backlog.json")


def _zonos_factory(context: DiscoveryContext) -> Plugin:
    from kateto.plugins.audio_output.zonos import ZonosAudioOutput

    return ZonosAudioOutput(
        context.plugin_settings("audio_output_zonos"),
        provider=context.dependencies.zonos_provider,
    )


def _player_factory(context: DiscoveryContext) -> Plugin:
    from kateto.plugins.audio_output.player import AudioOutputPlayer

    return AudioOutputPlayer(
        context.plugin_settings("audio_output_player"),
        player_factory=context.dependencies.player_factory,
    )


def _jane_factory(context: DiscoveryContext, settings: VoiceSettings) -> Plugin:
    from kateto.voices.jane import Jane

    return Jane(config_dir=context.config.paths.config_dir, provider=context.dependencies.voice_provider, settings=settings)


def _doktor_factory(context: DiscoveryContext, settings: VoiceSettings) -> Plugin:
    from kateto.voices.doktor import Doktor

    return Doktor(config_dir=context.config.paths.config_dir, provider=context.dependencies.voice_provider, settings=settings)


def _conquest_factory(context: DiscoveryContext, settings: VoiceSettings) -> Plugin:
    from kateto.voices.conquest import Conquest

    return Conquest(config_dir=context.config.paths.config_dir, provider=context.dependencies.voice_provider, settings=settings)


_PLUGIN_DEFINITIONS: Final[frozenset[_PluginDefinition]] = frozenset(
    {
        _PluginDefinition("audio_input_mic", "kateto.plugins.audio_input.mic", _microphone_factory, is_input=True),
        _PluginDefinition("audio_input_meet", "kateto.plugins.audio_input.meet", _meet_factory, is_input=True),
        _PluginDefinition("audio_processor_whisper", "kateto.plugins.audio_processor.whisper", _whisper_factory),
        _PluginDefinition("executor_classifier", "kateto.plugins.executor.classifier", _classifier_factory),
        _PluginDefinition("executor_interrupt", "kateto.plugins.executor.interrupt", _interrupt_factory, default_enabled=True),
        _PluginDefinition("executor_todo_list", "kateto.plugins.executor.todo_list", _todo_factory, default_enabled=True),
        _PluginDefinition("connector_cli", "kateto.plugins.connector.cli", _cli_factory, default_enabled=True),
        _PluginDefinition("backlog", "kateto.plugins.work.backlog", _backlog_factory, default_enabled=True),
        _PluginDefinition("audio_output_zonos", "kateto.plugins.audio_output.zonos", _zonos_factory),
        _PluginDefinition("audio_output_player", "kateto.plugins.audio_output.player", _player_factory),
    },
)

_VOICE_DEFINITIONS: Final[frozenset[_VoiceDefinition]] = frozenset(
    {
        _VoiceDefinition("jane", "kateto.voices.jane", _jane_factory),
        _VoiceDefinition("doktor", "kateto.voices.doktor", _doktor_factory),
        _VoiceDefinition("conquest", "kateto.voices.conquest", _conquest_factory),
    },
)
