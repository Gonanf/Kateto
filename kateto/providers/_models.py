from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kateto.core.event import Classification


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ChatMessage(ProviderModel):
    role: Literal["assistant", "developer", "system", "user"]
    content: str = Field(min_length=1)


class WhisperResponse(ProviderModel):
    text: str = Field(min_length=1)
    language: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class JsonResponseFormat(ProviderModel):
    type: Literal["json_object"] = "json_object"


class ClassifierRequest(ProviderModel):
    model: str | None = None
    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    agents: tuple[str, ...] = Field(default_factory=tuple)
    temperature: float = 0.0
    stream: Literal[False] = False
    response_format: JsonResponseFormat = Field(default_factory=JsonResponseFormat)


class ClassificationMessage(ProviderModel):
    content: str = Field(min_length=1)


class ClassificationChoice(ProviderModel):
    message: ClassificationMessage


class ClassificationResponse(ProviderModel):
    choices: tuple[ClassificationChoice, ...] = Field(min_length=1)


class ClassificationPayload(ProviderModel):
    category: Classification
    confidence: float | None = Field(default=None, ge=0, le=1)


class ChatRequest(ProviderModel):
    model: str | None = None
    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    stream: Literal[True] = True


class ChatDelta(ProviderModel):
    content: str | None = None


class ChatChoice(ProviderModel):
    delta: ChatDelta


class ChatStreamResponse(ProviderModel):
    choices: tuple[ChatChoice, ...] = Field(min_length=1)


class ResponseInputText(ProviderModel):
    type: Literal["input_text"] = "input_text"
    text: str = Field(min_length=1)


class ResponseInputMessage(ProviderModel):
    role: Literal["assistant", "developer", "system", "user"]
    content: tuple[ResponseInputText, ...] = Field(min_length=1)


class ResponsesRequest(ProviderModel):
    model: str | None = None
    input: tuple[ResponseInputMessage, ...] = Field(min_length=1)
    stream: Literal[True] = True


class ResponseDelta(ProviderModel):
    type: Literal["response.output_text.delta"]
    delta: str


class ResponseEventType(ProviderModel):
    type: str = Field(min_length=1)


class CambRequest(ProviderModel):
    text: str = Field(min_length=1)
    language: str = "en-us"
    voice_id: int = 147320
    speech_model: str | None = None


class ZonosRequest(ProviderModel):
    input: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)
    model: str | None = None
    response_format: Literal["pcm"] = "pcm"
    stream: bool = True
