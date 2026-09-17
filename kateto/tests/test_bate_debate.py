from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.event import GenerateData, TextChunk
from kateto.plugins.bate_debate.mock import MockProvider
from kateto.plugins.bate_debate.orchestrator import (
    EventDebateClient,
    _debate_system_prompt,
    run_debate,
    PHASE_OPENING,
    PHASE_ARGUMENT,
    PHASE_OBJECTION,
    PHASE_REBUTTAL,
    PHASE_RULING,
    PHASE_VERDICT,
)


def test_debate_system_prompt_preserves_voice_soul(tmp_path: Path) -> None:
    # Given: a custom SOUL.md in user config
    voice_dir = tmp_path / "voices" / "jane"
    voice_dir.mkdir(parents=True)
    soul_content = "You are Jane. Sarcastic, brilliant and host of FUN department."
    (voice_dir / "SOUL.md").write_text(soul_content, encoding="utf-8")

    # When: building the debate system prompt
    prompt = _debate_system_prompt("jane", config_dir=tmp_path)

    # Then: authentic soul is preserved and oral verbal discussion is specified,
    # NOT contradictory 'juicio escrito no hablando por voz'
    assert "You are Jane" in prompt
    assert "Sarcastic, brilliant" in prompt
    assert "juicio verbal" in prompt
    assert "no hablando por voz" not in prompt


@pytest.mark.asyncio
async def test_run_debate_mock_flow(tmp_path: Path) -> None:
    # Given: mock provider and registry directory
    registry_dir = tmp_path / "registry"
    spoken_turns = []

    def on_speak(voice_id: str, role: str, phase: str, text: str) -> None:
        spoken_turns.append((voice_id, phase, text))

    # When: running one debate round
    records = await run_debate(
        judge="jane",
        debaters=["whisperer", "doktor", "conquest"],
        topic="¿Debería automatizarse la arquitectura?",
        provider_factory=lambda vid: MockProvider(),
        rounds=1,
        registry_dir=registry_dir,
        on_speak=on_speak,
        delay_between_arguments=0.0,
    )

    # Then: debate record contains all phases and written registry
    assert len(records) == 1
    rec = records[0]
    phases = [t.phase for t in rec.turns]
    assert PHASE_OPENING in phases
    assert PHASE_ARGUMENT in phases
    assert PHASE_OBJECTION in phases
    assert PHASE_REBUTTAL in phases
    assert PHASE_RULING in phases
    assert PHASE_VERDICT in phases

    assert rec.verdict.startswith("VEREDICTO FINAL:")
    assert Path(rec.registry_md).is_file()
    assert Path(rec.registry_jsonl).is_file()
    assert len(spoken_turns) > 0

    # Thinking ticks are broadcast to the overlay with empty text (display-only
    # cue) and never recorded as registry turns.
    thinking = [t for t in spoken_turns if t[1] == "thinking"]
    assert len(thinking) > 0
    assert all(t[2] == "" for t in thinking)
    assert all(t.phase != "thinking" for t in rec.turns)


class DummyVoicePlugin(Plugin):
    def __init__(self, name: str) -> None:
        super().__init__(name=name)
        self.interrupted = False

    async def on_generate(self, data: GenerateData) -> None:
        if self.manager is not None:
            await self.manager.emit(
                "text_chunk",
                TextChunk(text="Hola", sequence=0, final=False, voice_id=self.name),
                source=self.name,
            )
            await self.manager.emit(
                "text_chunk",
                TextChunk(text="mundo.", sequence=1, final=True, voice_id=self.name),
                source=self.name,
            )

    async def on_interrupt(self, data) -> None:
        self.interrupted = True


@pytest.mark.asyncio
async def test_event_debate_client_generates_and_interrupts() -> None:
    # Given: a PluginManager with a dummy voice plugin
    manager = PluginManager()
    voice = DummyVoicePlugin("jane")
    manager.register_plugin(voice)
    await manager.enable_plugin(voice)

    client = EventDebateClient(manager)

    # When: generating a turn
    text = await client.generate_turn("jane", "Saludo")

    # Then: streamed chunks are reassembled
    assert text == "Hola mundo."

    # When: emitting an interruption
    await client.interrupt(reason="objection")
    await asyncio.sleep(0.05)

    # Then: voice received the interruption event
    assert voice.interrupted is True

    await manager.close()


