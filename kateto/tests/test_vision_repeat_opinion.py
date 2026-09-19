"""Narracion de vision: opina (no transcribe) y se calla si la pantalla es la misma.

Bug 123: el caption era un inventario literal en ingles, la voz lo repetia,
y con la pantalla quieta narraba la misma escena cada 30 s gastando un VLM
por tick. Ahora el prompt al VLM pide material opinable en espanol, la voz
opina sin repetir el literal, y el tick periodico se calla ante imagen
repetida (hash) o caption casi identico (texto) sin costo VLM en el primer
caso. El look-at pedido por el usuario siempre contesta.
"""

from __future__ import annotations

import asyncio
import io
import random
from types import SimpleNamespace

import pytest
from loguru import logger

from kateto.core.event import VisionDescribeRequestData
from kateto.core.manager import PluginManager
from kateto.plugins.executor import static_vision_plugin as svp
from kateto.plugins.executor.static_vision_plugin import (
    StaticVisionPlugin,
    _describe_prompt,
    _dhash,
    _hamming,
)
from kateto.voices.base import frame_look_at_turn, pick_narration_angle


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
    def __init__(self, text: str) -> None:
        self.text = text
        self.seen: list = []

    async def try_call_tool(self, servers, tool, args):
        self.seen.append((servers, tool, args))
        return self.text


def _install_fake_sidecar(monkeypatch: pytest.MonkeyPatch, mcp: _FakeSidecar) -> None:
    monkeypatch.setattr(svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=mcp))


def _install_fake_primary(
    monkeypatch: pytest.MonkeyPatch, calls: list, text: str | list[str] = "una terminal con código en pantalla"
) -> None:
    async def create(**kwargs):
        calls.append(kwargs)
        content = text[len(calls) - 1] if isinstance(text, list) else text
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(
        svp, "_openai_client", lambda *args: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    )


async def _make_plugin(manager: PluginManager, **kwargs) -> StaticVisionPlugin:
    plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    for key, value in kwargs.items():
        setattr(plugin, key, value)
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()
    plugin._windows.clear()
    plugin._dropped.clear()
    return plugin


async def _teardown(manager: PluginManager, *names: str) -> None:
    for name in names:
        await asyncio.wait_for(manager.disable_plugin(name), timeout=5.0)


def _generates(envelopes: list) -> list:
    return [e for e in envelopes if e.name == "generate"]


@pytest.mark.asyncio
async def test_periodic_same_screen_second_tick_silent_no_sidecar_call(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: sin VLM primario, sidecar que responde, un frame en ventana
    sidecar = _FakeSidecar("una terminal con código en pantalla")
    _install_fake_sidecar(monkeypatch, sidecar)
    manager = PluginManager()
    plugin = await _make_plugin(manager, vision_endpoint=None, vision_model=None)
    plugin._append_frame("screen", _noise_frame(7), 10.0)
    envelopes: list = []
    manager.add_event_observer(envelopes.append)
    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="INFO")
    try:
        # When: dos ticks periodicos con la misma pantalla
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="scheduler:jane", source="screen")
        )
        await manager.wait_for_idle()
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="scheduler:jane", source="screen")
        )
        await manager.wait_for_idle()
    finally:
        logger.remove(handler_id)
        manager.remove_event_observer(envelopes.append)
    joined = "\n".join(messages)

    # Then: el primero narra, el segundo se calla sin llamar al sidecar
    assert len(sidecar.seen) == 1
    assert len(_generates(envelopes)) == 1
    assert "imagen repetida" in joined
    assert "hamming 0/6" in joined
    await _teardown(manager, plugin.name)


@pytest.mark.asyncio
async def test_periodic_distinct_screen_narrates(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: primario fake, primer tick con una pantalla
    calls: list = []
    _install_fake_primary(monkeypatch, calls, text=["una terminal con código en pantalla", "un navegador con varias pestañas abiertas"])
    manager = PluginManager()
    plugin = await _make_plugin(manager, vision_endpoint="http://primary:8080/v1", vision_model="vlm")
    plugin._append_frame("screen", _noise_frame(1), 20.0)
    envelopes: list = []
    manager.add_event_observer(envelopes.append)

    # When: tick, cambio de pantalla, tick
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="scheduler:jane", source="screen")
    )
    await manager.wait_for_idle()
    plugin._windows["screen"].clear()
    plugin._append_frame("screen", _noise_frame(2), 30.0)
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="scheduler:jane", source="screen")
    )
    await manager.wait_for_idle()
    manager.remove_event_observer(envelopes.append)

    # Then: narra las dos veces
    assert len(calls) == 2
    assert len(_generates(envelopes)) == 2
    await _teardown(manager, plugin.name)


