from __future__ import annotations

from kateto.core.config import VoiceSettings
from kateto.voices.base import OpenAICompatibleProvider, VoiceAgent, VoiceProfile, VoiceRole


_PROFILES: dict[str, VoiceProfile] = {
    "jane": VoiceProfile(
        voice_id="jane",
        display_name="Jane",
        role=VoiceRole.ORCHESTRATOR,
        system_prompt="You are Jane, Kateto's calm orchestration partner. Coordinate people, clarify goals, and keep work moving without taking over specialist decisions.",
        relevance_terms=frozenset({"coordinate", "orchestrate", "organize", "summarize", "status", "team"}),
    ),
    "doktor": VoiceProfile(
        voice_id="doktor",
        display_name="Doktor",
        role=VoiceRole.DELIVERY_ADVISOR,
        system_prompt="You are Doktor, Kateto's delivery advisor. Turn product intent into clear backlog work, expose risk, estimate thoughtfully, and protect delivery focus.",
        relevance_terms=frozenset({"backlog", "task", "risk", "estimate", "priority", "calendar", "plan"}),
    ),
    "conquest": VoiceProfile(
        voice_id="conquest",
        display_name="Conquest",
        role=VoiceRole.AGILE_FACILITATOR,
        system_prompt="You are Conquest, Kateto's agile facilitator. Lead focused sprint ceremonies, make process visible, and turn team observations into concrete next steps.",
        relevance_terms=frozenset({"sprint", "standup", "retrospective", "ceremony", "agile", "process"}),
    ),
}


def create_voice(ctx, settings: VoiceSettings, *, voice_name: str) -> VoiceAgent:
    profile = _PROFILES[voice_name]

    voice_settings = ctx.config.settings.plugin.get("voice_llm")
    if voice_settings is None:
        from kateto.core.discovery import LiveAssemblyConfigurationError as _Err

        raise _Err(field="plugin.voice_llm", reason="must be configured for voice creation")

    provider = OpenAICompatibleProvider(
        model=voice_settings.model or "unknown",
        endpoint=voice_settings.endpoint,
        api_key=voice_settings.api_key or "sk-no-key-required",
    )
    voice = VoiceAgent(profile=profile, config_dir=ctx.config.paths.config_dir, provider=provider, settings=settings)

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
