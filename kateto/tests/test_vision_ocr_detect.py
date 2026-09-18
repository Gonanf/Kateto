"""Fix-114: la voz consume el OCR y la detección de objetos del sidecar.

El plugin de visión pide `ocr_images` (y opcionalmente `detect_objects`) con los
mismos frames del sidecar y compone el material como `VISUAL:` / `OCR:` /
`OBJECTS:`. Reglas duras: un error de OCR nunca se narra como texto de pantalla
(bug 106), una tool ausente (binario viejo) degrada en silencio, y
`vision_ocr`/`vision_detect` apagados no llaman a esas tools. El marco de la voz
menciona `OCR:` y mantiene la prohibición de pedir instrucciones (fix-111).
"""

from __future__ import annotations

import asyncio
import io
import random
from types import SimpleNamespace

import pytest

from loguru import logger

from kateto.core.event import InterruptData, VisionDescribeRequestData, VisionDescribeResultData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.executor import static_vision_plugin as svp
from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin
from kateto.voices.base import frame_look_at_turn

PRIMARY = "http://primary:8080/v1"
PRIMARY_MODEL = "test-vision-model"
CAPTION = "una terminal con código en pantalla"
OCR_TEXT = "REUNION MARTES 14:30\nTeorema de existencia"
DETECT_TEXT = "DETECT @ image 0: square 0.90 [86,238,430,842]"


def _noise_frame(seed: int) -> bytes:
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


class _FakeSidecar:
    """Sidecar fake: expone el path result-preserving que usa el plugin.

    ``ocr=None``/``detect=None`` significan "sin tool en la sesión" (binario
    viejo). ``ocr_is_error``/``detect_via_vlm`` modelan los flags que el plugin
    debe respetar.
    """

    def __init__(
        self,
        *,
        ocr: str | None = None,
        ocr_is_error: bool = False,
        detect: str | None = None,
        detect_via_vlm: bool = False,
    ) -> None:
        self.ocr = ocr
        self.ocr_is_error = ocr_is_error
        self.detect = detect
        self.detect_via_vlm = detect_via_vlm
        self.calls: list[str] = []

    async def try_call_tool_result(self, servers, tool, arguments, timeout=30.0):
        # Sin has_tool: un tool ausente (binario viejo) ni siquiera llega al
        # cliente real — el manager retorna None sin invocar nada.
        if tool == "ocr_images" and self.ocr is None:
            return None
        if tool == "detect_objects" and self.detect is None:
            return None
        self.calls.append(tool)
        if tool == "ocr_images":
            return SimpleNamespace(
                text=self.ocr, is_error=self.ocr_is_error, server="video_rag", tool="ocr_images"
            )
        if tool == "detect_objects":
            text = f"via=vlm\n{self.detect}" if self.detect_via_vlm else self.detect
            return SimpleNamespace(
                text=text, is_error=False, server="video_rag", tool="detect_objects"
            )
        return None  # no describe_images aquí: fuerza el path de recap


def _install_fake_sidecar(monkeypatch: pytest.MonkeyPatch, mcp: _FakeSidecar) -> None:
    monkeypatch.setattr(
        svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=mcp)
    )


def _install_fake_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    async def create(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=CAPTION))]
        )

    monkeypatch.setattr(
        svp,
        "_openai_client",
        lambda *a, **k: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )


class _ResultRecorder(Plugin):
    def __init__(self) -> None:
        super().__init__(name="result_recorder")
        self.seen: list[VisionDescribeResultData] = []

    async def on_vision_describe_result(self, data: VisionDescribeResultData) -> None:
        self.seen.append(data)


async def _make_plugin(manager: PluginManager, **kwargs) -> StaticVisionPlugin:
    plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    plugin.vision_endpoint = kwargs.pop("vision_endpoint", PRIMARY)
    plugin.vision_model = kwargs.pop("vision_model", PRIMARY_MODEL)
    for key, value in kwargs.items():
        setattr(plugin, key, value)
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()
    plugin._windows.clear()
    plugin._dropped.clear()
    return plugin


