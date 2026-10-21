from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from kateto.core.event import AudioOutput, InterruptData, WordTiming
from kateto.mask.audio_bridge import MASK_PROTOCOL, MaskAudioBridge


class FakeWS:
    def __init__(self) -> None:
        self.received: list[dict] = []
        self.accepted: bool = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.received.append(payload)

    async def receive_text(self) -> str:
        await asyncio.sleep(3600)
        return ""


class DeadWS(FakeWS):
    async def send_json(self, payload: dict) -> None:
        raise RuntimeError("socket dead")


def make_audio(**overrides) -> AudioOutput:
    kwargs = {
        "samples": b"\x01\x02" * 500,
        "sample_rate": 24000,
        "channels": 1,
        "format": "pcm_s16le",
        "voice_id": "jane",
        "sequence": 0,
        "final": False,
        "rms": 0.3,
        "text": None,
        "words": None,
    }
    kwargs.update(overrides)
    return AudioOutput(**kwargs)


@pytest.mark.asyncio
async def test_audio_frame_has_base64_pcm_and_metadata():
    bridge = MaskAudioBridge()
    ws = FakeWS()
    await bridge.register(ws)

    await bridge.on_audio_output(make_audio(voice_id="jane", sequence=2, rms=0.31, text="hola"))

    frame = ws.received[-1]
    assert frame["event"] == "audio_output"
    assert frame["type"] == "audio"
    assert frame["protocol"] == MASK_PROTOCOL
    assert frame["voice_id"] == "jane"
    assert frame["sample_rate"] == 24000
    assert frame["channels"] == 1
    assert frame["format"] == "pcm_s16le"
    assert frame["seq"] == 2
    assert frame["final"] is False
    assert frame["audio_b64"] == base64.b64encode(b"\x01\x02" * 500).decode("ascii")
    assert frame["n_bytes"] == 1000
    assert frame["rms"] == 0.31
    assert frame["is_speaking"] is True
    assert frame["text"] == "hola"
    assert isinstance(frame["t_ms"], int)
    assert bridge.turn_active is True


@pytest.mark.asyncio
async def test_frame_keeps_wire_format_pcm_s16le():
    bridge = MaskAudioBridge()
    ws = FakeWS()
    await bridge.register(ws)

    await bridge.on_audio_output(make_audio(sample_rate=22050, format="pcm_s16le", channels=1))

    frame = ws.received[-1]
    assert frame["format"] == "pcm_s16le"
    assert frame["sample_rate"] == 22050
    assert frame["channels"] == 1
    assert base64.b64decode(frame["audio_b64"]) == b"\x01\x02" * 500


@pytest.mark.asyncio
async def test_final_frame_without_samples_still_reaches_phone():
    bridge = MaskAudioBridge()
    ws = FakeWS()
    await bridge.register(ws)

    await bridge.on_audio_output(
        AudioOutput(samples=b"", sample_rate=24000, channels=1, format="pcm_s16le", final=True)
    )

    frame = ws.received[-1]
    assert frame["event"] == "audio_output"
    assert frame["audio_b64"] == ""
    assert frame["n_bytes"] == 0
    assert frame["final"] is True
    assert frame["is_speaking"] is False
    assert bridge.turn_active is False


@pytest.mark.asyncio
async def test_empty_non_final_chunk_is_not_sent():
    bridge = MaskAudioBridge()
    ws = FakeWS()
    await bridge.register(ws)

    await bridge.on_audio_output(
        AudioOutput(samples=b"", sample_rate=24000, channels=1, format="pcm_s16le", final=False)
    )

    assert bridge.connected == 1
    assert len(ws.received) == 1  # only mask_ready
    assert bridge.frames_sent == 0


@pytest.mark.asyncio
async def test_rms_is_computed_when_absent():
    bridge = MaskAudioBridge()
    ws = FakeWS()
    await bridge.register(ws)

    samples = (0x4000).to_bytes(2, "little") * 1000  # 16384 -> 0.5
    await bridge.on_audio_output(make_audio(samples=samples, rms=None))

    frame = ws.received[-1]
    assert frame["rms"] == pytest.approx(0.5, abs=0.01)


