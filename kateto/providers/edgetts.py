from __future__ import annotations

import logging
import subprocess
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Self
from wave import Wave_read

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, TextChunk

log = logging.getLogger(__name__)


def _mp3_to_pcm(mp3_data: bytes, *, sample_rate: int = 24000) -> tuple[bytes, int]:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-i", "pipe:0",
            "-f", "wav",
            "-acodec", "pcm_s16le",
            "-ar", str(sample_rate),
            "-ac", "1",
            "pipe:1",
        ],
        input=mp3_data,
        capture_output=True,
        check=True,
    )
    with Wave_read(__import__("io").BytesIO(proc.stdout)) as w:
        return w.readframes(w.getnframes()), w.getframerate()


class EdgeTTSProvider:
    def __init__(self, settings: PluginSettings, *, voice: str | None = None) -> None:
        self._voice = voice or settings.default_language or "en-US-JennyNeural"
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def __aenter__(self) -> Self:
        self._active = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        self._active = False

    async def stream_sentence(
        self,
        sentence: TextChunk,
        *,
        voice: str,
    ) -> AsyncIterator[AudioOutput]:
        # ponytail: edge-tts returns MP3; convert to PCM s16le via ffmpeg subprocess
        import edge_tts  # noqa: PLC0415

        communicate = edge_tts.Communicate(text=sentence.text, voice=voice)
        mp3_chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                audio_data: bytes | None = chunk.get("data")
                if audio_data:
                    mp3_chunks.append(audio_data)
        if not mp3_chunks:
            return
        mp3_data = b"".join(mp3_chunks)
        log.debug(
            "[edgetts] TTS for voice=%s text=%r: %d MP3 bytes",
            voice, sentence.text, len(mp3_data),
        )
        pcm, sample_rate = _mp3_to_pcm(mp3_data)
        yield AudioOutput(
            samples=pcm,
            sample_rate=sample_rate,
            channels=1,
            format="pcm_s16le",
            voice_id=voice,
            sequence=0,
        )
        yield AudioOutput(
            samples=b"",
            sample_rate=sample_rate,
            channels=1,
            format="pcm_s16le",
            voice_id=voice,
            sequence=1,
            final=True,
        )
