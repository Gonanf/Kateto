from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from kateto.core import PluginManager
from kateto.core.event import (
    AudioOutputStatus,
    AudioOutputStatusData,
    Classification,
    ClassificationData,
    GenerateData,
    InterruptData,
)
from kateto.core.plugin import Plugin
from kateto.plugins.system.turn_gate import Decision, TurnGate
from kateto.voices.base import VoiceAgent

from kateto.tests.conversation_support import (
    BlockingFixtureProvider,
    StreamingFixtureProvider,
    write_references,
)


async def _with_gate() -> tuple[PluginManager, TurnGate]:
    manager = PluginManager()
    await manager.enable_plugin(TurnGate())
    gate = manager.get_plugin("turn_gate")
    assert isinstance(gate, TurnGate)
    return manager, gate


class _DrainRecorder(Plugin):
    """Test-only sink named like a voice so targeted drains reach it."""

    def __init__(self) -> None:
        super().__init__("doktor")
        self.seen: list[str] = []

    async def initialize(self) -> None:
        self.required_manager.register_event("generate", GenerateData)

    async def on_generate(self, data: GenerateData) -> None:
        self.seen.append(data.prompt or "")


@pytest.mark.asyncio
async def test_user_interrupt_drops_queued_turns_and_nothing_drains() -> None:
    # Given: gate holding jane's turn with 2 queued turns + a drain recorder
    manager, gate = await _with_gate()
    recorder = _DrainRecorder()
    await manager.enable_plugin(recorder)
    assert gate.decide(voice="jane", prompt="first", origin="external") is Decision.EXECUTE
    gate.enqueue(event="generate", data=GenerateData(prompt="second"), target="jane")
    gate.enqueue(event="generate", data=GenerateData(prompt="third"), target="jane")
    assert len(gate._pending) == 2
    # When: the user barges in
    await manager.emit("interrupt", InterruptData(reason="voice_activity"), source="vad")
    await manager.wait_for_idle(timeout=5)
    # Then: the queue is flushed...
    assert not gate._pending
    # ...and a later idle drain emits nothing
    await manager.emit(
        "audio_output_status",
        AudioOutputStatusData(status=AudioOutputStatus.IDLE),
        source="player",
    )
    await manager.wait_for_idle(timeout=5)
    assert not gate._pending
    assert recorder.seen == []


@pytest.mark.asyncio
async def test_non_user_interrupt_keeps_queue_and_drains_as_followup() -> None:
    # Given: gate holding jane's turn with 1 queued turn + a drain recorder
    manager, gate = await _with_gate()
    recorder = _DrainRecorder()
    await manager.enable_plugin(recorder)
    assert gate.decide(voice="jane", prompt="first", origin="external") is Decision.EXECUTE
    gate.enqueue(event="generate", data=GenerateData(prompt="segunda"), target="doktor")
    # When: a non-user (inter-voice) interrupt arrives
    await manager.emit(
        "interrupt", InterruptData(reason="handoff", dept="planning"), source="doktor"
    )
    await manager.wait_for_idle(timeout=5)
    # Then: the queue survives...
    assert len(gate._pending) == 1
    # ...and drains once a new user turn executes and the voice goes idle
    assert gate.decide(voice="jane", prompt="nueva", origin="external") is Decision.EXECUTE
    gate.release("jane")
    await manager.emit(
        "audio_output_status",
        AudioOutputStatusData(status=AudioOutputStatus.IDLE),
        source="player",
    )
    await manager.wait_for_idle(timeout=5)
    assert recorder.seen == ["segunda"]


@pytest.mark.asyncio
async def test_new_user_generate_executes_after_user_interrupt_flush() -> None:
    # Given: gate with a queued turn flushed by a user interrupt
    manager, gate = await _with_gate()
    assert gate.decide(voice="jane", prompt="first", origin="external") is Decision.EXECUTE
    gate.enqueue(event="generate", data=GenerateData(prompt="second"), target="jane")
    await manager.emit("interrupt", InterruptData(reason="user_turn"), source="listener")
    await manager.wait_for_idle(timeout=5)
    assert not gate._pending
    # Then: a fresh user turn executes (not stuck behind _steering)
    assert gate.decide(voice="jane", prompt="nueva", origin="external") is Decision.EXECUTE


