from __future__ import annotations

from collections.abc import AsyncIterator
from struct import Struct
from wave import Wave_read

import httpx

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, TextChunk

from ._http import HttpProvider, configured_endpoint
from ._models import ZonosRequest
from .errors import MalformedUpstreamResponse


_F32 = Struct("<f")


def _f32_to_s16(buf: bytearray) -> bytes:
    usable = len(buf) & ~3
    out = bytearray(usable // 2)
    for i in range(0, usable, 4):
        sample_f32 = _F32.unpack_from(buf, i)[0]
        sample_f32 = max(-1.0, min(1.0, sample_f32))
        s16 = int(sample_f32 * 32767)
        j = i // 2
        out[j] = s16 & 0xFF
        out[j + 1] = (s16 >> 8) & 0xFF
    del buf[:usable]
    return bytes(out)


def _wav_to_pcm(wav: bytes) -> tuple[bytes, int]:
    with Wave_read(io := __import__("io").BytesIO(wav)) as w:
        framerate = w.getframerate()
        data = w.readframes(w.getnframes())
    return data, framerate


class ZonosProvider(HttpProvider):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        endpoint: str | None = None,
        path: str = "/v1/audio/speech",
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        super().__init__(
            provider_name="zonos",
            endpoint=configured_endpoint(settings, provider="zonos", endpoint=endpoint),
            client=client,
            timeout_s=timeout_s,
        )
        self._model = settings.model
        self._path = path
        self._sample_rate = settings.sample_rate if settings.sample_rate is not None else 24_000
        self._stream = settings.stream

    async def _read_streaming(
        self, response: httpx.Response, *, voice_id: str
    ) -> AsyncIterator[AudioOutput]:
        content_type = response.headers.get("Content-Type", "").lower()
        audio_format = response.headers.get("X-Audio-Format", "int16").lower()
        sample_rate = int(response.headers.get("X-Audio-Sample-Rate", str(self._sample_rate)))
        if not content_type.startswith("audio/l16") and not content_type.startswith("application/octet-stream") and not content_type.startswith("audio/pcm"):
            raise MalformedUpstreamResponse(provider="zonos", reason="expected PCM audio content type")
        sequence = 0
        buf = bytearray()
        bytes_per_sample = 4 if audio_format == "float32" else 2
        async for chunk in response.aiter_bytes():
            if not chunk:
                continue
            buf.extend(chunk)
            while len(buf) >= bytes_per_sample:
                if audio_format == "float32":
                    sample_bytes = _f32_to_s16(buf)
                else:
                    sample_bytes = bytes(buf[:bytes_per_sample])
                    del buf[:bytes_per_sample]
                yield AudioOutput(
                    samples=sample_bytes,
                    sample_rate=sample_rate,
                    channels=1,
                    format="pcm_s16le",
                    voice_id=voice_id,
                    sequence=sequence,
                )
                sequence += 1
        yield AudioOutput(
            samples=b"",
            sample_rate=sample_rate,
            channels=1,
            format="pcm_s16le",
            voice_id=voice_id,
            sequence=sequence,
            final=True,
        )

    async def stream_sentence(self, sentence: TextChunk, *, voice_id: str) -> AsyncIterator[AudioOutput]:
        if self._stream:
            async for chunk in self._stream_sentence(sentence, voice_id=voice_id):
                yield chunk
        else:
            async for chunk in self._generate_wav(sentence, voice_id=voice_id):
                yield chunk

    async def _stream_sentence(self, sentence: TextChunk, *, voice_id: str) -> AsyncIterator[AudioOutput]:
        request = ZonosRequest(input=sentence.text, voice_id=voice_id, model=self._model, stream=True)
        async with self._client_or_raise().stream(
            "POST",
            self._url(self._path),
            json=request.model_dump(mode="json", exclude_none=True),
            headers=self._request_headers,
        ) as response:
            response.raise_for_status()
            async for chunk in self._read_streaming(response, voice_id=voice_id):
                yield chunk

    async def _generate_wav(self, sentence: TextChunk, *, voice_id: str) -> AsyncIterator[AudioOutput]:
        # ponytail: full-inference endpoint can take 60s+, use generous timeout
        timeout = httpx.Timeout(connect=self._timeout_s, read=120, write=self._timeout_s, pool=self._timeout_s)
        async with self._client_or_raise().stream(
            "POST",
            self._url("/tts/generate"),
            json={"text": sentence.text, "stream": False, "format": "wav"},
            headers=self._request_headers,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            body = await response.aread()
            if not body:
                return
            pcm, sample_rate = _wav_to_pcm(body)
            yield AudioOutput(
                samples=pcm,
                sample_rate=sample_rate,
                channels=1,
                format="pcm_s16le",
                voice_id=voice_id,
                sequence=0,
            )
            yield AudioOutput(
                samples=b"",
                sample_rate=sample_rate,
                channels=1,
                format="pcm_s16le",
                voice_id=voice_id,
                sequence=1,
                final=True,
            )
