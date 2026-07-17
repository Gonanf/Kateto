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


def create_voice(ctx, settings):
    from kateto.voices.base import OpenAICompatibleProvider as _Provider
    from kateto.voices.jane import Jane

    voice_settings = ctx.config.settings.plugin.get("voice_llm")
    if voice_settings is None:
        from kateto.core.discovery import LiveAssemblyConfigurationError as _Err

        raise _Err(field="plugin.voice_llm", reason="must be configured for voice creation")

    provider = _Provider(
        model=voice_settings.model or "unknown",
        endpoint=voice_settings.endpoint,
        api_key=voice_settings.api_key or "sk-no-key-required",
    )
    return Jane(config_dir=ctx.config.paths.config_dir, provider=provider, settings=settings)