@pytest.mark.asyncio
async def test_decide_external_claims_turn_then_closed_turn_discards_duplicate() -> None:
    # Given: a fresh gate
    _manager, gate = await _with_gate()
    # When: a first external prompt claims the turn
    assert gate.decide(voice="jane", prompt="hola", origin="external") is Decision.EXECUTE
    # Then: the same prompt while the turn is in flight is discarded (one response)
    assert gate.decide(voice="jane", prompt="hola", origin="external") is Decision.DISCARD


@pytest.mark.asyncio
async def test_decide_external_queues_different_prompt_while_turn_in_flight() -> None:
    # Given: jane holds a turn
    _manager, gate = await _with_gate()
    assert gate.decide(voice="jane", prompt="first", origin="external") is Decision.EXECUTE
    # When: a different external prompt arrives while jane still holds the turn
    # Then: it is queued as steering, not executed (no overlapping response)
    assert gate.decide(voice="jane", prompt="second", origin="external") is Decision.QUEUE


@pytest.mark.asyncio
async def test_decide_executes_while_mixer_busy() -> None:
    # Given: the mixer is mid-playback (another voice's lane is yielding)
    manager, gate = await _with_gate()
    await manager.emit(
        "audio_output_status",
        AudioOutputStatusData(status=AudioOutputStatus.PLAYING),
        source="player",
    )
    await manager.wait_for_idle(timeout=5)
    # Then: generation is NOT gated on playback (data-lane model): the voice
    # generates immediately and the player serializes its lane at the device.
    assert gate.decide(voice="jane", prompt="hola", origin="external") is Decision.EXECUTE


@pytest.mark.asyncio
async def test_decide_discards_vad_noise_classified_as_self_talk() -> None:
    # Given: the classifier already tagged this utterance as self-talk
    manager, gate = await _with_gate()
    await manager.emit(
        "classification",
        ClassificationData(text="murmullo", category=Classification.IGNORE_SELF_TALK),
        source="classifier",
    )
    await manager.wait_for_idle(timeout=5)
    # Then: the gate refuses to call the LLM for it
    assert gate.decide(voice="jane", prompt="murmullo", origin="external") is Decision.DISCARD


async def _enable_two_voices(
    manager: PluginManager, config_dir: Path
) -> tuple[VoiceAgent, VoiceAgent]:
    write_references(config_dir)
    from kateto.voices.factory import _PROFILES

    jane = VoiceAgent(
        profile=_PROFILES["jane"],
        config_dir=config_dir,
        provider=BlockingFixtureProvider(),
    )
    doktor = VoiceAgent(
        profile=_PROFILES["doktor"],
        config_dir=config_dir,
        provider=StreamingFixtureProvider(),
    )
    for voice in (jane, doktor):
        await manager.enable_plugin(voice)
    return jane, doktor


@pytest.mark.asyncio
async def test_two_generates_same_voice_produce_single_response(tmp_path: Path) -> None:
    # Given: gate + two voices, jane streaming a blocking generation
    manager, _gate = await _with_gate()
    jane, doktor = await _enable_two_voices(manager, tmp_path)
    await manager.emit(
        "generate",
        GenerateData(prompt="primera tarea"),
        source="classifier",
        target="jane",
    )
    provider = jane._provider  # type: ignore[attr-defined]
    await provider.blocked.wait()  # type: ignore[attr-defined]
    # When: a second generate for the same voice arrives while the first streams
    await manager.emit(
        "generate",
        GenerateData(prompt="primera tarea"),
        source="classifier",
        target="jane",
    )
    await asyncio.sleep(0.05)
    # Then: only the first generation touched the LLM (duplicate discarded)
    assert provider.calls == 1  # type: ignore[attr-defined]
    assert len(doktor._provider.requests) == 0  # type: ignore[attr-defined]
    await manager.emit("interrupt", InterruptData(reason="voice_activity"), source="vad")
    await manager.wait_for_idle(timeout=5)


