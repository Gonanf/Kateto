"""Bug 128: la narración de visión sale del molde del reseñador.

El marco viejo pedía una reseña ("opiná… qué te parece") y el material era un
caption neutral en tercera persona, así que el modelo chico convergía siempre a
"me parece interesante que…" / "el usuario está aprendiendo…". Sin listas
negras de palabras (prohibidas: sólo mueven la fórmula), el fix es estructural:

1. El marco pide UNA línea corta hablándole al usuario de vos, sobre el
   contenido (OCR), no sobre su actividad — ya no pide reseña.
2. Variedad por construcción: un ángulo sorteado por narración, sin repetir el
   anterior (rng inyectable, tests deterministas).
3. Memoria: las últimas narraciones entran al marco; y el backstop numérico
   (ratio >= 0.85 contra las últimas 3, mismo criterio que fix-111) descarta
   la narración repetida antes de hablar.
"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from loguru import logger

from kateto.core import PluginManager
from kateto.core.config import VoiceSettings
from kateto.core.event import GenerateData, TextChunk
from kateto.voices.base import (
    NARRATION_ANGLES,
    NARRATION_ANGLES_ES,
    GenerationRequest,
    VoiceAgent,
    VoiceProfile,
    VoiceRole,
    frame_look_at_turn,
    pick_narration_angle,
    text_ratio,
)

CAPTION = "[look-at screen 5s]: terminal with code on screen"
OLD_REVIEW_MARKS_ES = ("Opiná", "qué te parece", "qué te llama la atención")
OLD_REVIEW_MARKS_EN = ("Give your opinion", "catches your eye")


class RecordingProvider:
    def __init__(self, text: str = "che, mirá ese bucle, te va a colgar la terminal") -> None:
        self.text = text
        self.requests: list[GenerationRequest] = []

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        return self._tokens()

    async def _tokens(self) -> AsyncIterator[str]:
        for char in self.text:
            yield char


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


def test_frame_contains_drawn_angle_one_line_second_person_both_languages() -> None:
    # Given: un rng sembrado y el caption pelado
    rng = random.Random(0)
    for lang in ("es", "en"):
        # When: se sortea el ángulo y se enmarca
        angle = pick_narration_angle(rng, None, lang)
        framed = frame_look_at_turn(CAPTION, lang, angle=angle)
        # Then: el marco contiene el ángulo sorteado
        assert angle in NARRATION_ANGLES
        if lang == "es":
            assert NARRATION_ANGLES_ES[angle] in framed
            assert "UNA sola línea corta" in framed
            assert "AL USUARIO" in framed
            assert "Esta vez:" in framed
        else:
            assert "ONE short line" in framed
            assert "TO the user" in framed
            assert "This time:" in framed
        # And: ya no está el pedido viejo de reseña
        for mark in OLD_REVIEW_MARKS_ES if lang == "es" else OLD_REVIEW_MARKS_EN:
            assert mark not in framed


def test_seeded_six_narrations_never_repeat_consecutive_angle() -> None:
    # Given: un rng sembrado simulando 6 narraciones seguidas
    rng = random.Random(42)
    previous: str | None = None
    drawn: list[str] = []
    # When: se sortea un ángulo por narración
    for _ in range(6):
        angle = pick_narration_angle(rng, previous, "es")
        # Then: ningún ángulo repetido consecutivo
        assert angle != previous
        drawn.append(angle)
        previous = angle
    # And: al menos 4 ángulos distintos en total
    assert len(set(drawn)) >= 4


def test_frame_includes_recent_narrations_only_when_present() -> None:
    # Given: narraciones previas
    recent = ("che, mirá ese bucle, te va a colgar", "eso te va a morder")
    # When: se enmarca con y sin memoria
    with_memory = frame_look_at_turn(CAPTION, "es", angle="dato", recent=recent)
    without_memory = frame_look_at_turn(CAPTION, "es", angle="dato")
    # Then: la memoria entra como anti-repetición sólo si hay
    assert "Ya dijiste esto" in with_memory
    for line in recent:
        assert line in with_memory
    assert "Ya dijiste esto" not in without_memory


def test_text_ratio_mirrors_caption_ratio() -> None:
    # Given/When/Then: mismo criterio que `_caption_ratio` (fix-111)
    assert text_ratio("Hola Mundo", "hola mundo") == 1.0
    assert text_ratio("abc", "xyz") < 0.85


@pytest.mark.asyncio
async def test_similar_narration_is_dropped_before_speaking(tmp_path: Path) -> None:
    # Given: una voz que ya dijo una línea y un provider que repite casi igual
    spoken = "che, mirá ese bucle, te va a colgar la terminal"
    provider = RecordingProvider(text=spoken + ".")
    voice = _voice(tmp_path, provider)
    voice._recent_narrations.append(spoken)
    manager = PluginManager()
    await manager.enable_plugin(voice)

    chunks: list[TextChunk] = []

    from kateto.core.plugin import Plugin

    class _ChunkCollector(Plugin):
        def __init__(self) -> None:
            super().__init__(name="chunk_collector")

        async def on_text_chunk(self, data: TextChunk) -> None:
            chunks.append(data)

    await manager.enable_plugin(_ChunkCollector())  # type: ignore[arg-type]
    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="INFO")
    try:
        # When: la narración nueva es >= 0.85 parecida a la reciente
        await manager.emit("generate", GenerateData(prompt=CAPTION), source="static_vision")
        await manager.wait_for_idle()

        # Then: no se habla (sin frases de audio) y queda log
        spoken_phrases = [c for c in chunks if c.text.strip()]
        assert spoken_phrases == []
        joined = "\n".join(messages)
        assert "narración de visión descartada" in joined
        # And: la repetida no entra a la memoria
        assert list(voice._recent_narrations) == [spoken]
    finally:
        logger.remove(handler_id)
        await manager.close()


@pytest.mark.asyncio
async def test_fresh_narration_is_spoken_framed_and_remembered(tmp_path: Path) -> None:
    # Given: la voz con una narración previa distinta y un rng sembrado
    provider = RecordingProvider(text="che, mirá: ese log crece por segundo.")
    voice = _voice(tmp_path, provider)
    voice._recent_narrations.append("eso te va a morder más tarde")
    voice._narration_rng = random.Random(3)
    manager = PluginManager()
    await manager.enable_plugin(voice)
    try:
        # When: la narración nueva no se parece a ninguna reciente
        await manager.emit("generate", GenerateData(prompt=CAPTION), source="static_vision")
        await manager.wait_for_idle()

        # Then: el turno llegó con marco, ángulo sorteado y memoria al modelo
        user_turn = provider.requests[0].messages[-1].content
        assert "propia mirada" in user_turn
        assert "Esta vez:" in user_turn
        assert "Ya dijiste esto" in user_turn
        assert "eso te va a morder más tarde" in user_turn
        # And: la narración hablada entró a la memoria
        assert any("ese log crece por segundo" in t for t in voice._recent_narrations)
        # And: el ángulo quedó anotado para no repetirlo
        assert voice._last_narration_angle in NARRATION_ANGLES
    finally:
        await manager.close()
