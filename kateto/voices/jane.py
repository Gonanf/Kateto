from __future__ import annotations

from pathlib import Path

from kateto.core.config import VoiceSettings
from kateto.voices.base import StreamingProvider, VoiceAgent, VoiceProfile, VoiceRole


_PROFILE = VoiceProfile(
    voice_id="jane",
    display_name="Jane",
    role=VoiceRole.ORCHESTRATOR,
    system_prompt="You are Jane, Kateto's calm orchestration partner. Coordinate people, clarify goals, and keep work moving without taking over specialist decisions.",
    relevance_terms=frozenset({"coordinate", "orchestrate", "organize", "summarize", "status", "team"}),
)


class Jane(VoiceAgent):
    def __init__(self, *, config_dir: Path, provider: StreamingProvider, settings: VoiceSettings | None = None) -> None:
        super().__init__(profile=_PROFILE, config_dir=config_dir, provider=provider, settings=settings)
