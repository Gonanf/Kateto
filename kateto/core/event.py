from datetime import datetime, timezone
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Classification(StrEnum):
    EXECUTE = "EXECUTE"
    IGNORE_SELF_TALK = "IGNORE_SELF_TALK"
    IGNORE_THIRD_PARTY = "IGNORE_THIRD_PARTY"


class BacklogPriority(StrEnum):
    MUST = "Must"
    SHOULD = "Should"
    COULD = "Could"
    WONT = "Won't"


class BacklogStatus(StrEnum):
    BACKLOG = "Backlog"
    READY = "Ready"
    IN_SPRINT = "In Sprint"
    DONE = "Done"


class AudioData(EventModel):
    samples: bytes
    sample_rate: int = Field(default=16_000, gt=0)
    channels: int = Field(default=1, gt=0)
    format: str = "wav"
    source: str = ""
    duration_ms: float = Field(default=0.0, ge=0.0)


class TranscriptionData(EventModel):
    text: str = Field(min_length=1)
    language: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    duration_ms: float | None = Field(default=None, ge=0.0)


class ClassificationData(EventModel):
    text: str = Field(min_length=1)
    category: Classification
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("category", mode="before")
    @classmethod
    def parse_category(cls, value: Classification | str) -> Classification:
        return Classification(value)


class TextChunk(EventModel):
    text: str
    sequence: int = Field(ge=0)
    final: bool = False
    voice_id: str | None = None


class AudioOutput(EventModel):
    samples: bytes
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0)
    format: str = "wav"
    voice_id: str | None = None
    sequence: int = Field(default=0, ge=0)
    final: bool = False


class AudioInputStatus(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"


class AudioInputStatusData(EventModel):
    status: AudioInputStatus


class AudioOutputStatus(StrEnum):
    IDLE = "idle"
    PLAYING = "playing"


class AudioOutputStatusData(EventModel):
    status: AudioOutputStatus


class InterruptData(EventModel):
    reason: str = "voice_activity"


class PluginErrorData(EventModel):
    plugin: str = Field(min_length=1)
    event_name: str = Field(min_length=1)
    error_type: str = Field(min_length=1)
    message: str


class GenerateData(EventModel):
    prompt: str | None = None


class VoiceIdleData(EventModel):
    voice: str


class TodoItemData(EventModel):
    voice: str = Field(min_length=1)
    task: str = Field(min_length=1)
    completed: bool = False


class WorkflowRunData(EventModel):
    workflow: str = Field(min_length=1)
    voice: str = Field(min_length=1)
    context: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class WorkflowStartedData(EventModel):
    workflow: str = Field(min_length=1)
    voice: str = Field(min_length=1)
    context: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class WorkflowCheckpointResult(EventModel):
    checkpoint: str = Field(min_length=1)
    passed: bool


class WorkflowStopData(EventModel):
    workflow: str = Field(min_length=1)
    voice: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class WorkflowPhaseStartData(EventModel):
    workflow: str = Field(min_length=1)
    phase_id: str = Field(min_length=1)
    voice: str = Field(min_length=1)
    instructions: list[str] = Field(default_factory=list)


class WorkflowPhaseCompleteData(EventModel):
    workflow: str = Field(min_length=1)
    phase_id: str = Field(min_length=1)
    voice: str = Field(min_length=1)
    deliverables: list[str] = Field(default_factory=list)
    checkpoint_results: list[WorkflowCheckpointResult] = Field(default_factory=list)


class WorkflowCheckpointFailData(EventModel):
    workflow: str = Field(min_length=1)
    phase_id: str = Field(min_length=1)
    checkpoint: str = Field(min_length=1)
    voice: str = Field(min_length=1)


class WorkflowCompletedData(EventModel):
    workflow: str = Field(min_length=1)
    voice: str = Field(min_length=1)


class BacklogItem(EventModel):
    id: str
    title: str = Field(min_length=1)
    description: str = ""
    priority: BacklogPriority
    status: BacklogStatus = BacklogStatus.BACKLOG
    estimate: int | float | None = Field(default=None, ge=0)
    dependencies: list[str] = Field(default_factory=list)
    created_by: str
    tags: list[str] = Field(default_factory=list)

    @field_validator("priority", "status", mode="before")
    @classmethod
    def parse_backlog_enum(cls, value: BacklogPriority | BacklogStatus | str) -> BacklogPriority | BacklogStatus:
        if isinstance(value, BacklogPriority | BacklogStatus):
            return value
        try:
            return BacklogPriority(value)
        except ValueError:
            return BacklogStatus(value)


class BacklogListData(EventModel):
    status: BacklogStatus | None = None
    priority: BacklogPriority | None = None

    @field_validator("status", "priority", mode="before")
    @classmethod
    def parse_filter_enum(cls, value: BacklogPriority | BacklogStatus | str) -> BacklogPriority | BacklogStatus:
        if isinstance(value, BacklogPriority | BacklogStatus):
            return value
        try:
            return BacklogStatus(value)
        except ValueError:
            return BacklogPriority(value)


class BacklogAddData(EventModel):
    item: BacklogItem


class BacklogUpdateData(EventModel):
    id: str
    status: BacklogStatus | None = None
    priority: BacklogPriority | None = None
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    estimate: int | float | None = Field(default=None, ge=0)
    tags: list[str] | None = None

    @field_validator("status", "priority", mode="before")
    @classmethod
    def parse_update_enum(cls, value: BacklogPriority | BacklogStatus | str) -> BacklogPriority | BacklogStatus:
        if isinstance(value, BacklogPriority | BacklogStatus):
            return value
        try:
            return BacklogStatus(value)
        except ValueError:
            return BacklogPriority(value)


Payload = TypeVar("Payload", bound=BaseModel)


class EventEnvelope(EventModel, Generic[Payload]):
    name: str = Field(min_length=1)
    data: Payload
    source: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target: str | None = None
    capabilities: list[str] | None = None
    only_once: bool = False
    reply_to: str | None = None
    correlation_id: str | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware UTC")
        return value.astimezone(timezone.utc)