@pytest.mark.asyncio
async def test_ocr_text_included_under_ocr_label(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: sidecar con ocr_images y caption desde el VLM primario
    sidecar = _FakeSidecar(ocr=OCR_TEXT)
    _install_fake_sidecar(monkeypatch, sidecar)
    _install_fake_primary(monkeypatch)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    try:
        plugin = await _make_plugin(manager)
        plugin._append_frame("screen", _noise_frame(1), 10.0)

        # When: describe con un frame en ventana
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="jane", source="screen")
        )
        await manager.wait_for_idle()

        # Then: el material lleva VISUAL + OCR; detect está apagado
        result = results.seen[0]
        assert "ocr_images" in sidecar.calls
        assert f"VISUAL: {CAPTION}" in result.text
        assert f"OCR: {OCR_TEXT}" in result.text
        assert "OBJECTS:" not in result.text
        assert "detect_objects" not in sidecar.calls
    finally:
        await asyncio.wait_for(manager.disable_plugin(results.name), timeout=5.0)
        await manager.close()


@pytest.mark.asyncio
async def test_ocr_is_error_not_included_falls_to_recap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: ocr_images responde con is_error y sin VLM primario ni describe ok
    sidecar = _FakeSidecar(ocr="image 0 exceeds ~1.5MB data-URL cap", ocr_is_error=True)
    _install_fake_sidecar(monkeypatch, sidecar)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    try:
        plugin = await _make_plugin(manager, vision_endpoint=None, vision_model=None)
        plugin._append_frame("screen", _noise_frame(2), 10.0)

        # When: describing con el sidecar que contesta un OCR error
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="jane", source="screen")
        )
        await manager.wait_for_idle()

        # Then: el error no se narra como texto de pantalla y cae al recap
        result = results.seen[0]
        assert result.via == "recap" and "recap" in result.text
        assert "OCR:" not in result.text
        assert "data-URL cap" not in result.text
    finally:
        await asyncio.wait_for(manager.disable_plugin(results.name), timeout=5.0)
        await manager.close()


@pytest.mark.asyncio
async def test_ocr_tool_missing_degrades_to_old_sidecar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: sidecar viejo sin ocr_images (solo describe via VLM primario)
    sidecar = _FakeSidecar(ocr=None)
    _install_fake_sidecar(monkeypatch, sidecar)
    _install_fake_primary(monkeypatch)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    try:
        plugin = await _make_plugin(manager)
        plugin._append_frame("screen", _noise_frame(3), 10.0)

        # When: describing con el sidecar viejo
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="jane", source="screen")
        )
        await manager.wait_for_idle()

        # Then: todo igual que antes — caption intacto, sin OCR
        result = results.seen[0]
        assert "ocr_images" not in sidecar.calls
        assert "OCR:" not in result.text
        assert f"VISUAL: {CAPTION}" in result.text
    finally:
        await asyncio.wait_for(manager.disable_plugin(results.name), timeout=5.0)
        await manager.close()


@pytest.mark.asyncio
async def test_vision_ocr_false_skips_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: vision_ocr=false
    sidecar = _FakeSidecar(ocr=OCR_TEXT)
    _install_fake_sidecar(monkeypatch, sidecar)
    _install_fake_primary(monkeypatch)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    try:
        plugin = await _make_plugin(manager, vision_ocr=False)
        plugin._append_frame("screen", _noise_frame(4), 10.0)

        # When: describing con OCR apagado
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="jane", source="screen")
        )
        await manager.wait_for_idle()

        # Then: no se llama ocr_images ni una vez, no hay sección OCR
        result = results.seen[0]
        assert "ocr_images" not in sidecar.calls
        assert "OCR:" not in result.text
    finally:
        await asyncio.wait_for(manager.disable_plugin(results.name), timeout=5.0)
        await manager.close()
@pytest.mark.asyncio
async def test_detect_true_includes_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: vision_detect=true
    sidecar = _FakeSidecar(ocr=OCR_TEXT, detect=DETECT_TEXT)
    _install_fake_sidecar(monkeypatch, sidecar)
    _install_fake_primary(monkeypatch)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    try:
        plugin = await _make_plugin(manager, vision_detect=True)
        plugin._append_frame("screen", _noise_frame(5), 10.0)

        # When: describing con detección prendida
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="jane", source="screen")
        )
        await manager.wait_for_idle()

        # Then: el material incluye OBJECTS (sin flag best-effort, via=sidecar)
        result = results.seen[0]
        assert "detect_objects" in sidecar.calls
        assert f"OBJECTS: {DETECT_TEXT}" in result.text
        assert "best-effort" not in result.text
    finally:
        await asyncio.wait_for(manager.disable_plugin(results.name), timeout=5.0)
        await manager.close()


