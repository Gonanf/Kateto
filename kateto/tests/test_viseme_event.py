from unittest.mock import AsyncMock, MagicMock

import pydantic
import pytest

from kateto.core.config import PluginSettings
from kateto.core.event import VisemeData
from kateto.plugins.audio_output.player import AudioOutputPlayer


def test_viseme_data_defaults():
    # Given: no se pasan argumentos
    # When: se construye VisemeData
    data = VisemeData()
    # Then: defaults neutros
    assert data.rms == 0.0
    assert data.sequence == 0
    assert data.is_speaking is False
    assert data.timestamp_us == 0


def test_viseme_data_validation():
    # Given: rms fuera de rango
    # When: se construye
    # Then: ValidationError (le=1.0)
    with pytest.raises(pydantic.ValidationError):
        VisemeData(rms=1.5)
    # Given: sequence negativa
    # Then: ValidationError (ge=0)
    with pytest.raises(pydantic.ValidationError):
        VisemeData(sequence=-1)


def test_viseme_data_frozen():
    # Given: una instancia válida
    data = VisemeData(rms=0.5)
    # When: se intenta mutar
    # Then: frozen lanza
    with pytest.raises(pydantic.ValidationError):
        data.rms = 0.9


def _make_player() -> AudioOutputPlayer:
    player = AudioOutputPlayer(settings=PluginSettings(device=None), player_factory=MagicMock())
    player.manager = MagicMock()
    player.manager.emit = AsyncMock()
    player.manager.get_plugin = MagicMock(return_value=None)
    return player


@pytest.mark.asyncio
async def test_send_viseme_emits_event():
    # Given: un player con manager mock
    player = _make_player()
    # When: se envía un viseme
    await player._send_viseme("jane", 0.5, None, audio_ms=10.0)
    # Then: emite una vez por el bus
    player.manager.emit.assert_awaited_once()
    name, payload = player.manager.emit.await_args.args
    assert name == "viseme"
    assert isinstance(payload, VisemeData)
    assert payload.voice_id == "jane"
    assert payload.is_speaking is True
    assert payload.jaw_offset_y < 0
    assert payload.jaw_rotation > 0
    assert payload.sequence == 1
    assert payload.timestamp_us > 0


@pytest.mark.asyncio
async def test_send_viseme_sequence_increments():
    # Given: un player ya emitió una vez
    player = _make_player()
    await player._send_viseme("jane", 0.5, None, audio_ms=1.0)
    # When: emite de nuevo
    await player._send_viseme("jane", 0.6, None, audio_ms=2.0)
    # Then: la secuencia avanza
    payload = player.manager.emit.await_args.args[1]
    assert payload.sequence == 2


@pytest.mark.asyncio
async def test_send_viseme_emit_failure_is_swallowed():
    # Given: un manager cuyo emit explota
    player = _make_player()
    player.manager.emit = AsyncMock(side_effect=RuntimeError("boom"))
    # When: se envía un viseme
    # Then: no propaga la excepción
    await player._send_viseme("jane", 0.5, None, audio_ms=1.0)
