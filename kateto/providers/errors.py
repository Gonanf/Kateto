from __future__ import annotations

from dataclasses import dataclass

from kateto.core.exceptions import ProviderError


@dataclass(slots=True)
class MalformedUpstreamResponse(Exception):
    provider: str
    reason: str

    def __str__(self) -> str:
        return f"{self.provider} returned malformed upstream data: {self.reason}"


@dataclass(slots=True)
class UnsupportedAudioPayload(Exception):
    format: str

    def __str__(self) -> str:
        return f"unsupported audio payload format: {self.format}"
