from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, TextChunk

from ._http import HttpProvider, configured_endpoint
from ._models import ZonosRequest
from .errors import MalformedUpstreamResponse


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

    async def stream_sentence(self, sentence: TextChunk, *, voice_id: str) -> AsyncIterator[AudioOutput]:
        request = ZonosRequest(input=sentence.text, voice_id=voice_id, model=self._model)
        sequence = 0
        async with self._client_or_raise().stream(
            "POST",
            self._url(self._path),
            json=request.model_dump(mode="json", exclude_none=True),
            headers=self._request_headers,
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            if not content_type.startswith("audio/l16") and not content_type.startswith("application/octet-stream"):
                raise MalformedUpstreamResponse(provider="zonos", reason="expected PCM audio content type")
            async for samples in response.aiter_bytes():
                if samples:
                    yield AudioOutput(
                        samples=samples,
                        sample_rate=self._sample_rate,
                        channels=1,
                        format="pcm_s16le",
                        voice_id=voice_id,
                        sequence=sequence,
                    )
                    sequence += 1
        yield AudioOutput(
            samples=b"",
            sample_rate=self._sample_rate,
            channels=1,
            format="pcm_s16le",
            voice_id=voice_id,
            sequence=sequence,
            final=True,
        )
