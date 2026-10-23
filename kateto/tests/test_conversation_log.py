from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from kateto.core.event import (
    ClassificationData,
    PluginErrorData,
    TextChunk,
    ToolCallData,
    ToolResultData,
    TranscriptionData,
    VoiceIdleData,
)
from kateto.core.manager import PluginManager
from kateto.plugins.executor.conversation_log import ConversationLogPlugin


def _read_lines(log_dir: Path) -> list[dict]:
    files = sorted(log_dir.glob("session-*.jsonl"))
    assert len(files) == 1, f"expected exactly one session log, got {files}"
    lines = files[0].read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


async def _enable(tmp_path: Path) -> tuple[PluginManager, ConversationLogPlugin]:
    manager = PluginManager()
    plugin = ConversationLogPlugin(config_dir=tmp_path)
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()
    return manager, plugin


@pytest.mark.asyncio
async def test_transcription_writes_user_turn(tmp_path):
    # Given: an enabled conversation_log plugin writing to tmp_path
    manager, plugin = await _enable(tmp_path)
    # When: a transcription arrives
    await manager.emit(
        "transcription",
        TranscriptionData(text="hola mundo", language="es", confidence=0.9, duration_ms=1200),
        source="whisper",
    )
    await manager.wait_for_idle()
    # Then: exactly one user_turn line with the text and extra fields
    records = _read_lines(tmp_path / "logs")
    assert len(records) == 1
    rec = records[0]
    assert rec["event"] == "user_turn"
    assert rec["text"] == "hola mundo"
    assert rec["source"] == "whisper"
    assert rec["extra"]["language"] == "es"
    assert rec["extra"]["confidence"] == 0.9
    assert rec["extra"]["duration_ms"] == 1200
    assert rec["ts"].startswith(str(date.today()))
    await manager.disable_plugin(plugin.name)


@pytest.mark.asyncio
async def test_text_chunk_final_writes_voice_turn(tmp_path):
    manager, plugin = await _enable(tmp_path)
    await manager.emit(
        "text_chunk",
        TextChunk(text="listo", sequence=0, final=True, voice_id="jane"),
        source="jane",
    )
    await manager.wait_for_idle()
    records = _read_lines(tmp_path / "logs")
    assert len(records) == 1
    rec = records[0]
    assert rec["event"] == "voice_turn"
    assert rec["text"] == "listo"
    assert rec["voice"] == "jane"
    await manager.disable_plugin(plugin.name)


@pytest.mark.asyncio
async def test_text_chunk_partial_not_logged(tmp_path):
    manager, plugin = await _enable(tmp_path)
    # When: only partial chunks arrive
    await manager.emit(
        "text_chunk",
        TextChunk(text="lis", sequence=0, final=False, voice_id="jane"),
        source="jane",
    )
    await manager.wait_for_idle()
    # Then: nothing is written
    assert list((tmp_path / "logs").glob("session-*.jsonl")) == []
    await manager.disable_plugin(plugin.name)


@pytest.mark.asyncio
async def test_classification_writes_classifier_line(tmp_path):
    manager, plugin = await _enable(tmp_path)
    await manager.emit(
        "classification",
        ClassificationData(text="arma el backlog", category="EXECUTE", confidence=0.87, voice="doktor"),
        source="executor_classifier",
    )
    await manager.wait_for_idle()
    records = _read_lines(tmp_path / "logs")
    assert len(records) == 1
    rec = records[0]
    assert rec["event"] == "classifier"
    assert rec["extra"]["category"] == "EXECUTE"
    assert rec["extra"]["confidence"] == 0.87
    await manager.disable_plugin(plugin.name)



@pytest.mark.asyncio
async def test_tool_call_and_result_logged(tmp_path):
    manager, plugin = await _enable(tmp_path)
    await manager.emit(
        "tool_call",
        ToolCallData(tool_name="todo_add", arguments={"task": "x"}, correlation_id="c1", voice="jane"),
        source="jane",
    )
    await manager.emit(
        "tool_result",
        ToolResultData(correlation_id="c1", tool_name="todo_add", result="ok", voice="jane"),
        source="jane",
    )
    await manager.wait_for_idle()
    records = _read_lines(tmp_path / "logs")
    assert [r["event"] for r in records] == ["tool_call", "tool_result"]
    assert records[0]["extra"]["tool"] == "todo_add"
    assert records[0]["extra"]["arguments"] == {"task": "x"}
    assert records[1]["extra"]["ok"] is True
    await manager.disable_plugin(plugin.name)


