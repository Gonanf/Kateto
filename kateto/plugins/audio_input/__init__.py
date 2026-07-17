__all__ = ["MeetAudioInput", "MicrophoneAudioInput"]


def __getattr__(name):
    if name == "MeetAudioInput":
        from .meet import MeetAudioInput
        return MeetAudioInput
    if name == "MicrophoneAudioInput":
        from .mic import MicrophoneAudioInput
        return MicrophoneAudioInput
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def create_plugins(ctx):
    from importlib import import_module

    plugins = []
    for name, module_name, attr_name in [
        ("audio_input_mic", "kateto.plugins.audio_input.mic", "MicrophoneAudioInput"),
        ("audio_input_meet", "kateto.plugins.audio_input.meet", "MeetAudioInput"),
    ]:
        settings = ctx.config.settings.plugin.get(name)
        if settings is None or not settings.enabled:
            continue
        try:
            mod = import_module(module_name)
            cls = getattr(mod, attr_name)
        except (ModuleNotFoundError, ImportError):
            continue
        plugins.append(
            cls(
                settings,
                vad=ctx.get_shared("vad", factory=_load_vad),
                capture_factory=ctx.get_shared("capture_factory"),
            )
        )
    if not plugins:
        from kateto.core.discovery import LiveAssemblyConfigurationError

        raise LiveAssemblyConfigurationError(
            field="plugin.audio_input_mic or plugin.audio_input_meet",
            reason="at least one configured input must be enabled",
        )
    return plugins


def _load_vad():
    from .silero import load_silero_model
    from .base import SileroVad, DEFAULT_VAD_THRESHOLD
    model = load_silero_model()
    return SileroVad(model, threshold=DEFAULT_VAD_THRESHOLD)
