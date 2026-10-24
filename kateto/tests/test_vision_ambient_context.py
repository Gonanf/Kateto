from __future__ import annotations

import io
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from loguru import logger

from kateto.core.event import (
    GenerateData,
    ScheduleRequestData,
    ScheduleResultData,
    ScheduleType,
    VisionDescribeRequestData,
    VisionDescribeResultData,
)
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.executor import static_vision_plugin as svp
from kateto.plugins.executor.static_vision_plugin import (
    StaticVisionPlugin,
    _ambient_line,
)
from kateto.tests.conversation_support import StreamingFixtureProvider, write_references
from kateto.voices.base import VISION_AMBIENT_MAX_BLOCKS, VoiceAgent
from kateto.voices.factory import _PROFILES


class _Voice(Plugin):
    """Minimal voice stand-in for target discovery."""

    def __init__(self, name: str = "jane") -> None:
        super().__init__(name=name, capabilities=("voice",))


class _ScheduleRequestRecorder(Plugin):
    """Records every schedule_request on the bus."""

    def __init__(self) -> None:
        super().__init__(name="schedule_recorder")
        self.seen: list[ScheduleRequestData] = []

    async def on_schedule_request(self, data: ScheduleRequestData) -> None:
        self.seen.append(data)


def _noise_payload(seed: int = 42) -> bytes:
    from PIL import Image

    rng = random.Random(seed)
    img = Image.new("RGB", (48, 32))
    px = img.load()
    assert px is not None
    for y in range(32):
        for x in range(48):
            px[x, y] = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# 1. _ambient_line recorta en palabra y agrega "…"; colapsa \n
def test_ambient_line_word_boundary_and_collapse_newlines():
    text = "First line here\nSecond line has many words and exceeds limit"
    result = _ambient_line(text, 25)
    assert "\n" not in result
    assert result.endswith("…")
    assert len(result) <= 25
    assert result == "First line here Second…"


# 2. _ambient_line no toca un texto corto
def test_ambient_line_short_text_unchanged():
    text = "Short visual summary"
    result = _ambient_line(text, 280)
    assert result == "Short visual summary"


# 3. __init__: ambient_delivery inválido → "context" (con warning logueado, patrón logger.add)
def test_init_invalid_ambient_delivery_falls_back_and_warns():
    logs: list[str] = []
    handler_id = logger.add(logs.append, format="{message}")
    try:
        plugin = StaticVisionPlugin(ambient_delivery="invalid_mode")
        assert plugin.ambient_delivery == "context"
        assert any("unknown ambient_delivery 'invalid_mode'; using 'context'" in m for m in logs)
    finally:
        logger.remove(handler_id)


# 4. __init__: ambient_max_chars = 10 → 40
def test_init_ambient_max_chars_clamped_to_40():
    plugin = StaticVisionPlugin(ambient_max_chars=10)
    assert plugin.ambient_max_chars == 40


# 5. _ambient_targets(): ambient_all_voices=True + ambient_exclude=["jane"] con manager de prueba
# devuelve todas menos jane.
@pytest.mark.asyncio
async def test_ambient_targets_all_voices_minus_excluded():
    manager = PluginManager()
    await manager.enable_plugin(_Voice("jane"))
    await manager.enable_plugin(_Voice("doktor"))
    await manager.enable_plugin(_Voice("conquest"))
    plugin = StaticVisionPlugin(
        ambient_all_voices=True,
        ambient_exclude=["jane"],
    )
    await manager.enable_plugin(plugin)
    targets = plugin._ambient_targets()
    assert targets == ("conquest", "doktor")
    await manager.close()


# 6. _schedule_periodic con ambient_delivery="context", ambient_all_voices=True emite UN
# schedule_request con job_id == "vision-describe-ambient" y data["requester"] == "scheduler:ambient"
@pytest.mark.asyncio
async def test_schedule_periodic_emits_single_shared_ambient_job():
    manager = PluginManager()
    requests = _ScheduleRequestRecorder()
    await manager.enable_plugin(requests)
    await manager.enable_plugin(_Voice("jane"))
    await manager.enable_plugin(_Voice("doktor"))
    plugin = StaticVisionPlugin(
        ambient_delivery="context",
        ambient_all_voices=True,
        describe_interval="45s",
    )
    plugin.capture_frame = lambda target_pid=None: b""
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()

    schedule_reqs = [r for r in requests.seen if r.job_id == "vision-describe-ambient"]
    assert len(schedule_reqs) == 1
    req = schedule_reqs[0]
    assert req.job_id == "vision-describe-ambient"
    assert req.data.get("requester") == "scheduler:ambient"
    assert req.data.get("source") == "screen"
    assert req.expression == "45s"
    assert req.target_voice is None
    assert req.jitter_seconds == 5.0
    await manager.close()


