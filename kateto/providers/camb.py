from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from wave import Wave_read

import httpx

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, TextChunk

log = logging.getLogger(__name__)

from ._http import HttpProvider, configured_endpoint
from ._models import CambRequest
from .errors import MalformedUpstreamResponse


def _wav_to_pcm(wav: bytes) -> tuple[bytes, int]:
    with Wave_read(__import__("io").BytesIO(wav)) as w:
        framerate = w.getframerate()
        data = w.readframes(w.getnframes())
    return data, framerate


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
        super().__init__(
            provider_name="camb",
            endpoint=configured_endpoint(settings, provider="camb", endpoint=endpoint),
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
            body = await response.aread()
            if not body:
                return
            log.debug("[camb] TTS stream for voice_id=%d language=%s: %d bytes", voice_id, language, len(body))
            pcm, sample_rate = _wav_to_pcm(body)
            yield AudioOutput(
                samples=pcm,
                sample_rate=sample_rate,
                channels=1,
                format="pcm_s16le",
                voice_id=str(voice_id),
                sequence=0,
            )
            yield AudioOutput(
                samples=b"",
                sample_rate=sample_rate,
                channels=1,
                format="pcm_s16le",
                voice_id=str(voice_id),
                sequence=1,
                final=True,
            )
