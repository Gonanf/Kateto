from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, override


PCM_S16LE = "pcm_s16le"


@dataclass(frozen=True, slots=True)
class AudioOutputFormatError(Exception):
    format: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"unsupported audio output format {self.format!r}: {self.reason}"


@dataclass(frozen=True, slots=True)
class AudioOutputDeviceError(Exception):
    device: str | None
    reason: str

    @override
    def __str__(self) -> str:
        selected = "default" if self.device is None else self.device
        return f"audio output cannot use configured device {selected!r}: {self.reason}"


class AudioOutputStream(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...

    def write(self, data: bytes) -> object: ...


class AudioOutputFactory(Protocol):
    def create(
        self,
        *,
        device: str | None,
        sample_rate: int,
        channels: int,
    ) -> AudioOutputStream: ...
