from __future__ import annotations

import logging
from typing import Any

from kateto.core.event import AudioOutput
from kateto.core.plugin import Plugin
from kateto.providers.boson_tts import BosonTTSProvider

logger = logging.getLogger(__name__)


class BosonTTSPlugin(Plugin):
    """Audio output plugin leveraging BosonTTSProvider."""

    def __init__(
        self,
        name: str = "boson_tts",
        *,
        provider: BosonTTSProvider | None = None,
        voice_id: str = "jane",
    ) -> None:
        super().__init__(name=name, capabilities=("audio_output", "tts"))
        self.provider = provider or BosonTTSProvider()
        self.voice_id = voice_id

    async def initialize(self) -> None:
        if self.manager is not None:
            self.manager.register_event("audio_output", AudioOutput)

    async def synthesize(self, text: str) -> bytes:
        try:
            return await self.provider.generate_speech(text, voice=self.voice_id)
        except Exception as e:
            logger.error("BosonTTS synthesis failed: %s", e)
            return b""
