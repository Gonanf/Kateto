from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kateto.core import PluginManager
from kateto.core.config import VoiceSettings
from kateto.core.event import Classification, ClassificationData, TranscriptionData
from kateto.plugins.system.turn_gate import Decision, TurnGate
from kateto.voices.base import IGNORED_TRANSCRIPT_PREFIX, VoiceAgent, VoiceProfile, VoiceRole


def _voice(tmp_path: Path, *, stream: bool = False) -> VoiceAgent:
    profile = VoiceProfile(
        voice_id="jane",
        display_name="Jane",
        role=VoiceRole.SITUATIONAL_ABSURD,
        system_prompt="system",
        relevance_terms=frozenset(),
    )
    return VoiceAgent(
        profile=profile,
        config_dir=tmp_path,
        provider=MagicMock(),
        settings=VoiceSettings(stream=stream),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("category", (Classification.IGNORE_SELF_TALK, Classification.IGNORE_THIRD_PARTY))
async def test_ignored_transcription_is_marked_in_history(category: Classification, tmp_path: Path) -> None:
    # Given: una voz que ya recibió la transcripción "Gracias.".
    voice = _voice(tmp_path)
    manager = PluginManager()
    await manager.enable_plugin(voice)
    try:
        # When: el clasificador la etiqueta como ignorada.
        await manager.emit("transcription", TranscriptionData(text="Gracias."), source="fixture")
        await manager.wait_for_idle()
        await manager.emit(
            "classification",
            ClassificationData(text="Gracias.", category=category),
            source="classifier",
        )
        await manager.wait_for_idle()

        # Then: el historial la conserva con marca explícita y texto original, sin duplicarla en claro.
        contents = [message.content for message in voice.message_history if message.role == "user"]
        assert any(
            IGNORED_TRANSCRIPT_PREFIX in content and "Gracias." in content for content in contents
        )
        assert "Gracias." not in contents
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_execute_classification_does_not_mark_history(tmp_path: Path) -> None:
    # Given: una voz con una transcripción normal.
    voice = _voice(tmp_path)
    manager = PluginManager()
    await manager.enable_plugin(voice)
    try:
        # When: el clasificador la etiqueta EXECUTE.
        await manager.emit("transcription", TranscriptionData(text="Hola Jane"), source="fixture")
        await manager.wait_for_idle()
        await manager.emit(
            "classification",
            ClassificationData(text="Hola Jane", category=Classification.EXECUTE),
            source="classifier",
        )
        await manager.wait_for_idle()

        # Then: el historial queda intacto, sin marca.
        contents = [message.content for message in voice.message_history if message.role == "user"]
        assert contents == ["Hola Jane"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_mark_lives_in_volatile_history_not_stable_prompt(tmp_path: Path) -> None:
    # Given: una voz con una transcripción ignorada ya marcada.
    voice = _voice(tmp_path)
    manager = PluginManager()
    await manager.enable_plugin(voice)
    try:
        await manager.emit("transcription", TranscriptionData(text="Gracias."), source="fixture")
        await manager.wait_for_idle()
        await manager.emit(
            "classification",
            ClassificationData(text="Gracias.", category=Classification.IGNORE_SELF_TALK),
            source="classifier",
        )
        await manager.wait_for_idle()

        # When: se arma el siguiente turno y el prompt estable congelado.
        messages = await voice._messages_for("¿qué sigue?", workflow=None, phase_id=None)
        stable = await voice.build_stable_prompt()

        # Then: la marca viaja en la parte volátil (historial), nunca en el prefijo cacheable.
        assert IGNORED_TRANSCRIPT_PREFIX not in stable
        assert "Gracias." not in stable
        assert IGNORED_TRANSCRIPT_PREFIX not in messages[0].content
        assert any(
            message.role == "user"
            and IGNORED_TRANSCRIPT_PREFIX in message.content
            and "Gracias." in message.content
            for message in messages[1:-1]
        )
        assert messages[-1].content == "¿qué sigue?"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_mark_survives_pydantic_history_filter(tmp_path: Path) -> None:
    # Given: una voz con agente pydantic (mismo patrón de fakes de la suite) y marca en historial.
    voice = _voice(tmp_path, stream=True)
    mock_agent = MagicMock()

    class FakeStreamResult:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def stream_text(self, delta=True):
            yield "ok"

        def get_output(self):
            return "ok"

    mock_agent.run_stream.return_value = FakeStreamResult()
    voice.set_pydantic_agent(mock_agent)
    manager = PluginManager()
    await manager.enable_plugin(voice)
    try:
        await manager.emit("transcription", TranscriptionData(text="Gracias."), source="fixture")
        await manager.wait_for_idle()
        await manager.emit(
            "classification",
            ClassificationData(text="Gracias.", category=Classification.IGNORE_THIRD_PARTY),
            source="classifier",
        )
        await manager.wait_for_idle()

        # When: corre el loop pydantic (filtra history a roles assistant/user).
        await voice._pydantic_agent_loop("siguiente pedido", workflow=None, phase_id=None)

        # Then: la marca con el texto original llega al modelo.
        _, kwargs = mock_agent.run_stream.call_args
        history = kwargs.get("message_history") or []
        texts = [
            getattr(part, "content", "")
            for message in history
            for part in getattr(message, "parts", ())
        ]
        assert any(
            IGNORED_TRANSCRIPT_PREFIX in text and "Gracias." in text for text in texts
        )
        assert kwargs.get("message_history") is not None
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("category", (Classification.IGNORE_SELF_TALK, Classification.IGNORE_THIRD_PARTY))
async def test_ignored_prompt_still_discards_turn(category: Classification) -> None:
    # Given: el gate ya vio el texto ignorado del clasificador.
    manager = PluginManager()
    await manager.enable_plugin(TurnGate())
    gate = manager.get_plugin("turn_gate")
    assert isinstance(gate, TurnGate)
    try:
        # When: ese mismo texto vuelve como prompt de turno.
        await manager.emit(
            "classification",
            ClassificationData(text="Gracias.", category=category),
            source="classifier",
        )
        await manager.wait_for_idle()

        # Then: el turno se sigue descartando (no se perdió el descarte actual).
        assert gate.decide(voice="jane", prompt="Gracias.", origin="external") is Decision.DISCARD
    finally:
        await manager.close()
