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


def create_voice(ctx, settings):
    from kateto.voices.base import OpenAICompatibleProvider as _Provider
    from kateto.voices.doktor import Doktor

    voice_settings = ctx.config.settings.plugin.get("voice_llm")
    if voice_settings is None:
        from kateto.core.discovery import LiveAssemblyConfigurationError as _Err

        raise _Err(field="plugin.voice_llm", reason="must be configured for voice creation")

    provider = _Provider(
        model=voice_settings.model or "unknown",
        endpoint=voice_settings.endpoint,
        api_key=voice_settings.api_key or "sk-no-key-required",
    )
    voice = Doktor(config_dir=ctx.config.paths.config_dir, provider=provider, settings=settings)

    if voice_settings.model:
        from kateto.providers.agent import OpenAIAgentProvider
        from kateto.voices.tools import VoiceToolExecutor
        agent_provider = OpenAIAgentProvider(
            model=voice_settings.model,
            endpoint=voice_settings.endpoint,
            api_key=voice_settings.api_key,
        )
        executor = VoiceToolExecutor(
            config_dir=ctx.config.paths.config_dir,
            cli_settings=ctx.config.settings.cli,
        )
        voice.setup_agent(agent_provider=agent_provider, tool_executor=executor)

    return voice
