import math
from pathlib import Path
import struct
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from kateto.core.event import AudioOutput, TextChunk
from kateto.core.manager import PluginManager
from kateto.plugins.system.http_server import HttpServer
from kateto.core.rms import (
    RMSProcessor,
    apply_ema,
    calculate_raw_rms,
    map_rms_to_jaw_transform,
    normalize_rms,
)
from kateto.plugins.visual_overlay.visual_overlay_plugin import VisualOverlayPlugin


def test_calculate_raw_rms():
    # Given: empty or invalid bytes
    assert calculate_raw_rms(b"") == 0.0
    assert calculate_raw_rms(b"\x00") == 0.0

    # Given: 100 samples with constant amplitude 32767
    max_samples = struct.pack("<100h", *[32767] * 100)
    rms_max = calculate_raw_rms(max_samples)
    assert math.isclose(rms_max, 32767 / 32768.0, rel_tol=1e-3)

    # Given: silence (0 amplitude)
    silence = struct.pack("<100h", *[0] * 100)
    assert calculate_raw_rms(silence) == 0.0


def test_normalize_rms():
    # Given: below noise threshold (0.01)
    assert normalize_rms(0.005, noise_threshold=0.01, peak_threshold=0.8) == 0.0
    assert normalize_rms(0.01, noise_threshold=0.01, peak_threshold=0.8) == 0.0

    # Given: at peak threshold (0.8)
    assert normalize_rms(0.8, noise_threshold=0.01, peak_threshold=0.8) == 1.0
    assert normalize_rms(0.9, noise_threshold=0.01, peak_threshold=0.8) == 1.0

    # Given: midpoint
    mid_raw = 0.01 + 0.5 * (0.8 - 0.01)
    assert math.isclose(normalize_rms(mid_raw, noise_threshold=0.01, peak_threshold=0.8), 0.5)


def test_apply_ema():
    # Given: initial state 0.0 and step input 1.0 with alpha=0.3
    step1 = apply_ema(1.0, 0.0, alpha=0.3)
    assert math.isclose(step1, 0.3)

    step2 = apply_ema(1.0, step1, alpha=0.3)
    assert math.isclose(step2, 0.3 * 1.0 + 0.7 * 0.3)

    # Given: very small value decays to 0.0
    assert apply_ema(0.0, 1e-5, alpha=0.3) == 0.0


def test_map_rms_to_jaw_transform_pure_mapping():
    # Given: noise floor = 0.05
    # When: rms is below noise floor
    assert map_rms_to_jaw_transform(0.0) == (0.0, 0.0)
    assert map_rms_to_jaw_transform(0.04) == (0.0, 0.0)
    assert map_rms_to_jaw_transform(0.05) == (0.0, 0.0)

    # When: rms is at intermediate level (0.525 gives factor = (0.525 - 0.05) / 0.95 = 0.5)
    offset_y, rotation = map_rms_to_jaw_transform(0.525)
    assert math.isclose(offset_y, 8.0, abs_tol=1e-2)
    assert math.isclose(rotation, 2.25, abs_tol=1e-2)

    # When: rms is at maximum (1.0)
    assert map_rms_to_jaw_transform(1.0) == (16.0, 4.5)

    # When: rms exceeds 1.0
    assert map_rms_to_jaw_transform(1.5) == (16.0, 4.5)


def test_rms_processor_stateful_and_windowed():
    processor = RMSProcessor(alpha=0.3, noise_threshold=0.01, peak_threshold=0.8, sample_rate=16000)

    # When: processing silence
    silence = struct.pack("<320h", *[0] * 320)
    assert processor.process(silence) == 0.0

    # When: processing audio with signal
    samples = struct.pack("<640h", *[15000] * 640)
    rms = processor.process(samples)
    assert 0.0 < rms <= 1.0

    # When: reset
    processor.reset()
    assert processor.current_ema == 0.0


@pytest.mark.asyncio
async def test_visual_overlay_compute_rms_and_broadcast():
    plugin = VisualOverlayPlugin()

    # Generate 100 16-bit PCM samples
    samples = struct.pack("<100h", *[5000] * 100)
    rms = plugin.compute_rms(samples)
    assert 0.0 < rms < 1.0

    # Mock websocket connection
    mock_ws = MagicMock()
    mock_ws.send_json = AsyncMock()

    await plugin.register_websocket(mock_ws)

    # Test subtitle chunk event
    chunk = TextChunk(text="Hello overlay", sequence=1, voice_id="jane")
    await plugin.on_text_chunk(chunk)

    mock_ws.send_json.assert_called_once()
    sub_payload = mock_ws.send_json.call_args[0][0]
    assert sub_payload["type"] == "subtitle"
    assert sub_payload["event"] == "text_chunk"
    assert sub_payload["text"] == "Hello overlay"
    assert sub_payload["voice_id"] == "jane"

    # Test audio output event
    audio = AudioOutput(samples=samples, sample_rate=16000, channels=1, voice_id="jane")
    await plugin.on_audio_output(audio)

    assert mock_ws.send_json.call_count == 2
    vis_payload = mock_ws.send_json.call_args_list[1][0][0]
    assert vis_payload["type"] == "viseme"
    assert vis_payload["event"] == "audio_output"
    assert vis_payload["voice_id"] == "jane"
    assert vis_payload["rms"] > 0.0
    assert "jawOffsetY" in vis_payload
    assert "jawRotation" in vis_payload
    assert vis_payload["data"]["rms"] == vis_payload["rms"]


