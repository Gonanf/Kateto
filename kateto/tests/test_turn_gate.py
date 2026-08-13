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
async def test_decide_queues_when_mixer_busy() -> None:
    # Given: the mixer is mid-playback
    manager, gate = await _with_gate()
    await manager.emit(
        "audio_output_status",
        AudioOutputStatusData(status=AudioOutputStatus.PLAYING),
        source="player",
    )
    await manager.wait_for_idle(timeout=5)
    # Then: an external generate is queued while another voice speaks
    assert gate.decide(voice="jane", prompt="hola", origin="external") is Decision.QUEUE


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
    # Then: jane speaks once more and the queued doktor turn drains afterwards
    assert provider.calls == 2  # type: ignore[attr-defined]
    assert len(doktor._provider.requests) == 1  # type: ignore[attr-defined]


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
async def test_followup_queued_while_mixer_busy_then_executes_when_free() -> None:
    # Given: the mixer is playing another voice's speech
    manager, gate = await _with_gate()
    await manager.emit(
        "audio_output_status",
        AudioOutputStatusData(status=AudioOutputStatus.PLAYING),
        source="player",
    )
    await manager.wait_for_idle(timeout=5)
    # Then: a follow-up attempt cannot take the turn
    assert gate.decide(voice="doktor", prompt="followup", origin="followup") is Decision.QUEUE
    # When: the playback finishes
    await manager.emit(
        "audio_output_status",
        AudioOutputStatusData(status=AudioOutputStatus.IDLE),
        source="player",
    )
    await manager.wait_for_idle(timeout=5)
    # Then: the turn is free again
    assert gate.decide(voice="doktor", prompt="followup", origin="followup") is Decision.EXECUTE