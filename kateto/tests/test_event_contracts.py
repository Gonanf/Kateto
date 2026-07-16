from datetime import datetime, timezone
from importlib import import_module

import pytest
from pydantic import BaseModel, ValidationError

from kateto.core.event import (
    AudioData,
    AudioOutput,
    Classification,
    ClassificationData,
    EventEnvelope,
    TextChunk,
    TranscriptionData,
)


def test_envelope_generates_utc_timestamp_and_round_trips_json() -> None:
    data = TranscriptionData(text="hello", language="en")

    envelope = EventEnvelope[TranscriptionData](
        name="transcription",
        data=data,
        source="audio_processor_whisper",
    )

    assert envelope.timestamp.tzinfo == timezone.utc
    assert abs((datetime.now(timezone.utc) - envelope.timestamp).total_seconds()) < 2
    restored = EventEnvelope[TranscriptionData].model_validate_json(
        envelope.model_dump_json(),
    )
    assert restored == envelope
    assert restored.data.text == "hello"


def test_event_payloads_are_pydantic_models() -> None:
    payloads = (
        AudioData(samples=b"pcm", sample_rate=16_000, channels=1),
        TranscriptionData(text="hello"),
        ClassificationData(text="hello", category=Classification.EXECUTE),
        TextChunk(text="hello", sequence=0, final=True),
        AudioOutput(samples=b"pcm", sample_rate=16_000, channels=1),
    )

    assert all(isinstance(payload, BaseModel) for payload in payloads)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (AudioData, {"samples": "not-bytes", "sample_rate": 16_000, "channels": 1}),
        (TranscriptionData, {"text": "hello", "unexpected": True}),
        (ClassificationData, {"text": "hello", "category": "UNKNOWN"}),
        (TextChunk, {"text": "hello", "sequence": -1}),
        (EventEnvelope[TranscriptionData], {
            "name": "transcription",
            "data": {"text": "hello"},
            "source": "",
        }),
    ],
)
def test_malformed_contract_input_is_rejected(model: type[BaseModel], payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_fixture_missing_text_reaches_pydantic_validation(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.argv", ["emit_fixture", "transcription"])
    fixture = import_module("kateto.qa.emit_fixture")

    assert fixture.main() != 0
    captured = capsys.readouterr()
    assert "ValidationError" in captured.err
    assert not any(line.startswith("{") for line in captured.out.splitlines())