@pytest.mark.asyncio
async def test_error_logged(tmp_path):
    manager, plugin = await _enable(tmp_path)
    await manager.emit(
        "error",
        PluginErrorData(plugin="broken", event_name="transcription", error_type="ValueError", message="boom"),
        source="broken",
    )
    await manager.wait_for_idle()
    records = _read_lines(tmp_path / "logs")
    assert len(records) == 1
    rec = records[0]
    assert rec["event"] == "error"
    assert rec["extra"]["plugin"] == "broken"
    assert rec["extra"]["error_type"] == "ValueError"
    await manager.disable_plugin(plugin.name)


@pytest.mark.asyncio
async def test_weird_object_does_not_explode(tmp_path):
    manager, plugin = await _enable(tmp_path)
    # When: a handler receives an object without `.text`
    await plugin.on_transcription(object(), None)
    # Then: no crash and no garbage line written
    assert list((tmp_path / "logs").glob("session-*.jsonl")) == []


@pytest.mark.asyncio
async def test_all_lines_parse_as_json(tmp_path):
    manager, plugin = await _enable(tmp_path)
    await manager.emit(
        "transcription",
        TranscriptionData(text="con\nsaltos\ny tildes: ñáéí", language="es"),
        source="whisper",
    )
    await manager.emit(
        "text_chunk",
        TextChunk(text='respuesta con "comillas" y {llaves}', sequence=1, final=True, voice_id="doktor"),
        source="doktor",
    )
    await manager.wait_for_idle()
    records = _read_lines(tmp_path / "logs")
    assert len(records) == 2
    for rec in records:
        assert set(rec) == {"ts", "epoch", "session_id", "turn_id", "event", "source", "voice", "text", "extra"}
        assert "\n" not in rec["text"]
    await manager.disable_plugin(plugin.name)


@pytest.mark.asyncio
async def test_write_failure_never_raises(tmp_path):
    # Given: an enabled plugin whose logs dir is a file (unwritable)
    manager = PluginManager()
    plugin = ConversationLogPlugin(config_dir=tmp_path)
    (tmp_path / "logs").write_text("not a dir", encoding="utf-8")
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()
    # When: events flow through the broken sink
    await manager.emit("transcription", TranscriptionData(text="hola"), source="whisper")
    # Then: the bus stays up and the plugin is not disabled
    assert plugin.enabled
    await manager.disable_plugin(plugin.name)


@pytest.mark.asyncio
async def test_partial_transcription_does_not_open_turn_and_not_input(tmp_path):
    # Given: an enabled conversation_log plugin
    manager, plugin = await _enable(tmp_path)
    # When: a partial transcription arrives
    await manager.emit(
        "transcription",
        TranscriptionData(text="hola par...", language="es", partial=True),
        source="whisper",
    )
    await manager.wait_for_idle()
    # Then: logged as user_turn_partial with extra.partial=True and no turn opened
    records = _read_lines(tmp_path / "logs")
    assert len(records) == 1
    assert records[0]["event"] == "user_turn_partial"
    assert records[0]["extra"]["partial"] is True
    assert plugin._current_turn_id is None
    await manager.disable_plugin(plugin.name)


@pytest.mark.asyncio
async def test_consecutive_final_transcriptions_do_not_mix_turns(tmp_path):
    manager, plugin = await _enable(tmp_path)
    # When: two consecutive final transcriptions arrive
    await manager.emit("transcription", TranscriptionData(text="primero"), source="whisper")
    await manager.wait_for_idle()
    await manager.emit("transcription", TranscriptionData(text="segundo"), source="whisper")
    await manager.wait_for_idle()

    # Then: turn 1 closes with closed_by="next_transcription" and turn 2 has distinct turn_id
    records = _read_lines(tmp_path / "logs")
    assert len(records) == 3
    assert records[0]["event"] == "user_turn"
    assert records[0]["text"] == "primero"
    turn1_id = records[0]["turn_id"]

    assert records[1]["event"] == "turn_end"
    assert records[1]["turn_id"] == turn1_id
    assert records[1]["closed_by"] == "next_transcription"
    assert records[1]["input"] == "primero"

    assert records[2]["event"] == "user_turn"
    assert records[2]["text"] == "segundo"
    turn2_id = records[2]["turn_id"]
    assert turn1_id != turn2_id
    await manager.disable_plugin(plugin.name)


