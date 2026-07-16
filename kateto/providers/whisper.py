from __future__ import annotations

from io import BytesIO
from typing import Final
import wave

import httpx
from pydantic import ValidationError

from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, TranscriptionData

from ._http import HttpProvider, configured_endpoint
from ._models import WhisperResponse
from .errors import MalformedUpstreamResponse, UnsupportedAudioPayload


WHISPER_INFERENCE_PATH: Final = "/inference"


class WhisperProvider(HttpProvider):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        endpoint: str | None = None,
        path: str = WHISPER_INFERENCE_PATH,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        super().__init__(
            provider_name="whisper",
            endpoint=configured_endpoint(settings, provider="whisper", endpoint=endpoint),
            client=client,
            timeout_s=timeout_s,
        )
        self._path = path

    async def transcribe(self, audio: AudioData) -> TranscriptionData:
        response = await self._client_or_raise().post(
            self._url(self._path),
            data={"response_format": "json", "temperature": "0.0"},
            files={"file": ("audio.wav", _wav_bytes(audio), "audio/wav")},
            headers=self._request_headers,
        )
        response.raise_for_status()
        try:
            payload = WhisperResponse.model_validate_json(response.content)
        except ValidationError as error:
            raise MalformedUpstreamResponse(provider="whisper", reason="expected transcription JSON") from error
        return TranscriptionData(
            text=payload.text,
            language=payload.language,
            confidence=payload.confidence,
            duration_ms=audio.duration_ms if audio.duration_ms > 0 else None,
        )


def _wav_bytes(audio: AudioData) -> bytes:
    match audio.format:
        case "wav":
            return audio.samples
        case "pcm_s16le":
            frame_size = audio.channels * 2
            if len(audio.samples) % frame_size != 0:
                raise UnsupportedAudioPayload(format="pcm_s16le with incomplete sample frame")
            with BytesIO() as buffer:
                with wave.open(buffer, "wb") as wav_file:
                    wav_file.setnchannels(audio.channels)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(audio.sample_rate)
                    wav_file.writeframes(audio.samples)
                return buffer.getvalue()
        case unsupported:
            raise UnsupportedAudioPayload(format=unsupported)
