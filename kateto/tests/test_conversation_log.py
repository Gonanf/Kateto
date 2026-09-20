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
        assert set(rec) == {"ts", "epoch", "event", "source", "voice", "text", "extra"}
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
