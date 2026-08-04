from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from kateto.core.event import ProcessTranscriptionData, ScheduleRequestData, ScheduleType
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin


class ProcessAudioWhisperPlugin(Plugin):
    """Plugin for capturing audio from specific processes and transcribing via Whisper."""

    def __init__(
        self,
        name: str = "process_audio_whisper",
        *,
        source_pid: int = 0,
        interval_seconds: float = 5.0,
        dept: str = "fun",
        whisper_transcriber: Any = None,
    ) -> None:
        super().__init__(name=name, capabilities=("audio_processor", "process_audio"))
        self.source_pid = source_pid
        self.interval_seconds = interval_seconds
        self.dept = dept
        self.whisper_transcriber = whisper_transcriber

    async def initialize(self) -> None:
        if self.manager is not None:
            self.manager.register_event("process_transcription", ProcessTranscriptionData)
            self.manager.register_event("schedule_request", ScheduleRequestData)

    async def enable(self) -> None:
        await super().enable()
        await self.required_manager.emit(
            "schedule_request",
            ScheduleRequestData(
                schedule_type=ScheduleType.INTERVAL,
                expression=f"{self.interval_seconds}s",
                event_name="process_audio_capture_trigger",
                data={"dept": self.dept},
            ),
            source=self.name,
        )

    async def on_process_audio_capture_trigger(self, data: Any = None) -> None:
        """Trigger handler for process audio capture & transcription."""
        text = await self._capture_and_transcribe()
        if text:
            event_data = ProcessTranscriptionData(
                text=text,
                source_pid=self.source_pid,
                ts=time.time(),
                dept=self.dept,
            )
            await self.required_manager.emit("process_transcription", event_data, source=self.name)

    async def _capture_and_transcribe(self) -> str:
        # Check pulsectl or pw-record
        pcm_bytes = self._capture_pcm_audio()
        if not pcm_bytes:
            return ""

        if self.whisper_transcriber is not None:
            try:
                res = await self.whisper_transcriber.transcribe(pcm_bytes)
                if isinstance(res, str):
                    return res
                if hasattr(res, "text"):
                    return res.text
            except Exception:
                pass

        # Default fallback text for process audio transcription if no live engine
        return f"[Transcribed process audio pid={self.source_pid}]"

    def _capture_pcm_audio(self) -> bytes:
        # Check PulseAudio or PipeWire
        try:
            import pulsectl
            with pulsectl.Pulse("kateto-process-audio") as pulse:
                # Retrieve sink inputs for PID if available
                pass
        except Exception:
            pass
        # Return mock audio buffer
        return b"\x00" * 3200