@pytest.mark.asyncio
async def test_rms_clamped():
    bridge = MaskAudioBridge()
    samples = b"\x00\x00" * 10

    high = SimpleNamespace(
        samples=samples, sample_rate=24000, channels=1, format="pcm_s16le",
        voice_id="jane", sequence=0, final=False, rms=1.5, text=None, words=None,
    )
    low = SimpleNamespace(
        samples=samples, sample_rate=24000, channels=1, format="pcm_s16le",
        voice_id="jane", sequence=0, final=False, rms=-0.5, text=None, words=None,
    )

    assert bridge.frame_for(high)["rms"] == 1.0
    assert bridge.frame_for(low)["rms"] == 0.0


@pytest.mark.asyncio
async def test_words_are_serialized():
    bridge = MaskAudioBridge()
    ws = FakeWS()
    await bridge.register(ws)

    words = [WordTiming(text="hola", start_ms=0.0, end_ms=210.0)]
    await bridge.on_audio_output(make_audio(words=words))
    assert ws.received[-1]["words"] == [{"text": "hola", "start_ms": 0.0, "end_ms": 210.0}]

    await bridge.on_audio_output(make_audio(words=None))
    assert ws.received[-1]["words"] is None


@pytest.mark.asyncio
async def test_interrupt_frame_and_turn_state():
    bridge = MaskAudioBridge()
    ws = FakeWS()
    await bridge.register(ws)

    await bridge.on_audio_output(make_audio(final=False))
    assert bridge.turn_active is True

    await bridge.on_interrupt(InterruptData(reason="voice_activity", dept="fun"))

    assert bridge.turn_active is False
    frame = ws.received[-1]
    assert frame["event"] == "interrupt"
    assert frame["type"] == "interrupt"
    assert frame["protocol"] == MASK_PROTOCOL
    assert frame["reason"] == "voice_activity"
    assert frame["dept"] == "fun"


@pytest.mark.asyncio
async def test_dead_socket_is_dropped_without_raising():
    bridge = MaskAudioBridge()
    dead = DeadWS()
    await bridge.register(dead)  # must not raise
    assert bridge.connected == 0

    good = FakeWS()
    bridge._sockets.add(good)
    await bridge.on_audio_output(make_audio(samples=b"\x01\x02" * 100))

    assert bridge.connected == 1
    assert good.received[-1]["event"] == "audio_output"


@pytest.mark.asyncio
async def test_no_sockets_is_a_noop():
    bridge = MaskAudioBridge()

    await bridge.on_audio_output(make_audio())
    await bridge.on_interrupt(InterruptData(reason="voice_activity"))

    assert bridge.connected == 0
    assert bridge.frames_sent == 0


@pytest.mark.asyncio
async def test_ready_frame_on_register():
    bridge = MaskAudioBridge()
    ws = FakeWS()

    await bridge.register(ws)

    assert ws.received[0] == {"event": "mask_ready", "type": "ready", "protocol": MASK_PROTOCOL}


@pytest.mark.asyncio
async def test_end_to_end_websocket_roundtrip():
    import uvicorn
    import websockets
    from fastapi import FastAPI, WebSocket

    bridge = MaskAudioBridge()
    app = FastAPI()

    @app.websocket("/ws/mask")
    async def mask_ws(ws: WebSocket) -> None:
        await bridge.serve(ws)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)

        port = server.servers[0].sockets[0].getsockname()[1]
        uri = f"ws://127.0.0.1:{port}/ws/mask"

        async with websockets.connect(uri) as client:
            ready = json.loads(await asyncio.wait_for(client.recv(), 5))
            assert ready["event"] == "mask_ready"

            await bridge.on_audio_output(
                AudioOutput(
                    samples=b"\x01\x02" * 500,
                    sample_rate=24000,
                    channels=1,
                    format="pcm_s16le",
                    voice_id="doktor",
                    sequence=0,
                    final=False,
                    rms=0.2,
                    text="dale",
                )
            )

            frame = json.loads(await asyncio.wait_for(client.recv(), 5))
            assert frame["event"] == "audio_output"
            assert frame["sample_rate"] == 24000
            assert frame["channels"] == 1
            assert base64.b64decode(frame["audio_b64"]) == b"\x01\x02" * 500
            assert frame["text"] == "dale"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)


@pytest.mark.asyncio
async def test_no_regression_visual_overlay_event_contract():
    data = AudioOutput(samples=b"", sample_rate=24000, channels=1, format="pcm_s16le", final=True)
    bridge = MaskAudioBridge()

    frame = bridge.frame_for(data)

    assert frame is not None
    assert frame["final"] is True
    assert frame["audio_b64"] == ""
