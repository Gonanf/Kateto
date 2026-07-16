from __future__ import annotations

from kateto.core.config import PluginSettings

from .base import AudioInputConfig, AudioInputIdentity, CaptureFactory, VoiceActivityDetector
from .capture import SoundDeviceCaptureFactory
from .listener import AudioInputPlugin


class MicrophoneAudioInput(AudioInputPlugin):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        vad: VoiceActivityDetector,
        capture_factory: CaptureFactory | None = None,
    ) -> None:
        super().__init__(
            identity=AudioInputIdentity(
                name="audio_input_mic",
                payload_source="mic",
                config=AudioInputConfig.from_settings(
                    settings,
                    source="audio_input_mic",
                    require_device=False,
                ),
            ),
            vad=vad,
            capture_factory=(
                SoundDeviceCaptureFactory()
                if capture_factory is None
                else capture_factory
            ),
        )
