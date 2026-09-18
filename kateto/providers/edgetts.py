from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from loguru import logger
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Self

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, TextChunk, WordTiming

log = logger

_CHUNK_SIZE = 65536  # ~1.4s PCM at 24000Hz s16le mono
_TICKS_PER_MS = 10_000  # EdgeTTS WordBoundary offsets are 100ns ticks


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

        communicate = edge_tts.Communicate(
            text=sentence.text, voice=voice, boundary="WordBoundary"
        )
        # Word-level timing for lip-synced captions (sentence-relative ms).
        # Collected in the feed task; attached to the final AudioOutput below.
        word_timings: list[WordTiming] = []

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
            try:
                async for chunk in communicate.stream():
                    if chunk.get("type") == "audio":
                        audio_data: bytes | None = chunk.get("data")
                        if audio_data:
                            stdin.write(audio_data)
                            await stdin.drain()
                    elif chunk.get("type") == "WordBoundary":
                        word = str(chunk.get("text") or "").strip()
                        if word:
                            try:
                                start_ms = float(chunk.get("offset", 0)) / _TICKS_PER_MS
                                end_ms = start_ms + float(chunk.get("duration", 0)) / _TICKS_PER_MS
                            except (TypeError, ValueError):
                                continue
                            if end_ms >= start_ms:
                                word_timings.append(
                                    WordTiming(text=word, start_ms=start_ms, end_ms=end_ms)
                                )
            except Exception as exc:
                log.warning("[edgetts] stream feed error: {}", exc)
            finally:
                try:
                    await stdin.drain()
                except Exception:
                    pass
                try:
                    stdin.close()
                except Exception:
                    pass

        feed_task = asyncio.create_task(_feed())
        seq = 0
        total_pcm = 0
        final_yielded = False
        log.info("[edgetts-provider] ffmpeg start voice={} chars={}", voice, len(sentence.text))
        try:
            while True:
                pcm = await stdout.read(_CHUNK_SIZE)
                if not pcm:
                    break
                total_pcm += len(pcm)
                log.info(
                    "[edgetts-provider] pcm voice={} seq={} bytes={} total={} words={}",
                    voice, seq, len(pcm), total_pcm, len(word_timings),
                )
                yield AudioOutput(
                    samples=pcm,
                    sample_rate=24_000,
                    channels=1,
                    format="pcm_s16le",
                    voice_id=voice,
                    sequence=seq,
                    text=sentence.text,
                    # Cumulative snapshot: lets consumers reveal words as the
                    # sentence streams instead of waiting for the final event.
                    words=list(word_timings) or None,
                )
                seq += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A mid-stream read failure must still close the player's lane:
            # without this final the mixer would wedge behind it for 10s.
            log.warning("[edgetts-provider] pcm read failed voice={}: {}", voice, exc)
            yield AudioOutput(
                samples=b"",
                sample_rate=24_000,
                channels=1,
                format="pcm_s16le",
                voice_id=voice,
                sequence=seq,
                final=True,
                text=sentence.text,
                words=list(word_timings) or None,
            )
            final_yielded = True
            seq += 1
        finally:
            current_task = asyncio.current_task()
            cancellation_requested = False
            if current_task is not None:
                cancellation_requested = current_task.cancelling() > 0
            log.info(
                "[edgetts-provider] ffmpeg end voice={} total_pcm={} chunks={} words={} cancelled={} returncode={}",
                voice, total_pcm, seq, len(word_timings),
                cancellation_requested, proc.returncode,
            )
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
            "[edgetts] TTS for voice={} text={!r}: {} PCM bytes across {} chunks",
            voice, sentence.text, total_pcm, seq,
        )
        if final_yielded:
            return
        yield AudioOutput(
            samples=b"",
            sample_rate=24_000,
            channels=1,
            format="pcm_s16le",
            voice_id=voice,
            sequence=seq,
            final=True,
            text=sentence.text,
            words=word_timings or None,
        )
