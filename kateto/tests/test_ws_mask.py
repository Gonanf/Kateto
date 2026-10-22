import asyncio
import base64
import json
import socket

import pytest
from websockets.asyncio.client import connect

from kateto.core.event import AudioData, AudioOutput, VisionFrameData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.system.http_server import HttpServer
from kateto.plugins.visual_overlay.visual_overlay_plugin import VisualOverlayPlugin


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _uri(server: HttpServer) -> str:
    return f"ws://127.0.0.1:{server._port}/ws/mask"


async def _recv_json(ws, timeout: float = 3) -> dict:
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("type") == "heartbeat":
            continue
        return msg


def _capture_plugin() -> tuple[Plugin, dict]:
    captured: dict = {}

    class CapturePlugin(Plugin):
        async def on_audio_chunk(self, data: AudioData) -> None:
            captured["samples"] = data.samples
            captured["sample_rate"] = data.sample_rate

        async def on_vision_frame(self, data: VisionFrameData) -> None:
            captured["frame"] = data.frame
            captured["source"] = data.source

        async def on_interrupt(self, data) -> None:
            captured["reason"] = data.reason

    return CapturePlugin("mask_capture"), captured


async def _wait_for(captured: dict, key: str, timeout: float = 3) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if key in captured:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"event {key} not received within {timeout}s")


@pytest.mark.asyncio
async def test_ws_mask_ping_pong():
    manager = PluginManager()
    server = HttpServer(manager, host="127.0.0.1", port=_free_port())
    await server.start()
    try:
        async with connect(_uri(server)) as ws:
            await ws.send(json.dumps({"type": "ping"}))
            msg = await _recv_json(ws)
            assert msg["type"] == "pong"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ws_mask_audio_input_emits_audio_chunk():
    manager = PluginManager()
    manager.register_event("audio_chunk", AudioData)
    plugin, captured = _capture_plugin()
    await manager.enable_plugin(plugin)

    server = HttpServer(manager, host="127.0.0.1", port=_free_port())
    await server.start()
    try:
        async with connect(_uri(server)) as ws:
            pcm = b"\x01\x00" * 320
            await ws.send(json.dumps({
                "type": "mask_audio_input",
                "audio": base64.b64encode(pcm).decode(),
            }))
            await _wait_for(captured, "samples")
            assert captured["samples"] == pcm
            assert captured["sample_rate"] == 16000
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ws_mask_binary_frame_emits_audio_chunk():
    manager = PluginManager()
    manager.register_event("audio_chunk", AudioData)
    plugin, captured = _capture_plugin()
    await manager.enable_plugin(plugin)

    server = HttpServer(manager, host="127.0.0.1", port=_free_port())
    await server.start()
    try:
        async with connect(_uri(server)) as ws:
            pcm = b"\x02\x00" * 640
            await ws.send(pcm)
            await _wait_for(captured, "samples")
            assert captured["samples"] == pcm
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ws_mask_camera_frame_emits_vision_frame():
    manager = PluginManager()
    manager.register_event("vision_frame", VisionFrameData)
    plugin, captured = _capture_plugin()
    await manager.enable_plugin(plugin)

    server = HttpServer(manager, host="127.0.0.1", port=_free_port())
    await server.start()
    try:
        async with connect(_uri(server)) as ws:
            frame = b"\xff\xd8\xff" + b"\x00" * 100
            await ws.send(json.dumps({
                "type": "mask_camera_frame",
                "frame": base64.b64encode(frame).decode(),
            }))
            await _wait_for(captured, "frame")
            assert captured["frame"] == frame
            assert captured["source"] == "mask"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ws_mask_interrupt_emits_interrupt():
    manager = PluginManager()
    plugin, captured = _capture_plugin()
    await manager.enable_plugin(plugin)

    server = HttpServer(manager, host="127.0.0.1", port=_free_port())
    await server.start()
    try:
        async with connect(_uri(server)) as ws:
            await ws.send(json.dumps({"type": "interrupt", "reason": "user_barge_in"}))
            await _wait_for(captured, "reason")
            assert captured["reason"] == "user_barge_in"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ws_mask_survives_garbage():
    manager = PluginManager()
    server = HttpServer(manager, host="127.0.0.1", port=_free_port())
    await server.start()
    try:
        async with connect(_uri(server)) as ws:
            await ws.send("no-json")
            assert (await _recv_json(ws))["type"] == "error"

            await ws.send(json.dumps({"type": "mask_audio_input", "audio": "!!!no-base64"}))
            assert (await _recv_json(ws))["type"] == "error"

            await ws.send(json.dumps({"type": "ping"}))
            assert (await _recv_json(ws))["type"] == "pong"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ws_mask_receives_viseme_and_audio():
    manager = PluginManager()
    await manager.enable_plugin(VisualOverlayPlugin())

    server = HttpServer(manager, host="127.0.0.1", port=_free_port())
    await server.start()
    try:
        async with connect(_uri(server)) as ws:
            await manager.emit("audio_output", AudioOutput(
                samples=b"\x01\x00" * 200,
                sample_rate=22050,
                channels=1,
                format="pcm_s16le",
                voice_id="jane",
            ))
            msg = await _recv_json(ws)
            assert msg["event"] == "audio_output"
            assert msg["type"] == "viseme"
            assert "jawRotation" in msg
            assert msg["audio"] is not None
    finally:
        await server.stop()
