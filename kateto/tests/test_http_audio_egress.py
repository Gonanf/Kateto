from __future__ import annotations

import asyncio
import base64
import json
import math
import socket
import struct
import time

import pytest
import websockets

from kateto.core.event import AudioData, AudioOutput, EventEnvelope, TextChunk
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.system.http_server import TURN_STALE_S, HttpServer

VOICE = "jane"
RATE = 22050
TIMEOUT = 10


def _pcm(seconds: float = 0.02, freq: float = 220.0) -> bytes:
    n = int(RATE * seconds)
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / RATE))) for i in range(n))


PCM_1 = _pcm()
PCM_2 = _pcm(0.03, 440.0)


class _FakeTTS(Plugin):
    """Emite audio de entrada y audio de salida, con sentinel en el medio."""

    def __init__(self) -> None:
        super().__init__("fake_tts", capabilities=("audio_output",))

    async def on_text_chunk(self, data: TextChunk) -> None:
        await self.manager.emit(
            "audio_chunk",
            AudioData(samples=b"\x00\x01" * 16, sample_rate=16000, format="pcm_s16le"),
            source="fake_tts",
        )
        for pcm, final in ((PCM_1, False), (b"", True), (PCM_2, True)):
            await self.manager.emit(
                "audio_output",
                AudioOutput(
                    samples=pcm,
                    sample_rate=RATE,
                    channels=1,
                    format="pcm_s16le",
                    voice_id=VOICE,
                    final=final,
                ),
                source="fake_tts",
            )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _collect(ws: object, want: int) -> list[dict]:
    frames: list[dict] = []
    while len(frames) < want:
        frames.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)))
    return frames


@pytest.mark.asyncio
async def test_events_stream_emite_audio_base64_con_turn_start_y_turn_end():
    # Given: un server con un plugin que emite audio de entrada y dos chunks de audio.
    manager = PluginManager()
    plugin = _FakeTTS()
    manager.register_plugin(plugin)
    await manager.enable_plugin(plugin)
    port = _free_port()
    server = HttpServer(manager, host="127.0.0.1", port=port)
    await server.start()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/events/stream") as ws:
            # When: se dispara un turno de texto.
            await manager.emit(
                "text_chunk", TextChunk(text="hola", sequence=0, voice_id=VOICE), source="test"
            )
            received = await _collect(ws, 9)
    finally:
        await server.stop()

    # Then: turn_start va antes del primer frame de audio del turno.
    assert [f["name"] for f in received] == [
        "text_chunk",
        "audio_chunk",
        "turn_start",
        "audio_output",
        "audio_output",
        "turn_end",
        "turn_start",
        "audio_output",
        "turn_end",
    ]
    assert all("samples" not in f["data"] for f in received)

    turn_start = received[2]["data"]
    assert turn_start["voice_id"] == VOICE
    assert turn_start["trigger"] == "text_chunk"
    assert turn_start["encoding"] == "base64"
    assert turn_start["format"] == "pcm_s16le"
    assert turn_start["sample_rate"] == RATE
    assert turn_start["channels"] == 1
    assert turn_start["t_in_audio"] is not None
    assert turn_start["t_first_audio_byte"] >= turn_start["t_in_audio"]

    # Then: el PCM del bus llega íntegro, en base64.
    first_audio = received[3]["data"]
    assert first_audio["encoding"] == "base64"
    assert base64.b64decode(first_audio["samples_b64"]) == PCM_1
    assert first_audio["final"] is False
    assert base64.b64decode(received[7]["data"]["samples_b64"]) == PCM_2
    assert received[7]["data"]["final"] is True

    # Then: el sentinel (samples vacíos + final) cierra turno sin abrir uno.
    assert received[4]["data"]["samples_b64"] == ""
    assert received[4]["data"]["final"] is True

    # Then: cada turn_end cuadra con los frames de su turno.
    for start_idx, end_idx, frames_expected, bytes_expected in ((2, 5, 2, len(PCM_1)), (6, 8, 1, len(PCM_2))):
        end = received[end_idx]["data"]
        assert end["turn_id"] == received[start_idx]["data"]["turn_id"]
        assert end["voice_id"] == VOICE
        assert end["reason"] == "final"
        assert end["frames"] == frames_expected
        assert end["bytes"] == bytes_expected
        assert end["t_turn_end"] >= received[start_idx]["data"]["t_first_audio_byte"]


@pytest.mark.asyncio
async def test_events_stream_turn_end_por_stale_tras_silencio():
    # Given: un turno abierto hace más de TURN_STALE_S que no recibe audio.
    manager = PluginManager()
    server = HttpServer(manager, host="127.0.0.1", port=_free_port())
    server._open_turns[VOICE] = {
        "turn_id": "t-open",
        "frames": 3,
        "bytes": 10,
        "last_frame_ts": time.time() - (TURN_STALE_S + 1),
        "trace_id": None,
    }
    envelope = EventEnvelope(
        name="audio_output",
        data=AudioOutput(samples=PCM_1, sample_rate=RATE, channels=1, format="pcm_s16le", voice_id=VOICE),
        source="test",
    )

    # When: llega el siguiente audio_output de esa voz.
    frames = server._frames_for(envelope)

    # Then: cierra el viejo por stale y abre el nuevo.
    assert [f["name"] for f in frames] == ["turn_end", "turn_start", "audio_output"]
    assert frames[0]["data"]["reason"] == "stale"
    assert frames[0]["data"]["turn_id"] == "t-open"
    assert frames[1]["data"]["turn_id"] != "t-open"
    assert server._open_turns[VOICE]["turn_id"] == frames[1]["data"]["turn_id"]


@pytest.mark.asyncio
async def test_events_stream_turn_start_sin_trigger_reciente():
    # Given: un audio_output sin trigger previo (t_in_audio no se puede atribuir).
    manager = PluginManager()
    server = HttpServer(manager, host="127.0.0.1", port=_free_port())
    envelope = EventEnvelope(
        name="audio_output",
        data=AudioOutput(samples=PCM_1, sample_rate=RATE, channels=1, format="pcm_s16le", voice_id=VOICE),
        source="test",
    )

    frames = server._frames_for(envelope)

    assert [f["name"] for f in frames] == ["turn_start", "audio_output"]
    assert frames[0]["data"]["t_in_audio"] is None
    assert frames[0]["data"]["trigger"] is None