@pytest.mark.asyncio
async def test_audio_output_explicit_rms_passthrough():
    plugin = VisualOverlayPlugin()
    mock_ws = MagicMock()
    mock_ws.send_json = AsyncMock()
    await plugin.register_websocket(mock_ws)

    # When: AudioOutput has explicit rms
    audio = AudioOutput(samples=b"", sample_rate=16000, channels=1, voice_id="jane", rms=0.525)
    await plugin.on_audio_output(audio)

    mock_ws.send_json.assert_called_once()
    payload = mock_ws.send_json.call_args[0][0]
    assert payload["rms"] == 0.525
    assert math.isclose(payload["jawOffsetY"], 8.0, abs_tol=1e-2)
    assert math.isclose(payload["jawRotation"], 2.25, abs_tol=1e-2)


@pytest.mark.asyncio
async def test_http_server_serves_avatar_assets_and_overlay(tmp_path: Path):
    voices_dir = tmp_path / "voices" / "jane"
    voices_dir.mkdir(parents=True)
    (voices_dir / "top.png").write_bytes(b"dummy_top_png")
    (voices_dir / "mouth.png").write_bytes(b"dummy_mouth_png")
    (voices_dir / "avatar_head.png").write_bytes(b"dummy_head_png")
    (voices_dir / "avatar_jaw.png").write_bytes(b"dummy_jaw_png")
    (voices_dir / "forbidden.txt").write_bytes(b"secret")

    manager = PluginManager()
    server = HttpServer(manager, host="127.0.0.1", port=8996, config_dir=tmp_path)
    await server.start()

    try:
        async with httpx.AsyncClient() as client:
            # 1. Overlay HTML endpoint
            resp_overlay = await client.get("http://127.0.0.1:8996/overlay")
            assert resp_overlay.status_code == 200
            assert "vtuber-overlay" in resp_overlay.text
            assert "avatar_head.png" in resp_overlay.text
            assert "avatar_jaw.png" in resp_overlay.text

            # 1b. Component and Courtroom routes
            resp_comp = await client.get("http://127.0.0.1:8996/components/kateto-avatar.js")
            assert resp_comp.status_code == 200
            assert "KatetoAvatar" in resp_comp.text
            assert "KatetoSubtitles" in resp_comp.text

            resp_court = await client.get("http://127.0.0.1:8996/courtroom")
            assert resp_court.status_code == 200
            assert "kateto-avatar" in resp_court.text
            assert "kateto-paper-transcript" in resp_court.text

            assert "caption" in resp_overlay.text

            # 2. Valid avatar assets
            for filename, expected_bytes in [
                ("top.png", b"dummy_top_png"),
                ("mouth.png", b"dummy_mouth_png"),
                ("avatar_head.png", b"dummy_head_png"),
                ("avatar_jaw.png", b"dummy_jaw_png"),
            ]:
                resp = await client.get(f"http://127.0.0.1:8996/voices/jane/{filename}")
                assert resp.status_code == 200
                assert resp.content == expected_bytes

            # 3. Disallowed file
            resp_disallowed = await client.get("http://127.0.0.1:8996/voices/jane/forbidden.txt")
            assert resp_disallowed.status_code == 404

            # 4. Non-existent avatar
            resp_missing = await client.get("http://127.0.0.1:8996/voices/ghost/avatar_head.png")
            assert resp_missing.status_code == 404
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_visual_overlay_audio_streaming_and_multi_agent_config():
    import base64

    # Given: settings with custom layout, voices, and audio streaming enabled
    settings = MagicMock()
    settings.layout = "multi"
    settings.voices = ["jane", "doktor", "whisperer"]
    settings.audio = True
    settings.get.side_effect = lambda k, default=None: getattr(settings, k, default)

    plugin = VisualOverlayPlugin(settings=settings)
    assert plugin._layout == "multi"
    assert plugin._voices == ["jane", "doktor", "whisperer"]
    assert plugin._stream_audio is True

    # When: audio output with PCM samples is emitted
    mock_ws = MagicMock()
    mock_ws.send_json = AsyncMock()
    await plugin.register_websocket(mock_ws)

    sample_bytes = struct.pack("<50h", *[4000] * 50)
    audio = AudioOutput(samples=sample_bytes, sample_rate=24000, channels=1, voice_id="doktor", format="pcm_s16le")
    await plugin.on_audio_output(audio)

    # Then: broadcast payload includes base64 audio and audio format metadata
    assert mock_ws.send_json.call_count == 1
    payload = mock_ws.send_json.call_args[0][0]
    assert payload["event"] == "audio_output"
    assert payload["voice_id"] == "doktor"
    assert payload["sample_rate"] == 24000
    assert payload["format"] == "pcm_s16le"
    assert payload["audio"] == base64.b64encode(sample_bytes).decode("ascii")
    assert payload["data"]["audio"] == payload["audio"]


@pytest.mark.asyncio
async def test_visual_overlay_programmatic_layout_event():
    from kateto.core.event import OverlayLayout

    plugin = VisualOverlayPlugin()
    mock_ws = MagicMock()
    mock_ws.send_json = AsyncMock()
    await plugin.register_websocket(mock_ws)

    # When: emitting an OverlayLayout event for a game (e.g. chess / versus)
    event = OverlayLayout(
        layout="sides",
        positions={"jane": "left", "doktor": "right"},
        voices=["jane", "doktor"],
    )
    await plugin.on_overlay_layout(event)

    # Then: layout update is broadcast to connected websockets
    assert mock_ws.send_json.call_count == 1
    payload = mock_ws.send_json.call_args[0][0]
    assert payload["event"] == "overlay_layout"
    assert payload["layout"] == "sides"
    assert payload["positions"]["jane"] == "left"
    assert payload["positions"]["doktor"] == "right"
    assert payload["voices"] == ["jane", "doktor"]