@pytest.mark.asyncio
async def test_two_generates_different_voices_queue_second_turn(tmp_path: Path) -> None:
    # Given: gate + two voices, jane streaming a blocking generation
    manager, _gate = await _with_gate()
    jane, doktor = await _enable_two_voices(manager, tmp_path)
    await manager.emit(
        "generate",
        GenerateData(prompt="primera tarea"),
        source="classifier",
        target="jane",
    )
    provider = jane._provider  # type: ignore[attr-defined]
    await provider.blocked.wait()  # type: ignore[attr-defined]
    # When: a generate for the other voice arrives while jane holds the turn
    await manager.emit(
        "generate",
        GenerateData(prompt="segunda tarea"),
        source="classifier",
        target="doktor",
    )
    # Then: doktor's turn queued as follow-up, no LLM call while jane speaks
    for _ in range(50):
        if _gate._pending:
            break
        await asyncio.sleep(0.01)
    assert _gate._pending, "expected doktor's turn to be queued"
    assert len(doktor._provider.requests) == 0  # type: ignore[attr-defined]
    # When: the user interrupts jane's stream, then routes a new generate to jane
    await manager.emit("interrupt", InterruptData(reason="voice_activity"), source="vad")
    await manager.emit(
        "generate",
        GenerateData(prompt="nueva tarea"),
        source="classifier",
        target="jane",
    )
    await manager.wait_for_idle(timeout=5)
    # Then: jane speaks once more, but the user interrupt dropped the queued
    # doktor turn (bug 108: queued turns are discarded on user barge-in),
    # so it is NOT answered afterwards
    assert provider.calls == 2  # type: ignore[attr-defined]
    assert len(doktor._provider.requests) == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_interrupt_cancels_generation_mid_stream(tmp_path: Path) -> None:
    # Given: gate + jane mid-generation (blocking provider)
    manager, _gate = await _with_gate()
    (jane, _doktor) = await _enable_two_voices(manager, tmp_path)
    await manager.emit(
        "generate",
        GenerateData(prompt="tarea larga"),
        source="classifier",
        target="jane",
    )
    provider = jane._provider  # type: ignore[attr-defined]
    await provider.blocked.wait()  # type: ignore[attr-defined]
    # When: the user interrupts mid-stream
    await manager.emit("interrupt", InterruptData(reason="voice_activity"), source="vad")
    # Then: the generation is cancelled (provider observes the cancellation)
    await manager.wait_for_idle(timeout=5)
    assert provider.cancelled.is_set()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_followup_executes_while_mixer_busy_but_queues_while_turn_held() -> None:
    # Given: the mixer is playing another voice's speech
    manager, gate = await _with_gate()
    await manager.emit(
        "audio_output_status",
        AudioOutputStatusData(status=AudioOutputStatus.PLAYING),
        source="player",
    )
    await manager.wait_for_idle(timeout=5)
    # Then: playback no longer blocks generation (data-lane model) — the
    # follow-up claims the turn and its lane queues at the player.
    assert gate.decide(voice="doktor", prompt="followup", origin="followup") is Decision.EXECUTE
    # When: another voice tries to follow up while doktor holds the turn
    gate.release("doktor")
    assert gate.decide(voice="jane", prompt="first", origin="external") is Decision.EXECUTE
    # Then: the follow-up is queued until the active turn is released
    assert gate.decide(voice="doktor", prompt="followup", origin="followup") is Decision.QUEUE
    gate.release("jane")
    assert gate.decide(voice="doktor", prompt="followup", origin="followup") is Decision.EXECUTE