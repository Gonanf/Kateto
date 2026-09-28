from .parakeet import ParakeetAudioProcessor
from .whisper import WhisperAudioProcessor

__all__ = ["ParakeetAudioProcessor", "WhisperAudioProcessor"]


def create_plugins(ctx):
    from .parakeet import ParakeetAudioProcessor
    from .whisper import WhisperAudioProcessor

    plugins = [
        WhisperAudioProcessor(ctx.plugin_settings("audio_processor_whisper")),
    ]
    # Guard: keep whisper alive even if `[plugin.audio_processor_parakeet]` is
    # absent (configs bootstrapped before this section existed). Un-guarded this
    # would raise LiveAssemblyConfigurationError and skip the whole factory.
    if "audio_processor_parakeet" in ctx.config.settings.plugin:
        plugins.append(ParakeetAudioProcessor(ctx.plugin_settings("audio_processor_parakeet")))
    return plugins
