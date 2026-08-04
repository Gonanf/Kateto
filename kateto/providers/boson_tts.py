from __future__ import annotations

import os
from typing import Any

import httpx


class BosonTTSProvider:
    """TTS Provider for Boson.ai API (https://api.boson.ai/v1/audio/speech)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "higgs-tts-3",
        voice: str | None = None,
        endpoint: str = "https://api.boson.ai/v1/audio/speech",
    ) -> None:
        self.api_key = api_key or os.environ.get("BOSON_API_KEY", "")
        self.model = model
        self.voice = voice
        self.endpoint = endpoint

    async def generate_speech(
        self,
        text: str,
        *,
        model: str | None = None,
        voice: str | None = None,
        response_format: str = "mp3",
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

        async with httpx.AsyncClient() as client:
            resp = await client.post(self.endpoint, json=payload, headers=headers, timeout=10.0)
            resp.raise_for_status()
            return resp.content
