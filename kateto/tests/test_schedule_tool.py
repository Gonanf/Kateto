import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from kateto.core.event import ScheduleRequestData, ScheduleType
from kateto.core.manager import PluginManager
from kateto.providers.agent import HermesProvider
from kateto.voices.tools import VoiceToolExecutor


@pytest.mark.asyncio
async def test_schedule_event_tool_emits_request(tmp_path):
    manager = MagicMock(spec=PluginManager)
    manager.emit = AsyncMock()

    executor = VoiceToolExecutor(
        config_dir=tmp_path,
        manager=manager,
        voice_name="jane",
    )

    args = {
        "event_name": "backup_db",
        "delay": 30,
        "target_voice": "doktor",
        "dept": "management",
    }
    result_raw = await executor.execute("schedule_event", args)
    result = json.loads(result_raw)

    assert result.get("status") == "scheduled"
    assert result.get("event_name") == "backup_db"
    assert "job_id" in result

    manager.emit.assert_called_once()
    event_name, data = manager.emit.call_args[0][:2]
    assert event_name == "schedule_request"
    assert isinstance(data, ScheduleRequestData)
    assert data.event_name == "backup_db"
    assert data.schedule_type == ScheduleType.ONE_SHOT
    assert data.expression == "30s"
    assert data.target_voice == "doktor"
    assert data.dept == "management"


@pytest.mark.asyncio
async def test_schedule_event_tool_disabled_when_flag_set(tmp_path):
    manager = MagicMock(spec=PluginManager)
    manager.emit = AsyncMock()

    executor = VoiceToolExecutor(
        config_dir=tmp_path,
        manager=manager,
        voice_name="jane",
        disable_scheduling_tools=True,
    )

    result_raw = await executor.execute("schedule_event", {"event_name": "test_event"})
    result = json.loads(result_raw)

    assert "error" in result
    assert result["error"] == "scheduling tools are disabled"
    manager.emit.assert_not_called()


@pytest.mark.asyncio
async def test_hermes_provider_manage_tools_false_omits_tools():
    provider = HermesProvider(
        conversation_id="conv_123",
        model="gpt-4o",
        endpoint="http://localhost:8000/v1",
        api_key="sk-test",
        manage_tools=False,
    )

    mock_create = AsyncMock()
    mock_choice = MagicMock()
    mock_choice.message = MagicMock(content="Hello from Hermes", tool_calls=None)
    mock_response = MagicMock(choices=[mock_choice])
    mock_create.return_value = mock_response

    provider._client.chat.completions.create = mock_create

    dummy_tool = {
        "type": "function",
        "function": {"name": "schedule_event", "description": "test", "parameters": {}},
    }

    res = await provider.chat_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        tools=(dummy_tool,),
    )

    assert res.text == "Hello from Hermes"
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert "tools" not in call_kwargs
    assert call_kwargs["extra_body"] == {"conversation_id": "conv_123"}
