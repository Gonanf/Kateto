"""Modo stream: frases random con timing configurable, sin audio ni red.

Fake manager que captura los eventos ``speak`` emitidos; tiempos de 50ms y
``asyncio.wait_for`` como cota. Nada de sounddevice ni pw-play acá.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import pytest

from hipotenusa.core.event import SpeakRequestData
from hipotenusa.plugins.system.stream_mode import CALMA, StreamModePlugin


class _FakeManager:
    """Captura lo emitido; lo mínimo que toca el plugin."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def register_event(self, *args: Any, **kwargs: Any) -> None:
        pass

    def get_plugin(self, name: str) -> None:
        return None

    async def emit(self, name: str, data: Any, **kwargs: Any) -> None:
        self.events.append((name, data))


async def _until(predicate, timeout: float = 2.0) -> None:
    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(_poll(), timeout=timeout)


def _plugin(manager: _FakeManager, **overrides: Any) -> StreamModePlugin:
    settings = {"enabled": True, "min_s": 0.05, "max_s": 0.05, "voice": "jane"}
    settings.update(overrides)
    plugin = StreamModePlugin(settings, rng=random.Random(7))
    plugin.manager = manager  # type: ignore[assignment]
    return plugin


@pytest.mark.asyncio
async def test_emits_literal_speak_from_pool() -> None:
    manager = _FakeManager()
    plugin = _plugin(manager)
    await plugin.enable()
    try:
        await _until(lambda: len(manager.events) >= 2)
    finally:
        await plugin.disable()

    assert all(name == "speak" for name, _ in manager.events)
    data = manager.events[0][1]
    assert isinstance(data, SpeakRequestData)
    assert data.voice == "jane"
    assert data.literal is True
    assert data.origin == "external"
    assert data.prompt in CALMA


@pytest.mark.asyncio
async def test_phrases_override() -> None:
    manager = _FakeManager()
    plugin = _plugin(manager, phrases=["una sola frase"])
    await plugin.enable()
    try:
        await _until(lambda: manager.events)
    finally:
        await plugin.disable()

    assert manager.events[0][1].prompt == "una sola frase"


@pytest.mark.asyncio
async def test_disable_cancels_timer() -> None:
    manager = _FakeManager()
    plugin = _plugin(manager, min_s=0.02, max_s=0.02)
    await plugin.enable()
    await _until(lambda: len(manager.events) >= 2)
    await plugin.disable()

    assert plugin._task is None
    seen = len(manager.events)
    await asyncio.sleep(0.1)
    assert len(manager.events) == seen, "siguió hablando después de disable"


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [{"enabled": False}, {"enabled": True, "filler": False}])
async def test_off_by_config_or_without_filler(settings: dict[str, Any]) -> None:
    manager = _FakeManager()
    plugin = _plugin(manager, min_s=0.02, max_s=0.02, **settings)
    await plugin.enable()
    await asyncio.sleep(0.1)
    assert plugin._task is None
    assert manager.events == []


def test_does_not_shadow_plugin_worker() -> None:
    # Plugin._run es el consumidor de la cola del manager: pisarlo lo rompe
    # (y duplicaba los emits porque corrían dos loops).
    from hipotenusa.core.plugin import Plugin

    assert StreamModePlugin._run is Plugin._run


def test_superchat_ranks_before_messages() -> None:
    """La donación se dice primero aunque el mensaje haya llegado antes."""
    paid = {"liveChatPaidMessageRenderer": {"id": "2", "authorName": {"simpleText": "@dona"},
            "purchaseAmountText": {"simpleText": "$5.00"},
            "message": {"runs": [{"text": "morite alien"}]}}}
    text_item = {"liveChatTextMessageRenderer": {"id": "1", "authorName": {"simpleText": "@tester"},
                 "message": {"runs": [{"text": "hola"}]}}}

    from hipotenusa.plugins.system.stream_mode import classify

    said = classify(paid)
    assert said is not None and said[0] == 0 and "$5.00" in said[1]
    assert classify(text_item) == (1, "tester dice: hola")

    async def order() -> list[str]:
        plugin = StreamModePlugin(settings=None)
        plugin._say_later(*classify(text_item))
        plugin._say_later(*said)
        return [(await plugin._queue.get())[2] for _ in range(2)]

    assert asyncio.run(order())[0].startswith("\u00a1$5.00")


@pytest.mark.asyncio
async def test_chat_mode_needs_only_video_url() -> None:
    """Con video_url alcanza para estar disponible aunque filler esté apagado."""
    manager = _FakeManager()
    plugin = StreamModePlugin({"enabled": True, "filler": False, "video_url": "abc123"}, rng=random.Random(1))
    plugin.manager = manager  # type: ignore[assignment]
    assert plugin.available is True
    assert StreamModePlugin({"enabled": True, "filler": False}).available is False