# 7. Camino ambient: llamando al helper de emisión / al bloque de _run_describe con datos ya armados
# (monkeypatch del describe para devolver fused fijo), se emiten N vision_describe_result con
# ambient=True (uno por target) y CERO generate.
@pytest.mark.asyncio
async def test_ambient_describe_emits_ambient_results_and_zero_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_openai_client(endpoint, api_key, retries, timeout):
        async def create(**kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="a cat on a desk"))]
            )

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(svp, "_openai_client", fake_openai_client)

    manager = PluginManager()
    await manager.enable_plugin(_Voice("jane"))
    await manager.enable_plugin(_Voice("doktor"))

    plugin = StaticVisionPlugin(
        ambient_delivery="context",
        ambient_all_voices=True,
    )
    plugin.vision_endpoint = "http://primary:8080/v1"
    plugin.vision_model = "vlm"
    plugin.capture_frame = lambda target_pid=None: b""
    plugin._append_frame("screen", _noise_payload(101), 100.0)
    plugin._append_frame("screen", _noise_payload(102), 101.0)
    await manager.enable_plugin(plugin)

    envelopes: list[Any] = []
    manager.add_event_observer(envelopes.append)

    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="scheduler:ambient", source="screen")
    )
    await manager.wait_for_idle()

    ambient_results = [
        e for e in envelopes if e.name == "vision_describe_result" and getattr(e.data, "ambient", False)
    ]
    assert len(ambient_results) == 2
    assert set(e.target for e in ambient_results) == {"doktor", "jane"}
    for res in ambient_results:
        assert "a cat on a desk" in res.data.text
        assert res.data.ambient is True

    generates = [e for e in envelopes if e.name == "generate"]
    assert len(generates) == 0

    manager.remove_event_observer(envelopes.append)
    await manager.close()


# 8. Voz: emitir VisionDescribeResultData(ambient=True) en un VoiceAgent (patrón de
# kateto/tests/test_voice_vision_memory.py, StreamingFixtureProvider + write_references)
# deja en jane._event_messages un mensaje que empieza con [contexto visual] y no contiene
# el marco [Tu propia mirada / [Your own look.
@pytest.mark.asyncio
async def test_voice_remembers_ambient_vision_result(tmp_path: Path) -> None:
    write_references(tmp_path)
    manager = PluginManager()

    jane = VoiceAgent(
        profile=_PROFILES["jane"],
        config_dir=tmp_path,
        provider=StreamingFixtureProvider(),
    )
    await manager.enable_plugin(jane)

    await manager.emit(
        "vision_describe_result",
        VisionDescribeResultData(
            text="terminal with code on screen",
            frame_count=2,
            kept_count=2,
            dropped=0,
            window_start=10.0,
            window_end=15.0,
            source="screen",
            ambient=True,
        ),
        source="static_vision",
        target="jane",
    )
    await manager.wait_for_idle(timeout=5)

    assert len(jane._event_messages) == 1
    content = jane._event_messages[0].content
    assert content.startswith("[contexto visual]")
    assert "terminal with code on screen" in content
    assert "[Tu propia mirada" not in content
    assert "[Your own look" not in content

    await manager.close()


# 9. Pruning: 4 bloques ambient seguidos → quedan 2 en _event_messages
@pytest.mark.asyncio
async def test_ambient_pruning_keeps_maximum_two_blocks(tmp_path: Path) -> None:
    write_references(tmp_path)
    manager = PluginManager()

    jane = VoiceAgent(
        profile=_PROFILES["jane"],
        config_dir=tmp_path,
        provider=StreamingFixtureProvider(),
    )
    await manager.enable_plugin(jane)

    for i in range(4):
        await manager.emit(
            "vision_describe_result",
            VisionDescribeResultData(
                text=f"screen observation #{i}",
                frame_count=2,
                kept_count=2,
                dropped=0,
                window_start=float(i * 10),
                window_end=float(i * 10 + 5),
                source="screen",
                ambient=True,
            ),
            source="static_vision",
            target="jane",
        )
        await manager.wait_for_idle(timeout=5)

    ambient_msgs = [
        m.content for m in jane._event_messages if m.content.startswith("[contexto visual]")
    ]
    assert len(ambient_msgs) == VISION_AMBIENT_MAX_BLOCKS
    assert "screen observation #2" in ambient_msgs[0]
    assert "screen observation #3" in ambient_msgs[1]

    await manager.close()