@pytest.mark.asyncio
async def test_periodic_same_caption_different_frames_skips_by_text(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: primario que devuelve casi el mismo caption, pantallas distintas
    first = _noise_frame(1)
    second_seed = 2
    while _hamming(_dhash(first), _dhash(_noise_frame(second_seed))) <= 6:  # type: ignore[arg-type]
        second_seed += 1
    calls: list = []
    _install_fake_primary(monkeypatch, calls, text="una terminal con código en pantalla")
    manager = PluginManager()
    plugin = await _make_plugin(manager, vision_endpoint="http://primary:8080/v1", vision_model="vlm")
    plugin._append_frame("screen", first, 40.0)
    envelopes: list = []
    results: list = []
    manager.add_event_observer(envelopes.append)

    from kateto.core.plugin import Plugin

    class _ResultsPlugin(Plugin):
        def __init__(self) -> None:
            super().__init__(name="results")

        async def on_vision_describe_result(self, data) -> None:  # type: ignore[no-untyped-def]
            results.append(data)

    await manager.enable_plugin(_ResultsPlugin())
    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="INFO")
    try:
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="scheduler:jane", source="screen")
        )
        await manager.wait_for_idle()
        plugin._windows["screen"].clear()
        plugin._append_frame("screen", _noise_frame(second_seed), 50.0)
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="scheduler:jane", source="screen")
        )
        await manager.wait_for_idle()
    finally:
        logger.remove(handler_id)
        manager.remove_event_observer(envelopes.append)
    joined = "\n".join(messages)

    # Then: el VLM trabajo dos veces pero solo se narro una (capa de texto)
    assert len(calls) == 2
    assert len(results) == 2
    assert len(_generates(envelopes)) == 1
    assert "caption repetido" in joined
    assert "similitud 1.00" in joined
    await _teardown(manager, plugin.name, "results")


@pytest.mark.asyncio
async def test_user_ask_same_screen_always_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: primario fake y la misma pantalla
    calls: list = []
    _install_fake_primary(monkeypatch, calls)
    manager = PluginManager()
    plugin = await _make_plugin(manager, vision_endpoint="http://primary:8080/v1", vision_model="vlm")
    payload = _noise_frame(9)
    plugin._append_frame("screen", payload, 60.0)

    from kateto.core.plugin import Plugin

    results: list = []

    class _ResultsPlugin(Plugin):
        def __init__(self) -> None:
            super().__init__(name="results")

        async def on_vision_describe_result(self, data) -> None:  # type: ignore[no-untyped-def]
            results.append(data)

    await manager.enable_plugin(_ResultsPlugin())

    # When: dos pedidos directos del usuario con imagen repetida
    await plugin.on_vision_describe_request(VisionDescribeRequestData(requester="jane", source="screen"))
    await manager.wait_for_idle()
    await plugin.on_vision_describe_request(VisionDescribeRequestData(requester="jane", source="screen"))
    await manager.wait_for_idle()

    # Then: contesta las dos veces
    assert len(calls) == 2
    assert len(results) == 2
    await _teardown(manager, plugin.name, "results")


def test_turn_instruction_reacts_instead_of_reviewing() -> None:
    # Given: el caption pelado en ambos idiomas y un ángulo fijo
    caption = "[look-at screen 5s]: terminal con código"
    # When: se enmarca el turno
    es = frame_look_at_turn(caption, "es", angle="queja")
    en = frame_look_at_turn(caption, "en", angle="queja")
    # Then: una sola línea, dirigida al usuario, con el ángulo explícito
    assert "UNA sola línea corta" in es
    assert "AL USUARIO" in es
    assert "Esta vez: una queja" in es
    assert "ONE short line" in en
    assert "TO the user" in en
    assert "This time: a gripe" in en
    # And: el registro viejo de reseña desapareció
    assert "Opiná" not in es
    assert "qué te parece" not in es
    assert "qué te llama la atención" not in es
    assert "Give your opinion" not in en
    assert "catches your eye" not in en
    # And: siguen las prohibiciones estructurales
    assert "Nunca pidas instrucciones" in es
    assert "No inventes" in es
    assert "Never ask for instructions" in en


def test_vlm_prompt_in_spanish_asks_standout() -> None:
    # When: se arma el prompt al VLM
    prompt = _describe_prompt(2, "screen", "t+0.0s, t+4.0s")
    # Then: en espanol, pide lo que llama la atencion y prohibe inventar
    assert "español" in prompt
    assert "llama la atención" in prompt
    assert "cambió" in prompt
    assert "No inventes" in prompt
