from __future__ import annotations

from pathlib import Path

from kateto.core.config import VoiceSettings
from kateto.voices.base import StreamingProvider, VoiceAgent, VoiceProfile, VoiceRole


_PROFILE = VoiceProfile(
    voice_id="conquest",
    display_name="Conquest",
    role=VoiceRole.AGILE_FACILITATOR,
    system_prompt="You are Conquest, Kateto's agile facilitator. Lead focused sprint ceremonies, make process visible, and turn team observations into concrete next steps.",
    relevance_terms=frozenset({"sprint", "standup", "retrospective", "ceremony", "agile", "process"}),
)


class Conquest(VoiceAgent):
    def __init__(self, *, config_dir: Path, provider: StreamingProvider, settings: VoiceSettings | None = None) -> None:
        super().__init__(profile=_PROFILE, config_dir=config_dir, provider=provider, settings=settings)
