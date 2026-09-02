from __future__ import annotations

import asyncio
import io
import re
import wave
from collections.abc import Mapping
from typing import Any, override

from loguru import logger
from pydantic import BaseModel

from kateto.core.config import PluginConfigRegistry, PluginSettings
from kateto.core.event import AudioOutput, AudioOutputStatus, AudioOutputStatusData, EventEnvelope, InterruptData, TextChunk
from kateto.core.plugin import EventHandler, Plugin
from kateto.providers.boson_tts import BosonTTSProvider

# Register dynamic config parameters contributed by this plugin
PluginConfigRegistry.register_plugin_param("audio_output_boson", "default_voice", "chloe")
PluginConfigRegistry.register_voice_param("boson_voice", None)


def _wav_to_pcm(wav_bytes: bytes) -> tuple[bytes, int, int]:
    """Parse WAV byte stream and extract raw PCM samples (channels, sample_rate)."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            pcm = wf.readframes(wf.getnframes())
            return pcm, sample_rate, channels
    except Exception:
        return wav_bytes[44:] if len(wav_bytes) > 44 else wav_bytes, 24000, 1


class BosonAudioOutput(Plugin):
    """Audio output plugin leveraging Boson AI Higgs TTS 3."""

    def __init__(
        self,
        settings: PluginSettings,
        *,
        provider: BosonTTSProvider | None = None,
        voice_map: Mapping[str, Mapping[str, Any]] | None = None,
        default_voice: str | None = None,
    ) -> None:
        super().__init__("audio_output_boson", capabilities=("audio_output", "tts"))
        self._settings = settings
        self._provider = provider or BosonTTSProvider(settings)
        self._voice_map = dict(voice_map) if voice_map is not None else {}
        self._default_voice = default_voice or settings.get("default_voice", "chloe") or "chloe"
        self._interrupted = False
        self._current_voice: str | None = None
        self._stream_task: asyncio.Task[None] | None = None
        self._playing = False

    @override
    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("text_chunk", TextChunk)
        manager.register_event("audio_output", AudioOutput)
        manager.register_event("audio_output_status", AudioOutputStatusData)

    @override
    async def _enqueue(
        self, envelope: EventEnvelope[BaseModel], handler: EventHandler
    ) -> None:
        match envelope.name, envelope.data:
            case "interrupt", InterruptData() as interrupt:
                await self.on_interrupt(interrupt)
            case _:
                await super()._enqueue(envelope, handler)

    async def on_interrupt(self, data: InterruptData) -> None:
        self._interrupted = True
        if self._stream_task is not None and not self._stream_task.done():
            self._stream_task.cancel()
        await self._set_playing(False)

    async def on_text_chunk(self, data: TextChunk) -> None:
        if data.voice_id is None:
            return
        if not data.text or not data.text.strip():
            if data.final:
                await self.required_manager.emit(
                    "audio_output",
                    AudioOutput(
                        samples=b"",
                        sample_rate=24_000,
                        channels=1,
                        format="pcm_s16le",
                        voice_id=data.voice_id,
                        final=True,
                    ),
                    source=self.name,
                )
            return

        if self._interrupted or (
            self._stream_task is not None
            and not self._stream_task.done()
            and self._current_voice != data.voice_id
        ):
            if self._stream_task is not None and not self._stream_task.done():
                self._stream_task.cancel()

        self._interrupted = False
        self._current_voice = data.voice_id
        task = asyncio.create_task(self._emit_pcm(data), name=f"kateto-boson-{data.voice_id}")
        self._stream_task = task
        try:
            await task
        except asyncio.CancelledError:
            if not self._interrupted:
                raise
        finally:
            if self._stream_task is task:
                self._stream_task = None
            await self._set_playing(False)

    async def _emit_pcm(self, data: TextChunk) -> None:
        raw_text = (data.text or "").strip()
        if not raw_text:
            return
        voice_id_str = str(data.voice_id).casefold()
        voice_cfg = self._voice_map.get(voice_id_str, {})
        boson_voice = voice_cfg.get("boson_voice") or self._default_voice
        await self._set_playing(True)

        sentences = [s.strip() for s in re.split(r"(?<=[.!?\n])\s+", raw_text) if s.strip()]
        if not sentences:
            sentences = [raw_text]

        for idx, sentence in enumerate(sentences):
            if self._interrupted:
                break
            try:
                wav_data = await self._provider.generate_speech(
                    sentence,
                    voice=boson_voice,
                    response_format="wav",
                )
                if not wav_data or self._interrupted:
                    continue
                pcm_bytes, srate, ch = _wav_to_pcm(wav_data)
                is_final_sentence = (idx == len(sentences) - 1) and data.final

                chunk_size = 2048
                for offset in range(0, len(pcm_bytes), chunk_size):
                    if self._interrupted:
                        break
                    chunk = pcm_bytes[offset:offset + chunk_size]
                    await self.required_manager.emit(
                        "audio_output",
                        AudioOutput(
                            samples=chunk,
                            sample_rate=srate,
                            channels=ch,
                            format="pcm_s16le",
                            voice_id=data.voice_id,
                            sequence=idx,
                            final=False,
                        ),
                        source=self.name,
                    )
                if is_final_sentence and not self._interrupted:
                    await self.required_manager.emit(
                        "audio_output",
                        AudioOutput(
                            samples=b"",
                            sample_rate=srate,
                            channels=ch,
                            format="pcm_s16le",
                            voice_id=data.voice_id,
                            sequence=idx + 1,
                            final=True,
                        ),
                        source=self.name,
                    )
            except Exception as exc:
                logger.warning("[boson_tts] Speech generation failed for {}: {}", boson_voice, exc)

    async def _set_playing(self, playing: bool) -> None:
        if self._playing != playing:
            self._playing = playing
            status = AudioOutputStatus.PLAYING if playing else AudioOutputStatus.IDLE
            await self.required_manager.emit(
                "audio_output_status",
                AudioOutputStatusData(status=status),
                source=self.name,
            )


# Backwards compatibility alias
BosonTTSPlugin = BosonAudioOutput