@pytest.mark.asyncio
async def test_multi_voice_marks_ambiguous(tmp_path):
    manager, plugin = await _enable(tmp_path)
    # Given: a user turn
    await manager.emit("transcription", TranscriptionData(text="pregunta a dos"), source="whisper")
    # When: multiple voices answer
    await manager.emit(
        "text_chunk",
        TextChunk(text="respuesta uno", sequence=0, final=True, voice_id="jane"),
        source="jane",
    )
    await manager.emit(
        "text_chunk",
        TextChunk(text="respuesta dos", sequence=0, final=True, voice_id="doktor"),
        source="doktor",
    )
    # And both voices report idle
    await manager.emit("voice_idle", VoiceIdleData(voice="jane"), source="jane")
    await manager.emit("voice_idle", VoiceIdleData(voice="doktor"), source="doktor")
    await manager.wait_for_idle()

    # Then: turn closes as ambiguous with ambiguity=["multi_voice"]
    records = _read_lines(tmp_path / "logs")
    assert len(records) == 4
    end_rec = records[3]
    assert end_rec["event"] == "turn_end"
    assert end_rec["closed_by"] == "voice_idle"
    assert end_rec["ambiguous"] is True
    assert end_rec["ambiguity"] == ["multi_voice"]
    assert len(end_rec["outputs"]) == 2
    await manager.disable_plugin(plugin.name)


@pytest.mark.asyncio
async def test_dept_sherut_writes_no_lines(tmp_path):
    manager, plugin = await _enable(tmp_path)
    # When: event arrives with dept="sherut"
    await manager.emit(
        "transcription",
        TranscriptionData(text="secreto de cliente"),
        source="whisper",
        dept="sherut",
    )
    await manager.wait_for_idle()

    # And with casefold match
    await manager.emit(
        "transcription",
        TranscriptionData(text="otro secreto"),
        source="whisper",
        dept="WorkMatch",
    )
    await manager.wait_for_idle()

    # Then: no lines written at all
    log_files = list((tmp_path / "logs").glob("session-*.jsonl"))
    if log_files:
        assert log_files[0].read_text().strip() == ""
    else:
        assert True
    await manager.disable_plugin(plugin.name)


@pytest.mark.asyncio
async def test_long_text_5000_chars_arrives_complete_in_turn_end(tmp_path):
    manager, plugin = await _enable(tmp_path)
    long_input = "a" * 5000
    long_output = "b" * 5000
    await manager.emit("transcription", TranscriptionData(text=long_input), source="whisper")
    await manager.emit(
        "text_chunk",
        TextChunk(text=long_output, sequence=0, final=True, voice_id="jane"),
        source="jane",
    )
    await manager.emit("voice_idle", VoiceIdleData(voice="jane"), source="jane")
    await manager.wait_for_idle()

    records = _read_lines(tmp_path / "logs")
    assert len(records) == 3
    user_turn, voice_turn, turn_end = records[0], records[1], records[2]

    # Event lines are capped at 4000 and marked truncated
    assert len(user_turn["text"]) == 4000
    assert user_turn["extra"]["truncated"] is True
    assert len(voice_turn["text"]) == 4000
    assert voice_turn["extra"]["truncated"] is True

    # turn_end is NOT truncated
    assert turn_end["event"] == "turn_end"
    assert turn_end["input"] == long_input
    assert len(turn_end["input"]) == 5000
    assert turn_end["outputs"][0]["text"] == long_output
    assert len(turn_end["outputs"][0]["text"]) == 5000
    await manager.disable_plugin(plugin.name)
