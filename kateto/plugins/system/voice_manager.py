from __future__ import annotations

from loguru import logger
import random
from collections.abc import Callable
from typing import Any

from kateto.core.config import PluginSettings
from kateto.core.event import (
    GenerateData,
    InterjectData,
    SpeakingStateData,
    SpeakRequestData,
    VoiceEnableData,
    VoiceEnabledData,
    VoiceIdleData,
    VoiceStatusData,
)
from kateto.core.plugin import Plugin
from kateto.voices.base import VoiceProfile

log = logger

_DEFAULT_PROBABILITIES: dict[str, float] = {
    "jane": 0.7,
    "doktor": 0.15,
    "conquest": 0.1,
}


class VoiceManager(Plugin):
    def __init__(
        self,
        settings: PluginSettings | None = None,
        *,
        on_voice_enable: Callable[[VoiceEnableData], Any] | None = None,
    ) -> None:
        super().__init__("voice_manager", streaming=True)
        self._settings = settings
        self._probabilities = dict(_DEFAULT_PROBABILITIES)
        self._speaking: str | None = None
        self._on_voice_enable = on_voice_enable
        if settings is not None and settings.voice_probabilities:
            self._probabilities.update(settings.voice_probabilities)

    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("generate", GenerateData)
        manager.register_event("speak", SpeakRequestData)
        manager.register_event("speaking_state", SpeakingStateData)
        manager.register_event("interject", InterjectData)
        manager.register_event("voice_enable", VoiceEnableData)
        manager.register_event("voice_enabled", VoiceEnabledData)

    async def on_generate(self, data: GenerateData) -> None:
        manager = self.required_manager
        prompt = data.prompt
        if prompt is None or not prompt.strip():
            return
        eligible = self._eligible_voices()
        if not eligible:
            log.warning("voice_manager: no eligible voices for generate")
            return
        chosen = self._pick_voice(eligible)
        log.info("voice_manager: routing to {} (probabilities: {})", chosen, self._probabilities)
        envelope = await manager.emit(
            "speak",
            SpeakRequestData(
                voice=chosen,
                prompt=prompt,
                workflow=data.workflow,
                phase_id=data.phase_id,
            ),
            source=self.name,
            target=chosen,
        )
        self._remember(envelope)

    async def on_voice_status(self, data: VoiceStatusData) -> None:
        manager = self.required_manager
        if data.status.value == "talking":
            self._speaking = data.voice
            await manager.emit(
                "speaking_state",
                SpeakingStateData(voice=data.voice, active=True),
                source=self.name,
            )
        elif self._speaking == data.voice and data.status.value in ("idle", "waiting"):
            self._speaking = None
            await manager.emit(
                "speaking_state",
                SpeakingStateData(voice=data.voice, active=False),
                source=self.name,
            )

    async def on_voice_idle(self, data: VoiceIdleData) -> None:
        if self._speaking == data.voice:
            manager = self.required_manager
            self._speaking = None
            await manager.emit(
                "speaking_state",
                SpeakingStateData(voice=data.voice, active=False),
                source=self.name,
            )

    async def on_voice_enable(self, data: VoiceEnableData) -> None:
        if self._on_voice_enable is not None:
            await self._on_voice_enable(data)

    def _eligible_voices(self) -> list[str]:
        manager = self.manager
        if manager is None:
            return []
        eligible: list[str] = []
        for plugin in manager.get_plugins():
            if not plugin.enabled:
                continue
            if "voice" not in plugin.capabilities:
                continue
            eligible.append(plugin.name)
        return eligible

    def _pick_voice(self, eligible: list[str]) -> str:
        weights = [self._probabilities.get(name, 1.0) for name in eligible]
        return random.choices(eligible, weights=weights, k=1)[0]

    def _remember(self, envelope: object) -> None:
        pass
