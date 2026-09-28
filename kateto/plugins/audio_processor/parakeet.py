from __future__ import annotations

import wave
from io import BytesIO
from typing import TYPE_CHECKING, override

from loguru import logger

from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, TranscriptionData
from kateto.core.plugin import Plugin

log = logger

if TYPE_CHECKING:
    from kateto.providers import ParakeetProvider, ParakeetServerProvider, ParakeetStreamProvider


def _raw_pcm(data: AudioData) -> bytes:
    if data.format == "pcm_s16le":
        return data.samples
    if data.format == "wav":
        try:
            with wave.open(BytesIO(data.samples), "rb") as wav_file:
                return wav_file.readframes(wav_file.getnframes())
        except (wave.Error, EOFError):
            return data.samples[44:]
    return data.samples


class ParakeetAudioProcessor(Plugin):
    """Local parakeet (CrispASR) transcription, mirror of the whisper processor.

    Capability ``transcribe`` like ``audio_processor_whisper``; keep exactly one
    of the two enabled per config so a chunk is not transcribed twice.
    Transport is selected by ``[plugin.audio_processor_parakeet] backend``:
    ``server`` (default, model resident in an externally-launched CrispASR
    ``--server``), ``cli`` (per-invocation binary) or ``stream`` (the binary
    open once in ``--stream --stream-json``; PCM fed per ``audio_chunk``).
    Fail-open: any provider error (missing server/binary, hang, empty output) is
    logged and yields no transcription event instead of taking the runtime down.
    """

    def __init__(self, settings: PluginSettings) -> None:
        super().__init__("audio_processor_parakeet", capabilities=("transcribe",))
        self._settings: PluginSettings = settings
        self._provider: ParakeetProvider | ParakeetServerProvider | ParakeetStreamProvider | None = None

    @override
    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("audio_chunk", AudioData)
        manager.register_event("transcription", TranscriptionData)

    @override
    async def enable(self) -> None:
        from kateto.providers import ParakeetServerProvider, ParakeetStreamProvider, create_parakeet_provider

        provider = create_parakeet_provider(self._settings)
        await provider.__aenter__()
        self._provider = provider
        backend = getattr(provider, "backend", "cli")
        if isinstance(provider, ParakeetStreamProvider):
            provider.on_event = self._on_stream_event
            if getattr(provider, "_degraded", False):
                log.warning("[parakeet] stream backend selected but the child failed to spawn — chunks are dropped (fail-open)")
            log.info(
                "[parakeet] enabled backend=stream step={}ms silence={}ms motor={} model={}",
                provider.stream_step_ms,
                provider.stream_final_on_silence_ms,
                provider.motor,
                provider.model,
            )
        elif isinstance(provider, ParakeetServerProvider):
            if not await provider.health():
                # Clear warning but do NOT fail enable: the provider fail-opens
                # per transcribe, so the voice flow survives a not-yet-up server.
                log.warning(
                    "[parakeet] server backend selected but /health not OK at {} — "
                    "transcribes will fail-open until the CrispASR server is up",
                    provider.endpoint,
                )
            log.info(
                "[parakeet] enabled backend={} endpoint={} motor={}",
                backend,
                provider.endpoint,
                provider.motor,
            )
        else:
            log.info(
                "[parakeet] enabled backend={} motor={} model={}",
                backend,
                provider.motor,
                provider.model,
            )

    @override
    async def disable(self) -> None:
        if self._provider is not None:
            await self._provider.aclose()
            self._provider = None

    async def _on_stream_event(self, transcription: TranscriptionData) -> None:
        if not transcription.text or not transcription.text.strip():
            return
        kind = "partial" if transcription.partial else "final"
        log.info("[parakeet] Streamed {}: {!r}", kind, transcription.text)
        _ = await self.required_manager.emit("transcription", transcription, source=self.name)

    async def on_audio_chunk(self, data: AudioData) -> None:
        from kateto.providers import ParakeetStreamProvider

        provider = self._provider
        if provider is None:
            log.warning("[parakeet] processor must be enabled before transcribing; dropping chunk")
            return
        if isinstance(provider, ParakeetStreamProvider):
            try:
                await provider.feed(_raw_pcm(data))
            except Exception as error:  # noqa: BROAD_EXCEPT_OK
                log.error("[parakeet] Stream feed error: {}", error)
            return
        try:
            transcription = await provider.transcribe(data)
        except Exception as error:  # noqa: BROAD_EXCEPT_OK
            # Fail-open: a broken/hung binary must not take the voice flow down.
            log.error("[parakeet] Transcription error: {}", error)
            return
        if not transcription.text or not transcription.text.strip():
            log.debug("[parakeet] No speech detected in audio chunk")
            return
        log.info("[parakeet] Transcribed: {!r}", transcription.text)
        _ = await self.required_manager.emit("transcription", transcription, source=self.name)
