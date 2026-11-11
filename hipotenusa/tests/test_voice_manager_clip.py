"""El pasador de turno IA->IA (clip) respeta tope de turnos, cooldown y elección de par."""
from __future__ import annotations

import pytest

from hipotenusa.core import PluginManager
from hipotenusa.core.config import PluginSettings
from hipotenusa.core.event import TranscriptionData
from hipotenusa.core.plugin import Plugin
from hipotenusa.plugins.system.voice_manager import VoiceManager


class _FakeVoice(Plugin):
    def __init__(self, name: str) -> None:
        super().__init__(name, capabilities=("voice",))


def _settings(**extra: object) -> PluginSettings:
    base = {"interject_enabled": True, "interject_chance": 1.0,
            "interject_max_turns": 2, "interject_cooldown": "0s",
            "voice_probabilities": {"alfa": 1.0, "beta": 1.0}}
    base.update(extra)
    return PluginSettings(**base)


async def _manager_with_al_alfa_y_beta() -> tuple[PluginManager, VoiceManager]:
    manager = PluginManager()
    await manager.enable_plugin(_FakeVoice("alfa"))
    await manager.enable_plugin(_FakeVoice("beta"))
    return manager, VoiceManager(_settings())


@pytest.mark.asyncio
async def test_clip_pasa_el_turno_a_la_otra_voz_y_respeta_el_tope() -> None:
    # Given: dos voces habilitadas y el manager con su remate guardado
    manager, vm = await _manager_with_al_alfa_y_beta()
    await manager.enable_plugin(vm)
    seen: list[tuple[str, str | None]] = []
    manager.add_event_observer(lambda env: seen.append((env.name, env.target)))
    vm._last_line["alfa"] = "el plan ya está en marcha"

    # When: alfa termina de hablar (dos veces, que es el tope configurado)
    await vm._maybe_clip("alfa")
    await vm._maybe_clip("alfa")

    # Then: las dos veces le pasó el turno a beta y nunca a sí misma
    assert [n for n, _ in seen] == ["generate_request", "generate_request"]
    assert {t for _, t in seen} == {"beta"}

    # When: se llama una tercera vez
    await vm._maybe_clip("alfa")

    # Then: la cadena ya se cerró sola: no hay turnos nuevos
    assert len(seen) == 2
    assert vm._clip_turns == 0


@pytest.mark.asyncio
async def test_clip_no_arranca_sin_linea_ni_sin_peer() -> None:
    # Given: una sola voz habilitada (sin par posible)
    manager = PluginManager()
    await manager.enable_plugin(_FakeVoice("alfa"))
    vm = VoiceManager(_settings())
    await manager.enable_plugin(vm)
    seen: list[str] = []
    manager.add_event_observer(lambda env: seen.append(env.name))

    # When: alfa termina sin haber dicho nada y después con texto pero sin par
    await vm._maybe_clip("alfa")
    vm._last_line["alfa"] = "algo dijo"
    await vm._maybe_clip("alfa")

    # Then: no se emitió ningún turno
    assert seen == []


@pytest.mark.asyncio
async def test_clip_apagado_y_reset_con_habla_del_usuario() -> None:
    # Given: clip apagado en config
    manager, vm = await _manager_with_al_alfa_y_beta()
    vm._settings = _settings(interject_enabled=False)
    await manager.enable_plugin(vm)
    seen: list[str] = []
    manager.add_event_observer(lambda env: seen.append(env.name))
    vm._last_line["alfa"] = "el plan ya está en marcha"

    # When: alfa termina de hablar con el clip apagado
    await vm._maybe_clip("alfa")

    # Then: nada emitido
    assert seen == []

    # When: el clip está prendido, hay una cadena abierta y habla el usuario
    vm._settings = _settings()
    await vm._maybe_clip("alfa")
    assert seen == ["generate_request"]
    assert vm._clip_turns == 1
    await vm.on_transcription(TranscriptionData(text="hola", language="es"))

    # Then: la cadena se cortó
    assert vm._clip_turns == 0
