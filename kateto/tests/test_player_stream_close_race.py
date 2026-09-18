from __future__ import annotations

import asyncio
import threading
import time

import pytest
import sounddevice

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, InterruptData
from kateto.plugins.audio_output.player import AudioOutputPlayer, SoundDeviceOutputStream


class OrderRecordingRawStream:
    """Fake PortAudio stream: records op order, flags close-during-write.

    write() blocks like the real C call (sleep), so a stop()/close() that
    overlaps it models the libasound segfault path (bug 113). Without the
    stream lock the violation is recorded; with it, the closer waits.
    """

    def __init__(self, *, write_delay: float = 0.05) -> None:
        self.ops: list[str] = []
        self.active = True
        self.writing = False
        self.violations: list[str] = []
        self.writes = 0
        self.write_delay = write_delay
        self.write_entered = threading.Event()
        self.fail_once = False

    def start(self) -> None:
        self.ops.append("start")
        self.active = True

    def stop(self) -> None:
        if self.writing:
            self.violations.append("stop-during-write")
        self.ops.append("stop")
        self.active = False

    def close(self) -> None:
        if self.writing:
            self.violations.append("close-during-write")
        self.ops.append("close")

    def write(self, data: bytes) -> int:
        if self.fail_once:
            self.fail_once = False
            raise sounddevice.PortAudioError("boom")
        self.writes += 1
        self.writing = True
        self.write_entered.set()
        try:
            time.sleep(self.write_delay)
            return len(data)
        finally:
            self.writing = False


class ScriptedFactory:
    """Factory handing out OrderRecordingRawStream wrappers on demand."""

    def __init__(self, *, write_delay: float = 0.05, fail_first_write: bool = False) -> None:
        self.streams: list[OrderRecordingRawStream] = []
        self.write_delay = write_delay
        self.fail_first_write = fail_first_write

    def create(self, *, device: str | None, sample_rate: int, channels: int):
        del device, sample_rate, channels
        raw = OrderRecordingRawStream(write_delay=self.write_delay)
        if self.fail_first_write:
            raw.fail_once = True
            self.fail_first_write = False
        self.streams.append(raw)
        return SoundDeviceOutputStream(raw, device=None)


def _pcm(n: int = 4000) -> bytes:
    return b"\x00" * n


def test_stop_close_never_overlap_inflight_write() -> None:
    # Given: a stream with a write blocked in flight (the to_thread worker).
    raw = OrderRecordingRawStream(write_delay=0.05)
    stream = SoundDeviceOutputStream(raw, device=None)
    writer = threading.Thread(target=stream.write, args=(_pcm(2048),))
    writer.start()
    assert raw.write_entered.wait(timeout=2.0)

    # When: the event loop thread stops and closes underneath it.
    stream.stop()
    stream.close()
    writer.join(timeout=2.0)

    # Then: no close overlapped the write (pre-fix this records violations),
    # and nothing deadlocked.
    assert not writer.is_alive()
    assert raw.violations == []
    assert raw.ops[-2:] == ["stop", "close"]


@pytest.mark.asyncio
async def test_interrupt_during_mixer_write_closes_cleanly() -> None:
    # Given: the mixer blocked inside a slow write (barge-in mid-playback).
    factory = ScriptedFactory(write_delay=0.2)
    player = AudioOutputPlayer(PluginSettings(enabled=True), player_factory=factory)
    await player.on_audio_output(
        AudioOutput(samples=_pcm(), sample_rate=24000, channels=1, format="pcm_s16le",
                    voice_id="racevoice", sequence=0, final=False)
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while not factory.streams or not factory.streams[0].write_entered.is_set():
        assert loop.time() < deadline, "mixer never started the write"
        await asyncio.sleep(0.01)
    raw = factory.streams[0]

    # When: the user barges in while the write is in flight.
    await player.on_interrupt(InterruptData(reason="voice_activity"))

    # Then: the close waited out the write (no overlap), the stream is gone,
    # the mixer is dead, and nothing is written after the close.
    assert raw.violations == []
    assert "close" in raw.ops
    assert player._stream is None
    assert player._mixer_task is None
    writes_after_close = raw.writes
    await asyncio.sleep(0.3)
    assert raw.writes == writes_after_close


@pytest.mark.asyncio
async def test_failed_write_still_closes_and_reopens() -> None:
    # Given: a stream whose first write raises (bug 88 host-error path).
    factory = ScriptedFactory(write_delay=0.01, fail_first_write=True)
    player = AudioOutputPlayer(PluginSettings(enabled=True), player_factory=factory)
    await player.on_audio_output(
        AudioOutput(samples=_pcm(), sample_rate=24000, channels=1, format="pcm_s16le",
                    voice_id="flakyvoice", sequence=0, final=False)
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while not (factory.streams and "close" in factory.streams[0].ops):
        assert loop.time() < deadline, "failed write never closed the stream"
        await asyncio.sleep(0.01)

    # When: the next chunk arrives after the failure.
    await player.on_audio_output(
        AudioOutput(samples=_pcm(), sample_rate=24000, channels=1, format="pcm_s16le",
                    voice_id="flakyvoice", sequence=1, final=False)
    )
    deadline = loop.time() + 5.0
    while not (len(factory.streams) > 1 and factory.streams[1].writes >= 1):
        assert loop.time() < deadline, "mixer never reopened the stream"
        await asyncio.sleep(0.01)

    # Then: the corrupted stream was closed and a fresh one took over.
    assert factory.streams[0].violations == []
    assert factory.streams[1].violations == []
    assert "close" in factory.streams[0].ops
    assert factory.streams[1].writes >= 1
