from .whisper import WhisperAudioProcessor

__all__ = ["ParakeetAudioProcessor", "WhisperAudioProcessor"]


def __getattr__(name):
    if name == "ParakeetAudioProcessor":
        from .parakeet import ParakeetAudioProcessor

        return ParakeetAudioProcessor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def create_plugins(ctx):
    from .parakeet import ParakeetAudioProcessor
    from .whisper import WhisperAudioProcessor

    settings = ctx.config.settings.plugin
    parakeet = settings.get("audio_processor_parakeet")
    if parakeet is not None and parakeet.enabled:
        return [ParakeetAudioProcessor(parakeet)]
    return [WhisperAudioProcessor(ctx.plugin_settings("audio_processor_whisper"))]
