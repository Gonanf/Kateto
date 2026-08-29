from __future__ import annotations

from loguru import logger
from collections.abc import AsyncIterator
import struct
from wave import Wave_read

import httpx

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, TextChunk

log = logger

from ._http import HttpProvider, configured_endpoint
from ._models import CambRequest
from .errors import MalformedUpstreamResponse


def _wav_to_pcm(wav: bytes, default_sample_rate: int = 24_000) -> tuple[bytes, int]:
    if wav.startswith(b"RIFF"):
        try:
            with Wave_read(__import__("io").BytesIO(wav)) as w:
                framerate = w.getframerate()
                data = w.readframes(w.getnframes())
            return data, framerate
        except Exception as err:
            log.warning("[camb] Failed to parse RIFF WAV bytes: {}", err)
    if len(wav) % 2 != 0:
        wav = wav[: len(wav) - 1]
    return wav, default_sample_rate


class CambProvider(HttpProvider):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        endpoint: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        headers = {"x-api-key": settings.api_key} if settings.api_key else {}
        endpoint_val = endpoint or settings.endpoint or "https://client.camb.ai/apis"
        super().__init__(
            provider_name="camb",
            endpoint=endpoint_val,
            client=client,
            timeout_s=timeout_s,
            headers=headers,
        )
        self._model = settings.model
        self._sample_rate = settings.sample_rate if settings.sample_rate is not None else 24_000

    async def stream_sentence(
        self,
        sentence: TextChunk,
        *,
        voice_id: int,
        language: str,
    ) -> AsyncIterator[AudioOutput]:
        async for chunk in self._generate_wav(sentence, voice_id=voice_id, language=language):
            yield chunk

    async def _generate_wav(
        self,
        sentence: TextChunk,
        *,
        voice_id: int,
        language: str,
    ) -> AsyncIterator[AudioOutput]:
        request = CambRequest(
            text=sentence.text,
            language=language,
            voice_id=voice_id,
            speech_model=self._model,
        )
        # ponytail: single timeout for the whole request, camb.ai can take 60s+
        timeout = httpx.Timeout(connect=self._timeout_s, read=120, write=self._timeout_s, pool=self._timeout_s)
        async with self._client_or_raise().stream(
            "POST",
            self._url("/tts-stream"),
            json=request.model_dump(mode="json", exclude_none=True),
            headers=self._request_headers,
            timeout=timeout,
        ) as response:
            if response.status_code == 422:
                body = await response.aread()
                raise MalformedUpstreamResponse(
                    provider="camb",
                    reason=f"validation error (check language/voice_id): {body.decode(errors='replace')}",
                )
            response.raise_for_status()
            out_voice_id = sentence.voice_id or str(voice_id)
            data_started = False
            sample_rate = self._sample_rate or 24_000
            seq = 0
            pcm_buffer = bytearray()

            async for raw_chunk in response.aiter_bytes():
                if not raw_chunk:
                    continue
                if not data_started:
                    if raw_chunk.startswith(b"RIFF"):
                        if len(raw_chunk) >= 28:
                            sample_rate = struct.unpack("<I", raw_chunk[24:28])[0]
                        data_pos = raw_chunk.find(b"data")
                        if data_pos != -1:
                            pcm_payload = raw_chunk[data_pos + 8 :]
                        else:
                            pcm_payload = raw_chunk[44:]
                        data_started = True
                        if pcm_payload:
                            pcm_buffer.extend(pcm_payload)
                    else:
                        data_started = True
                        pcm_buffer.extend(raw_chunk)
                else:
                    pcm_buffer.extend(raw_chunk)

                step = 4 if sample_rate == 48_000 else 2
                valid_len = len(pcm_buffer) - (len(pcm_buffer) % step)
                if valid_len >= 4096:
                    raw_samples = bytes(pcm_buffer[:valid_len])
                    pcm_buffer = pcm_buffer[valid_len:]
                    if sample_rate == 48_000:
                        out_samples = memoryview(raw_samples).cast("h")[::2].tobytes()
                        out_rate = 24_000
                    else:
                        out_samples = raw_samples
                        out_rate = sample_rate

                    yield AudioOutput(
                        samples=out_samples,
                        sample_rate=out_rate,
                        channels=1,
                        format="pcm_s16le",
                        voice_id=out_voice_id,
                        sequence=seq,
                    )
                    seq += 1

            # Flush remaining buffer
            step = 4 if sample_rate == 48_000 else 2
            valid_len = len(pcm_buffer) - (len(pcm_buffer) % step)
            if valid_len > 0:
                raw_samples = bytes(pcm_buffer[:valid_len])
                if sample_rate == 48_000:
                    out_samples = memoryview(raw_samples).cast("h")[::2].tobytes()
                    out_rate = 24_000
                else:
                    out_samples = raw_samples
                    out_rate = sample_rate

                yield AudioOutput(
                    samples=out_samples,
                    sample_rate=out_rate,
                    channels=1,
                    format="pcm_s16le",
                    voice_id=out_voice_id,
                    sequence=seq,
                )
                seq += 1

            yield AudioOutput(
                samples=b"",
                sample_rate=24_000 if sample_rate == 48_000 else sample_rate,
                channels=1,
                format="pcm_s16le",
                voice_id=out_voice_id,
                sequence=seq,
                final=True,
            )
