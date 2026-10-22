__all__ = ["MaskAudioInput", "MeetAudioInput", "MicrophoneAudioInput"]


def __getattr__(name):
    if name == "MaskAudioInput":
        from .mask import MaskAudioInput
        return MaskAudioInput
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
        ("audio_input_mask", "kateto.plugins.audio_input.mask", "MaskAudioInput"),
    ]:
        settings = ctx.config.settings.plugin.get(name)
        if settings is None:
            continue
        try:
            mod = import_module(module_name)
            cls = getattr(mod, attr_name)
        except (ModuleNotFoundError, ImportError):
            continue
        if name == "audio_input_mask":
            capture_factory = ctx.get_shared("mask_capture_factory", factory=_load_mask_factory)
        else:
            capture_factory = ctx.get_shared("capture_factory")
        plugins.append(
            cls(
                settings,
                vad=ctx.get_shared("vad", factory=_load_vad),
                capture_factory=capture_factory,
            )
        )
    if not plugins:
        from kateto.core.discovery import LiveAssemblyConfigurationError

        raise LiveAssemblyConfigurationError(
            field="plugin.audio_input_mic or plugin.audio_input_meet or plugin.audio_input_mask",
            reason="at least one configured input must be enabled",
        )
    return plugins


def _load_mask_factory():
    from .mask import get_mask_capture_factory

    return get_mask_capture_factory()


def _load_vad():
    from .silero import load_silero_model
    from .base import SileroVad, DEFAULT_VAD_THRESHOLD
    model = load_silero_model()
    return SileroVad(model, threshold=DEFAULT_VAD_THRESHOLD)