def test_anti_echo_and_clean_prefix() -> None:
    from kateto.plugins.bate_debate.orchestrator import _clean_prefix, _is_echo

    # Given: meta-prefix and name-prefix
    raw1 = "Jane: Tengo que defender la postura de que la IA debe regularse."
    cleaned1 = _clean_prefix("Jane", raw1)
    assert cleaned1 == "la IA debe regularse."

    raw2 = "Como facilitador ágil debo decir que el proceso debe ser iterativo."
    cleaned2 = _clean_prefix("Conquest", raw2)
    assert cleaned2 == "el proceso debe ser iterativo."

    # Given: echoed text vs original objection
    objection = "El orador cometió un error grave al asumir metadatos sin verificación técnica previa."
    echoed = "El orador cometió un error grave al asumir metadatos sin verificación técnica previa."
    diff_defense = "Rechazo plenamente esa acusación, la verificación técnica ya está implementada en producción."

    assert _is_echo(echoed, objection) is True
    assert _is_echo(diff_defense, objection) is False


def test_find_interruption_cue() -> None:
    from kateto.plugins.bate_debate.orchestrator import _find_interruption_cue

    sample = (
        'Yo defiendo que Kateto debe abandonar sus prácticas de eficiencia y adoptar una cultura tóxica de "hacerlo tú mismo" para competir. '
        'La competencia actual exige un enfoque agresivo donde la eficiencia se sacrifica para dominar el mercado. '
        'Adoptar esta cultura tóxica permite a Kateto diferenciarse y ganar cuota de mercado frente a competidores más tradicionales.'
    )
    cut_text, duration = _find_interruption_cue(sample, target_ratio=0.70)
    assert cut_text.endswith(" —")
    assert "Yo defiendo que Kateto" in cut_text
    assert "dominar el mercado" in cut_text
    assert duration >= 5.0
    assert len(cut_text.split()) < len(sample.split())


@pytest.mark.asyncio
async def test_pace_applies_delay_without_waiting_for_playback() -> None:
    # Data-lane model: the orchestrator never waits on TTS/playback between
    # turns — the player's lane sequencer guarantees audio ordering. Pacing is
    # a pure optional sleep.
    from kateto.plugins.bate_debate.orchestrator import _AsyncDebate

    class MockPlayer:
        name = "audio_output_player"
        enabled = True
        _playing = True  # never goes idle

        async def wait_idle(self, timeout: float | None = None) -> bool:
            while self._playing:
                await asyncio.sleep(0.02)
            return True

    class MockManager:
        def __init__(self):
            self.player = MockPlayer()

        def get_plugin(self, name):
            if name == "audio_output_player":
                return self.player
            return None

    mgr = MockManager()
    engine = _AsyncDebate(
        judge="jane",
        debaters=["whisperer", "doktor"],
        provider_factory=lambda vid: None,
        manager=mgr,
        rng=__import__("random").Random(7),
        delay_between_arguments=0.05,
    )

    # When: the player is still playing and we pace between turns
    t0 = asyncio.get_running_loop().time()
    await engine._pace()
    elapsed = asyncio.get_running_loop().time() - t0

    # Then: _pace returns after the optional delay WITHOUT waiting for the
    # still-playing player (the next turn's generation pipelines behind it).
    assert 0.04 <= elapsed < 0.2


@pytest.mark.asyncio
async def test_emit_waits_until_voice_is_actually_playing() -> None:
    # Data-lane model: text is broadcast when the voice's lane reaches the
    # device, not when generation finishes — subtitles no longer lead audio.
    from kateto.plugins.bate_debate.orchestrator import _AsyncDebate

    class SyncPlayer:
        name = "audio_output_player"
        enabled = True
        is_busy = True
        _pipeline_queues = {"jane": asyncio.Queue()}
        _playing_speaker = "jane"

    class MockManager:
        def __init__(self):
            self.player = SyncPlayer()

        def get_plugin(self, name):
            if name == "audio_output_player":
                return self.player
            return None

    mgr = MockManager()
    engine = _AsyncDebate(
        judge="jane",
        debaters=["whisperer", "doktor"],
        provider_factory=lambda vid: None,
        manager=mgr,
        rng=__import__("random").Random(3),
    )

    spoken: list[tuple[str, str]] = []
    engine.on_speak = lambda voice_id, role, phase, text: spoken.append((voice_id, phase))

    # When: doktor's text is ready but jane's lane is still playing; doktor's
    # lane reaches the device 0.1s later.
    async def _become_head():
        await asyncio.sleep(0.1)
        mgr.player._playing_speaker = "doktor"

    task = asyncio.create_task(_become_head())
    t0 = asyncio.get_running_loop().time()
    await engine._emit("doktor", "argument", "texto de prueba")
    elapsed = asyncio.get_running_loop().time() - t0
    await task

    # Then: the speak broadcast waited for doktor to be the audible speaker
    assert elapsed >= 0.1
    assert spoken == [("doktor", "argument")]


