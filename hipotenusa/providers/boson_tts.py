from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import httpx


# ponytail: shared client is never closed — process-lifetime reuse is the point
@lru_cache(maxsize=16)
def _httpx_client(endpoint: str) -> httpx.AsyncClient:
    return httpx.AsyncClient()


class BosonTTSProvider:
    """TTS Provider for Boson.ai API (https://api.boson.ai/v1/audio/speech)."""

    def __init__(
        self,
        settings: Any = None,
        *,
        api_key: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        if settings is not None:
            self.endpoint = getattr(settings, "endpoint", None) or endpoint or "https://api.boson.ai/v1/audio/speech"
            self.api_key = getattr(settings, "api_key", None) or api_key or os.environ.get("BOSON_API_KEY", "")
            self.model = getattr(settings, "model", None) or model or "higgs-tts-3"
            self.voice = voice or getattr(settings, "default_voice", None)
        else:
            self.api_key = api_key or os.environ.get("BOSON_API_KEY", "")
            self.model = model or "higgs-tts-3"
            self.voice = voice
            self.endpoint = endpoint or "https://api.boson.ai/v1/audio/speech"

    async def generate_speech(
        self,
        text: str,
        *,
        model: str | None = None,
        voice: str | None = None,
        response_format: str = "wav",
    ) -> bytes:
        if not text:
            return b""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model or self.model,
            "input": text,
            "response_format": response_format,
        }
        effective_voice = voice or self.voice
        if effective_voice:
            payload["voice"] = effective_voice

        client = _httpx_client(self.endpoint)
        resp = await client.post(self.endpoint, json=payload, headers=headers, timeout=10.0)
        resp.raise_for_status()
        return resp.content
