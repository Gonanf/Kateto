from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Protocol

from kateto.core.event import (
    AudioData,
    AudioOutput,
    InterruptData,
    TextChunk,
    ToolCallData,
    TranscriptionData,
)
from kateto.core.plugin import Plugin

logger = logging.getLogger(__name__)


class RealtimeSessionProtocol(Protocol):
    async def connect(self) -> None: ...

    async def send_audio_chunk(self, chunk: bytes, sample_rate: int = 16000) -> None: ...

    async def interrupt(self) -> None: ...

    async def disconnect(self) -> None: ...


class SimulatedRealtimeSession:
    """Mock/Simulated session for testing & offline mode."""

    def __init__(self, voice_id: str = "jane") -> None:
        self.voice_id = voice_id
        self.connected = False
        self.audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.is_interrupted = False

    async def connect(self) -> None:
        self.connected = True

    async def send_audio_chunk(self, chunk: bytes, sample_rate: int = 16000) -> None:
        if not self.connected:
            return
        await self.audio_queue.put(chunk)

    async def interrupt(self) -> None:
        self.is_interrupted = True
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def disconnect(self) -> None:
        self.connected = False


class OmnimodalConnectorPlugin(Plugin):
    """Plugin connecting Kateto's event bus to an Omnimodal Speech-to-Speech (S2S) inference server.

    Supports OpenAI Realtime API / FastRTC / WebRTC protocol schemas.
    Models supported: MiniCPM-o 4.5 GGUF, Qwen3-Omni-30B GGUF, HF speech-to-speech.
    """

    def __init__(
        self,
        name: str = "omnimodal_connector",
        *,
        endpoint_url: str = "ws://localhost:8080/v1/realtime",
        model_name: str = "openbmb/MiniCPM-o-4_5-gguf",
        voice_id: str = "jane",
        session: RealtimeSessionProtocol | None = None,
    ) -> None:
        super().__init__(
            name=name,
            capabilities=("audio_processor", "omnimodal_s2s", "audio_output"),
            streaming=True,
        )
        self.endpoint_url = endpoint_url
        self.model_name = model_name
        self.voice_id = voice_id
        self._session = session or SimulatedRealtimeSession(voice_id=voice_id)
        self._sequence_counter = 0
        self._is_active = False

    async def initialize(self) -> None:
        if self.manager is not None:
            self.manager.register_event("audio_output", AudioOutput)
            self.manager.register_event("text_chunk", TextChunk)
            self.manager.register_event("transcription", TranscriptionData)
            self.manager.register_event("tool_call", ToolCallData)

    async def enable(self) -> None:
        await super().enable()
        try:
            await self._session.connect()
            self._is_active = True
        except Exception as err:
            logger.warning("Failed to connect to Omnimodal server at %s: %s", self.endpoint_url, err)

    async def disable(self) -> None:
        self._is_active = False
        try:
            await self._session.disconnect()
        except Exception:
            pass
        await super().disable()

    async def on_audio_data(self, data: AudioData) -> None:
        """Stream raw microphone PCM audio to the omnimodal inference server."""
        if not self._is_active:
            return

        await self._session.send_audio_chunk(data.samples, sample_rate=data.sample_rate)

    async def on_interrupt(self, data: InterruptData) -> None:
        """Handle interrupt signal from VAD or user interrupt."""
        await self._session.interrupt()

    async def handle_server_event(self, server_event: dict[str, Any]) -> None:
        """Process incoming events from the Omnimodal S2S server and emit to Kateto event bus."""
        event_type = server_event.get("type", "")

        if event_type == "response.audio.delta":
            # Native audio token output PCM stream
            pcm_data = server_event.get("delta", b"")
            if isinstance(pcm_data, str):
                pcm_bytes = base64.b64decode(pcm_data)
            else:
                pcm_bytes = pcm_data

            if pcm_bytes and self.manager:
                self._sequence_counter += 1
                await self.required_manager.emit(
                    "audio_output",
                    AudioOutput(
                        samples=pcm_bytes,
                        sample_rate=server_event.get("sample_rate", 24000),
                        channels=1,
                        voice_id=self.voice_id,
                        sequence=self._sequence_counter,
                        final=server_event.get("final", False),
                    ),
                    source=self.name,
                )

        elif event_type == "response.text.delta":
            # Concurrent text streaming (transcription of output)
            text_delta = server_event.get("delta", "")
            if text_delta and self.manager:
                await self.required_manager.emit(
                    "text_chunk",
                    TextChunk(
                        text=text_delta,
                        sequence=self._sequence_counter,
                        final=server_event.get("final", False),
                        voice_id=self.voice_id,
                    ),
                    source=self.name,
                )

        elif event_type == "conversation.item.input_audio_transcription.completed":
            # User input transcription
            transcription_text = server_event.get("transcript", "")
            if transcription_text and self.manager:
                await self.required_manager.emit(
                    "transcription",
                    TranscriptionData(
                        text=transcription_text,
                        confidence=server_event.get("confidence", 1.0),
                    ),
                    source=self.name,
                )

        elif event_type == "response.function_call_arguments.done":
            # Tool call requested by model
            tool_name = server_event.get("name", "")
            call_id = server_event.get("call_id", f"call_{self._sequence_counter}")
            arguments_str = server_event.get("arguments", "{}")
            try:
                args = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
            except Exception:
                args = {}

            if tool_name and self.manager:
                await self.required_manager.emit(
                    "tool_call",
                    ToolCallData(
                        tool_name=tool_name,
                        arguments=args,
                        correlation_id=call_id,
                        voice=self.voice_id,
                    ),
                    source=self.name,
                )