@pytest.mark.asyncio
async def test_detect_via_vlm_is_flagged_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: vision_detect=true y el backend contesta via=vlm
    sidecar = _FakeSidecar(ocr=OCR_TEXT, detect=DETECT_TEXT, detect_via_vlm=True)
    _install_fake_sidecar(monkeypatch, sidecar)
    _install_fake_primary(monkeypatch)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    try:
        plugin = await _make_plugin(manager, vision_detect=True)
        plugin._append_frame("screen", _noise_frame(6), 10.0)

        # When: describing con detección vía VLM (estimación)
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="jane", source="screen")
        )
        await manager.wait_for_idle()

        # Then: se incluye pero marcado como best-effort, no como certeza
        result = results.seen[0]
        assert "via=vlm" in result.text and "best-effort" in result.text
    finally:
        await asyncio.wait_for(manager.disable_plugin(results.name), timeout=5.0)
        await manager.close()


@pytest.mark.asyncio
async def test_detect_false_not_called(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: vision_detect=false (default)
    sidecar = _FakeSidecar(ocr=OCR_TEXT, detect=DETECT_TEXT)
    _install_fake_sidecar(monkeypatch, sidecar)
    _install_fake_primary(monkeypatch)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    try:
        plugin = await _make_plugin(manager)
        plugin._append_frame("screen", _noise_frame(7), 10.0)

        # When: describing con detección apagada
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="jane", source="screen")
        )
        await manager.wait_for_idle()

        # Then: nunca se llama detect_objects ni se inventa OBJECTS
        result = results.seen[0]
        assert "detect_objects" not in sidecar.calls
        assert "OBJECTS:" not in result.text
    finally:
        await asyncio.wait_for(manager.disable_plugin(results.name), timeout=5.0)
        await manager.close()


def test_frame_mentions_ocr_and_keeps_no_instructions() -> None:
    # Given: un bloque look-at con texto de pantalla en OCR:
    block = (
        "[look-at screen 5s]: --- screen (5s, 1/5 frames) ---\n"
        f"VISUAL: {CAPTION}\nOCR: {OCR_TEXT}"
    )

    # When: la voz lo enmarca (bug 121)
    framed = frame_look_at_turn(block, "es")

    # Then: el marco menciona OCR: y mantiene la prohibición de pedir instrucciones
    assert "OCR:" in framed
    assert "Nunca pidas instrucciones" in framed
    assert "No inventes" in framed
    assert block in framed  # el bloque viaja intacto


def _install_slow_primary(
    monkeypatch: pytest.MonkeyPatch,
    ready: asyncio.Event,
    release: asyncio.Event,
) -> None:
    async def create(**kwargs):
        ready.set()
        await release.wait()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=CAPTION))]
        )

    monkeypatch.setattr(
        svp,
        "_openai_client",
        lambda *a, **k: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )


class _GenerateRecorder(Plugin):
    # Named like the voice: the narration generate is emitted with target=voice.
    def __init__(self, name: str = "jane") -> None:
        super().__init__(name=name)
        self.seen: list[object] = []

    async def initialize(self) -> None:
        from kateto.core.event import GenerateData

        self.required_manager.register_event("generate", GenerateData)

    async def on_generate(self, data) -> None:
        self.seen.append(data)


async def _teardown(manager: PluginManager, *plugins: Plugin) -> None:
    for plugin in plugins:
        await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    await manager.close()


@pytest.mark.asyncio
async def test_user_interrupt_cancels_in_flight_describe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: un describe en vuelo bloqueado en el VLM
    ready = asyncio.Event()
    release = asyncio.Event()
    _install_fake_sidecar(monkeypatch, _FakeSidecar(ocr=OCR_TEXT))
    _install_slow_primary(monkeypatch, ready, release)
    manager = PluginManager()
    results = _ResultRecorder()
    generates = _GenerateRecorder()
    await manager.enable_plugin(results)
    await manager.enable_plugin(generates)
    plugin = await _make_plugin(manager)
    try:
        plugin._append_frame("screen", _noise_frame(1), 10.0)
        task = asyncio.create_task(
            plugin.on_vision_describe_request(
                VisionDescribeRequestData(requester="jane", source="screen")
            )
        )
        await asyncio.wait_for(ready.wait(), timeout=5)
        assert plugin._describe_tasks.get("jane") is not None

        # When: el usuario habla encima (interrupt de usuario)
        await manager.emit(
            "interrupt", InterruptData(reason="voice_activity"), source="vad"
        )
        await manager.wait_for_idle(timeout=5)
        release.set()
        await asyncio.wait_for(task, timeout=5)

        # Then: la tarea en vuelo se cancela y no se narra ni se emite generate
        assert results.seen == []
        assert generates.seen == []
        assert plugin._describe_tasks.get("jane") is None
    finally:
        await _teardown(manager, results, generates, plugin)


