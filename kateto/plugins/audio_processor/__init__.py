from .whisper import WhisperAudioProcessor

__all__ = ["WhisperAudioProcessor"]


def create_plugins(ctx):
    from .whisper import WhisperAudioProcessor

    return [
        WhisperAudioProcessor(ctx.plugin_settings("audio_processor_whisper")),
    ]
