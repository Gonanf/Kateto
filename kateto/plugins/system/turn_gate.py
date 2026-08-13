from __future__ import annotations

from collections import deque
from enum import StrEnum

from loguru import logger

from kateto.core.event import (
    AudioOutput,
    AudioOutputStatus,
    AudioOutputStatusData,
    Classification,
    ClassificationData,
    EventModel,
    GenerateData,
    GenerateRequestData,
    InterruptData,
    SpeakRequestData,
    TranscriptionData,
    VoiceIdleData,
    VoiceStatus,
    VoiceStatusData,
)
from kateto.core.plugin import Plugin

log = logger

_IGNORE_WINDOW: int = 8


class VoiceTurnState(StrEnum):
    IDLE = "idle"
    THINKING = "thinking"
    SPEAKING = "speaking"


class Decision(StrEnum):
    EXECUTE = "execute"
    QUEUE = "queue"
    DISCARD = "discard"


QueuedTurn = tuple[str, EventModel, str | None]


class TurnGate(Plugin):
    """Turn gating + steering/follow-up queues for the voice team.

    Mirrors existing bus events into per-voice turn state and the follow-up
    queue. No global singleton: the gate is one more subscriber.
    """

    def __init__(self) -> None:
        super().__init__("turn_gate")
        self._states: dict[str, VoiceTurnState] = {}
        self._active: str | None = None
        self._active_prompt: str | None = None
        self._mixer_busy = False
        self._barge_in: set[str] = set()
        self._steering = False
        self._ignored: deque[str] = deque(maxlen=_IGNORE_WINDOW)
        self._pending: deque[QueuedTurn] = deque()

    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("speak", SpeakRequestData)
        manager.register_event("voice_status", VoiceStatusData)
        manager.register_event("audio_output", AudioOutput)
        manager.register_event("audio_output_status", AudioOutputStatusData)
        manager.register_event("voice_idle", VoiceIdleData)
        manager.register_event("transcription", TranscriptionData)
        manager.register_event("classification", ClassificationData)

    async def on_speak(self, data: SpeakRequestData) -> None:
        self._states[data.voice] = VoiceTurnState.THINKING
        if self._active is None:
            self._active = data.voice
            self._active_prompt = data.prompt

    async def on_voice_status(self, data: VoiceStatusData) -> None:
        match data.status:
            case VoiceStatus.THINKING:
                self._states[data.voice] = VoiceTurnState.THINKING
            case VoiceStatus.TALKING:
                self._states[data.voice] = VoiceTurnState.SPEAKING
            case VoiceStatus.IDLE:
                self._states[data.voice] = VoiceTurnState.IDLE
                if self._active == data.voice:
                    self._active = None
                    self._active_prompt = None
                    await self._drain()
            case VoiceStatus.WAITING:
                pass

    async def on_audio_output(self, data: AudioOutput) -> None:
        if data.voice_id is not None and not data.final:
            self._states[data.voice_id] = VoiceTurnState.SPEAKING

    async def on_audio_output_status(self, data: AudioOutputStatusData) -> None:
        if data.status is AudioOutputStatus.PLAYING:
            self._mixer_busy = True
        else:
            self._mixer_busy = False
            await self._drain()

    async def on_voice_idle(self, data: VoiceIdleData) -> None:
        self._states[data.voice] = VoiceTurnState.IDLE
        if self._active == data.voice:
            self._active = None
            self._active_prompt = None
            await self._drain()

    async def on_interrupt(self, data: InterruptData) -> None:
        for voice, state in tuple(self._states.items()):
            if state in (VoiceTurnState.THINKING, VoiceTurnState.SPEAKING):
                if data.dept is not None and data.dept not in self._voice_depts(voice):
                    continue
                self._barge_in.add(voice)
                self._states[voice] = VoiceTurnState.IDLE
        if self._active is not None:
            self._active = None
            self._active_prompt = None
        self._steering = True

    async def on_transcription(self, data: TranscriptionData) -> None:
        if self._active is not None:
            self._steering = True

    async def on_classification(self, data: ClassificationData) -> None:
        if data.category in (Classification.IGNORE_SELF_TALK, Classification.IGNORE_THIRD_PARTY):
            self._ignored.append(data.text)

    def decide(self, *, voice: str, prompt: str, origin: str) -> Decision:
        """Feed-only decision: ``origin`` is "external" (user/system: steering
        priority) or "followup" (inter-voice: only when no other voice holds the turn)."""
        if self._consume_ignored(prompt):
            return Decision.DISCARD
        if origin == "followup":
            if voice in self._barge_in or (
                self._active is not None and self._active != voice
            ) or self._mixer_busy:
                return Decision.QUEUE
            self._claim(voice, prompt)
            return Decision.EXECUTE
        self._steering = False
        self._barge_in.discard(voice)
        if self._active is not None or self._mixer_busy:
            if self._active_prompt is not None and prompt == self._active_prompt:
                return Decision.DISCARD
            return Decision.QUEUE
        self._claim(voice, prompt)
        return Decision.EXECUTE

    def _claim(self, voice: str, prompt: str) -> None:
        self._active = voice
        self._active_prompt = prompt
        self._states[voice] = VoiceTurnState.THINKING

    def _consume_ignored(self, prompt: str) -> bool:
        for index, text in enumerate(self._ignored):
            if text == prompt:
                del self._ignored[index]
                return True
        return False

    def enqueue(
        self,
        *,
        event: str,
        data: EventModel,
        target: str | None,
        front: bool = False,
    ) -> None:
        item: QueuedTurn = (event, data, target)
        if front:
            self._pending.appendleft(item)
        else:
            self._pending.append(item)

    def release(self, voice: str) -> None:
        if self._active == voice:
            self._active = None
            self._active_prompt = None
            self._states[voice] = VoiceTurnState.IDLE

    async def _drain(self) -> None:
        manager = self.manager
        if manager is None or not self._pending:
            return
        if self._active is not None or self._mixer_busy or self._steering:
            return
        for _ in range(len(self._pending)):
            event, data, target = self._pending[0]
            if not self._target_latched(event, data, target):
                self._pending.popleft()
                log.info("turn_gate: draining follow-up {}({}) -> {}", event, target, data)
                await manager.emit(event, data, source=self.name, target=target)
                return
            self._pending.rotate(-1)

    def _target_latched(self, event: str, data: EventModel, target: str | None) -> bool:
        voice: str | None = None
        match event, data:
            case "generate_request", GenerateRequestData(target_voice=target_voice):
                voice = target_voice
            case "speak", SpeakRequestData(voice=speak_voice):
                voice = speak_voice
            case "generate", _:
                voice = target
        return voice is not None and voice in self._barge_in

    def _voice_depts(self, voice: str) -> tuple[str, ...]:
        manager = self.manager
        if manager is None:
            return ()
        plugin = manager.get_plugin(voice)
        return plugin.depts if plugin is not None else ()