"""Bug 121: el turno de visión es una instrucción, no un dato pelado.

Un `generate` con prompt `[look-at …]` (o un `vision_describe_result` del
look-at pedido) tiene que llegar al modelo con marco —mirada propia, idioma
de la voz, prohibido preguntar qué hacer— y el caption intacto. La charla
normal no se envuelve y el prompt estable no cambia.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from kateto.core import PluginManager
from kateto.core.config import VoiceSettings
from kateto.core.event import GenerateData, VisionDescribeResultData
from kateto.voices.base import (
    GenerationRequest,
    VoiceAgent,
    VoiceProfile,
    VoiceRole,
    frame_look_at_turn,
)


class RecordingProvider:
    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        return self._tokens()

    async def _tokens(self) -> AsyncIterator[str]:
        yield "reply"


def _voice(
    tmp_path: Path, provider: RecordingProvider, response_language: str | None = None
) -> VoiceAgent:
    path = tmp_path / "voices" / "jane" / "reference.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFFfixtureWAVE")
    return VoiceAgent(
        profile=VoiceProfile(
            voice_id="jane",
            display_name="Jane",
            role=VoiceRole.SITUATIONAL_ABSURD,
            system_prompt="You are Jane, the lead.",
            relevance_terms=frozenset(),
        ),
        config_dir=tmp_path,
        provider=provider,
        settings=VoiceSettings(),
        response_language=response_language,
    )


CAPTION = "[look-at screen 5s]: terminal with code on screen"


@pytest.mark.asyncio
async def test_look_at_generate_arrives_framed_with_caption_intact(tmp_path: Path) -> None:
    # Given: una voz con idioma es (None cae al idioma del proyecto: español)
    provider = RecordingProvider()
    voice = _voice(tmp_path, provider)
    manager = PluginManager()
    await manager.enable_plugin(voice)
    try:
        # When: narración ambiental con el caption pelado
        await manager.emit("generate", GenerateData(prompt=CAPTION), source="static_vision")
        await manager.wait_for_idle()

        # Then: el turno lleva instrucción + caption intacto
        user_turn = provider.requests[0].messages[-1].content
        assert "propia mirada" in user_turn
        assert "Nunca pidas instrucciones" in user_turn
        assert "No inventes" in user_turn
        assert CAPTION in user_turn
        assert "español" in user_turn
        # And: el prompt estable no tocó (sigue congelado, sin instrucción)
        stable = provider.requests[0].messages[0].content
        assert "propia mirada" not in stable
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_normal_generate_is_not_wrapped(tmp_path: Path) -> None:
    # Given: la misma voz
    provider = RecordingProvider()
    voice = _voice(tmp_path, provider)
    manager = PluginManager()
    await manager.enable_plugin(voice)
    try:
        # When: charla normal
        await manager.emit("generate", GenerateData(prompt="Hola, ¿cómo estás?"), source="fixture")
        await manager.wait_for_idle()

        # Then: el turno viaja pelado
        assert provider.requests[0].messages[-1].content == "Hola, ¿cómo estás?"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_language_comes_from_voice_config(tmp_path: Path) -> None:
    # Given: una voz con response_language = "en"
    provider = RecordingProvider()
    voice = _voice(tmp_path, provider, response_language="en")
    manager = PluginManager()
    await manager.enable_plugin(voice)
    try:
        # When: el mismo caption pelado
        await manager.emit("generate", GenerateData(prompt=CAPTION), source="static_vision")
        await manager.wait_for_idle()

        # Then: la instrucción va en inglés, nada de español hardcodeado
        user_turn = provider.requests[0].messages[-1].content
        assert "own look" in user_turn
        assert "Never ask for instructions" in user_turn
        assert CAPTION in user_turn
        assert "propia mirada — vos" not in user_turn
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_requested_look_at_result_lands_framed(tmp_path: Path) -> None:
    # Given: una voz habilitada (camino tool/event del look-at pedido)
    provider = RecordingProvider()
    voice = _voice(tmp_path, provider)
    manager = PluginManager()
    await manager.enable_plugin(voice)
    try:
        # When: llega el resultado que el modelo mismo pidió
        await manager.emit(
            "vision_describe_result",
            VisionDescribeResultData(
                text="terminal with code on screen",
                frame_count=5,
                kept_count=3,
                dropped=0,
                window_start=10.0,
                window_end=15.0,
                source="screen",
                via="sidecar",
            ),
            source="static_vision",
        )
        await manager.wait_for_idle()

        # Then: la memoria guarda el marco + el bloque crudo intacto
        memories = [m.content for m in voice.message_history]
        framed = next(m for m in memories if "terminal with code" in m)
        assert "propia mirada" in framed
        assert "Nunca pidas instrucciones" in framed
        assert "[look-at screen 5s]" in framed
    finally:
        await manager.close()


def test_frame_is_idempotent() -> None:
    # Given: un bloque ya enmarcado
    once = frame_look_at_turn(CAPTION, "es")
    # When/Then: enmarcar de nuevo es no-op
    assert frame_look_at_turn(once, "es") == once
    assert frame_look_at_turn(once, "en") == once
