from __future__ import annotations

import argparse
import sys
import wave
from asyncio import Event, run, wait_for  # noqa: ANYIO_OK
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, assert_never

from kateto.core import Plugin, PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import AudioData
from kateto.plugins.audio_input.base import (
    AudioDeviceError,
    AudioInputConfig,
    CaptureCallback,
    CaptureStatus,
    CaptureTimeInfo,
    SileroVad,
)
from kateto.plugins.audio_input.meet import MeetAudioInput
from kateto.plugins.audio_input.mic import MicrophoneAudioInput


BUILTIN_UTTERANCE_PATH: Final = Path("fixtures/utterance.wav")
SPEECH_FRAME: Final = b"\x01\x00" * 1_600
SILENCE_FRAME: Final = b"\x00\x00" * 1_600
Source = Literal["mic", "meet"]


@dataclass(frozen=True, slots=True)
class FixtureWavError(Exception):
    path: Path
    reason: str

    def __str__(self) -> str:
        return f"invalid fixture WAV {self.path}: {self.reason}"


@dataclass(frozen=True, slots=True)
class FixtureSourceError(Exception):
    source: str

    def __str__(self) -> str:
        return f"unsupported fixture source: {self.source}"


class FixtureSileroModel:
    def speech_probability(self, samples: bytes, sample_rate: int) -> float:
        if sample_rate != 16_000:
            return 0.0
        return 0.9 if any(samples) else 0.1


class FixtureTimeInfo:
    pass


class FixtureStatus:
    def __bool__(self) -> bool:
        return False


FIXTURE_TIME_INFO: Final[CaptureTimeInfo] = FixtureTimeInfo()
FIXTURE_STATUS: Final[CaptureStatus] = FixtureStatus()


class FixtureCapture:
    def __init__(self, callback: CaptureCallback) -> None:
        self._callback = callback

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def close(self) -> None:
        return None

    def emit(self, samples: bytes) -> None:
        self._callback(
            samples,
            len(samples) // 2,
            FIXTURE_TIME_INFO,
            FIXTURE_STATUS,
        )


class FixtureCaptureFactory:
    def __init__(self) -> None:
        self.capture: FixtureCapture | None = None

    def create(self, config: AudioInputConfig, callback: CaptureCallback) -> FixtureCapture:
        if config.device == "missing":
            raise AudioDeviceError(
                source=config.source,
                device=config.device,
                reason="select an installed loopback or virtual input device",
            )
        self.capture = FixtureCapture(callback)
        return self.capture


class FixtureRecorder(Plugin):
    def __init__(self) -> None:
        super().__init__("audio_fixture_recorder")
        self.chunk: AudioData | None = None
        self.received = Event()

    async def on_audio_chunk(self, data: AudioData) -> None:
        self.chunk = data
        self.received.set()


def load_fixture_wav(path: Path) -> bytes:
    if path == BUILTIN_UTTERANCE_PATH and not path.exists():
        return SPEECH_FRAME
    try:
        with wave.open(str(path), "rb") as fixture_wav:
            if fixture_wav.getnchannels() != 1:
                raise FixtureWavError(path=path, reason="must be mono")
            if fixture_wav.getframerate() != 16_000:
                raise FixtureWavError(path=path, reason="must be 16 kHz")
            if fixture_wav.getsampwidth() != 2:
                raise FixtureWavError(path=path, reason="must use 16-bit PCM")
            return fixture_wav.readframes(fixture_wav.getnframes())
    except (OSError, wave.Error) as error:
        raise FixtureWavError(path=path, reason=str(error)) from error


async def run_fixture(source: Source, wav_path: Path | None, device: str | None) -> int:
    manager = PluginManager()
    recorder = FixtureRecorder()
    factory = FixtureCaptureFactory()
    source_device = device if device is not None else f"fixture-{source}"
    settings = PluginSettings(
        device=source_device,
        sample_rate=16_000,
        silence_timeout=0.1,
        vad_model="silero",
        interrupt_on_vad=True,
    )
    vad = SileroVad(FixtureSileroModel(), threshold=0.5)
    match source:
        case "mic":
            audio_input = MicrophoneAudioInput(
                settings,
                vad=vad,
                capture_factory=factory,
            )
        case "meet":
            audio_input = MeetAudioInput(
                settings,
                vad=vad,
                capture_factory=factory,
            )
        case unexpected:
            raise FixtureSourceError(source=unexpected)
            assert_never(unexpected)
    await manager.enable_plugin(recorder)
    try:
        await manager.enable_plugin(audio_input)
    except AudioDeviceError as error:
        print(f"device-error: {error}", file=sys.stderr)
        print(f"capture_task={'none' if audio_input.capture_task is None else 'running'}", file=sys.stderr)
        await manager.close()
        return 2
    if wav_path is None:
        print("fixture-error: --wav is required after capture starts", file=sys.stderr)
        await manager.close()
        return 2
    try:
        samples = load_fixture_wav(wav_path)
    except FixtureWavError as error:
        print(f"fixture-error: {error}", file=sys.stderr)
        await manager.close()
        return 2
    capture = factory.capture
    if capture is None:
        print("fixture-error: capture did not start", file=sys.stderr)
        await manager.close()
        return 2
    capture.emit(samples)
    capture.emit(SILENCE_FRAME)
    await wait_for(recorder.received.wait(), timeout=1)
    await manager.wait_for_idle()
    chunk = recorder.chunk
    if chunk is None:
        print("fixture-error: audio chunk missing", file=sys.stderr)
        await manager.close()
        return 2
    resume_gap_ms = audio_input.last_resume_gap_ms
    if resume_gap_ms is None:
        print("fixture-error: listener did not resume", file=sys.stderr)
        await manager.close()
        return 2
    print(
        f"audio_chunk source={chunk.source} samples={len(chunk.samples)} "
        f"format={chunk.format}",
    )
    print(
        f"resumed-listening source={chunk.source} gap_ms={resume_gap_ms:.3f}",
    )
    await manager.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("mic", "meet"), required=True)
    parser.add_argument("--wav", type=Path)
    parser.add_argument("--device")
    arguments = parser.parse_args()
    return run(run_fixture(parse_source(arguments.source), arguments.wav, arguments.device))


def parse_source(source: str) -> Source:
    match source:
        case "mic":
            return "mic"
        case "meet":
            return "meet"
        case unexpected:
            raise FixtureSourceError(source=unexpected)
            assert_never(unexpected)


if __name__ == "__main__":
    raise SystemExit(main())
