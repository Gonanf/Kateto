from __future__ import annotations

from dataclasses import dataclass
from typing import override


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