@pytest.mark.asyncio
async def test_stale_epoch_result_is_discarded_with_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: un describe en vuelo cuyo resultado vuelve con la época vieja
    ready = asyncio.Event()
    release = asyncio.Event()
    _install_fake_sidecar(monkeypatch, _FakeSidecar(ocr=OCR_TEXT))
    _install_slow_primary(monkeypatch, ready, release)
    manager = PluginManager()
    results = _ResultRecorder()
    generates = _GenerateRecorder()
    await manager.enable_plugin(results)
    await manager.enable_plugin(generates)
    plugin = await _make_plugin(manager)
    messages: list[str] = []
    sink = logger.add(messages.append, format="{message}")
    try:
        plugin._append_frame("screen", _noise_frame(2), 10.0)
        task = asyncio.create_task(
            plugin.on_vision_describe_request(
                VisionDescribeRequestData(requester="jane", source="screen")
            )
        )
        await asyncio.wait_for(ready.wait(), timeout=5)

        # When: la época sube mientras el describe está en vuelo (sin cancelar)
        plugin._user_epoch["jane"] = plugin._user_epoch.get("jane", 0) + 1
        release.set()
        await asyncio.wait_for(task, timeout=5)
        await manager.wait_for_idle(timeout=5)

        # Then: el resultado se descarta con log y no se emite generate
        assert "describe result discarded for jane" in "\n".join(messages)
        assert generates.seen == []
    finally:
        logger.remove(sink)
        await _teardown(manager, results, generates, plugin)


@pytest.mark.asyncio
async def test_look_at_after_interrupt_still_answers_with_fresh_epoch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: un describe cancelado por interrupt (época sube) y luego un
    # look-at pedido por el usuario sin barge-in posterior
    _install_fake_sidecar(monkeypatch, _FakeSidecar(ocr=OCR_TEXT))
    _install_fake_primary(monkeypatch)
    manager = PluginManager()
    results = _ResultRecorder()
    generates = _GenerateRecorder()
    await manager.enable_plugin(results)
    await manager.enable_plugin(generates)
    plugin = await _make_plugin(manager)
    try:
        plugin._append_frame("screen", _noise_frame(3), 10.0)

        # When: interrupt primero (época sube) y el usuario pide look-at después
        await manager.emit(
            "interrupt", InterruptData(reason="voice_activity"), source="vad"
        )
        await manager.wait_for_idle(timeout=5)
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="jane", source="screen")
        )
        await manager.wait_for_idle(timeout=5)

        # Then: el look-at responde (época fresca) y no se descarta
        assert len(results.seen) == 1
    finally:
        await _teardown(manager, results, generates, plugin)


@pytest.mark.asyncio
async def test_periodic_narration_emits_ambient_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: el plugin con un narrador periódico due (rango fijo) y sin OCR
    # (la primera narración con OCR y _last_narrated vacío se saltea por diseño)
    _install_fake_sidecar(monkeypatch, _FakeSidecar())
    _install_fake_primary(monkeypatch)
    manager = PluginManager()
    results = _ResultRecorder()
    generates = _GenerateRecorder()
    await manager.enable_plugin(results)
    await manager.enable_plugin(generates)
    plugin = await _make_plugin(manager)
    try:
        plugin._append_frame("screen", _noise_frame(4), 10.0)
        plugin._vision_range["jane"] = (0, 0)  # siempre due

        # When: la narración periódica corre
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="scheduler:jane", source="screen")
        )
        await manager.wait_for_idle(timeout=5)

        # Then: el generate lleva origin="ambient"
        assert len(generates.seen) == 1
        assert generates.seen[0].origin == "ambient"
    finally:
        await _teardown(manager, results, generates, plugin)