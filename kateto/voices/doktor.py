from __future__ import annotations

from pathlib import Path

from kateto.core.config import VoiceSettings
from kateto.voices.base import StreamingProvider, VoiceAgent, VoiceProfile, VoiceRole


_PROFILE = VoiceProfile(
    voice_id="doktor",
    display_name="Doktor",
    role=VoiceRole.DELIVERY_ADVISOR,
    system_prompt="You are Doktor, Kateto's delivery advisor. Turn product intent into clear backlog work, expose risk, estimate thoughtfully, and protect delivery focus.",
    relevance_terms=frozenset({"backlog", "task", "risk", "estimate", "priority", "calendar", "plan"}),
)


class Doktor(VoiceAgent):
    def __init__(self, *, config_dir: Path, provider: StreamingProvider, settings: VoiceSettings | None = None) -> None:
        super().__init__(profile=_PROFILE, config_dir=config_dir, provider=provider, settings=settings)
