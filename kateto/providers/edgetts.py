from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import logging
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Self

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, TextChunk

log = logging.getLogger(__name__)

_CHUNK_SIZE = 65536  # ~1.4s PCM at 24000Hz s16le mono


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
        # ponytail: stream MP3 chunks through ffmpeg stdin, read raw PCM from stdout
        import edge_tts  # noqa: PLC0415

        communicate = edge_tts.Communicate(text=sentence.text, voice=voice)

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i", "pipe:0",
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ar", "24000",
            "-ac", "1",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdin = proc.stdin
        stdout = proc.stdout
        assert stdin is not None and stdout is not None

        async def _feed() -> None:
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    audio_data: bytes | None = chunk.get("data")
                    if audio_data:
                        stdin.write(audio_data)
                        await stdin.drain()
            await stdin.drain()
            stdin.close()

        feed_task = asyncio.create_task(_feed())
        seq = 0
        total_pcm = 0
        try:
            while True:
                pcm = await stdout.read(_CHUNK_SIZE)
                if not pcm:
                    break
                total_pcm += len(pcm)
                yield AudioOutput(
                    samples=pcm,
                    sample_rate=24_000,
                    channels=1,
                    format="pcm_s16le",
                    voice_id=voice,
                    sequence=seq,
                )
                seq += 1
        finally:
            current_task = asyncio.current_task()
            cancellation_requested = False
            if current_task is not None:
                cancellation_requested = current_task.cancelling() > 0
            if cancellation_requested and not feed_task.done():
                feed_task.cancel()
            try:
                await feed_task
            except asyncio.CancelledError:
                if not cancellation_requested:
                    raise
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=1)
                except TimeoutError:
                    proc.kill()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=1)
                    except TimeoutError:
                        pass

        log.debug(
            "[edgetts] TTS for voice=%s text=%r: %d PCM bytes across %d chunks",
            voice, sentence.text, total_pcm, seq,
        )
        yield AudioOutput(
            samples=b"",
            sample_rate=24_000,
            channels=1,
            format="pcm_s16le",
            voice_id=voice,
            sequence=seq,
            final=True,
        )
