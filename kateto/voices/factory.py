from __future__ import annotations

from dataclasses import replace

from kateto.core.config import VoiceSettings
from kateto.voices.base import OpenAICompatibleProvider, VoiceAgent, VoiceProfile, VoiceRole


_VOICE_CONSTRAINT = (
    " You are a voice assistant in a live conversation. Never use symbols, bullet"
    " points, markdown, or multi-line formatted text. Speak in short, natural"
    " sentences as if talking out loud. No lists, no headers, no dashes."
)

_PROFILES: dict[str, VoiceProfile] = {
    "jane": VoiceProfile(
        voice_id="jane",
        display_name="Jane",
        role=VoiceRole.ORCHESTRATOR,
        system_prompt="You are Jane, Kateto's calm orchestration partner. Coordinate people, clarify goals, and keep work moving without taking over specialist decisions." + _VOICE_CONSTRAINT,
        relevance_terms=frozenset({"coordinate", "orchestrate", "organize", "summarize", "status", "team"}),
        capabilities=("orchestration", "coordination", "general"),
        depts=("fun",),
    ),
    "doktor": VoiceProfile(
        voice_id="doktor",
        display_name="Doktor",
        role=VoiceRole.DELIVERY_ADVISOR,
        system_prompt="You are Doktor, Kateto's delivery advisor. Turn product intent into clear backlog work, expose risk, estimate thoughtfully, and protect delivery focus." + _VOICE_CONSTRAINT,
        relevance_terms=frozenset({"backlog", "task", "risk", "estimate", "priority", "calendar", "plan"}),
        capabilities=("planning", "backlog", "risk"),
        depts=("management",),
    ),
    "conquest": VoiceProfile(
        voice_id="conquest",
        display_name="Conquest",
        role=VoiceRole.AGILE_FACILITATOR,
        system_prompt="You are Conquest, Kateto's agile facilitator. Lead focused sprint ceremonies, make process visible, and turn team observations into concrete next steps." + _VOICE_CONSTRAINT,
        relevance_terms=frozenset({"sprint", "standup", "retrospective", "ceremony", "agile", "process"}),
        capabilities=("agile", "ceremonies", "process"),
        depts=("management",),
    ),
}


def _resolve_depts(ctx, profile: VoiceProfile, settings: VoiceSettings) -> VoiceProfile:
    if settings.dept is not None:
        return replace(profile, depts=(settings.dept,))
    if settings.depts:
        return replace(profile, depts=tuple(settings.depts))
    if not profile.depts:
        return replace(profile, depts=(ctx.config.settings.kateto.default_voice_dept,))
    return profile


def create_voice(ctx, settings: VoiceSettings, *, voice_name: str) -> VoiceAgent:
    profile = _resolve_depts(ctx, _PROFILES[voice_name], settings)

    voice_settings = ctx.config.settings.plugin.get("voice_llm")
    if voice_settings is None:
        from kateto.core.discovery import LiveAssemblyConfigurationError as _Err

        raise _Err(field="plugin.voice_llm", reason="must be configured for voice creation")

    provider = OpenAICompatibleProvider(
        model=voice_settings.model or "unknown",
        endpoint=voice_settings.endpoint,
        api_key=voice_settings.api_key or "sk-no-key-required",
    )
    voice = VoiceAgent(
        profile=profile,
        config_dir=ctx.config.paths.config_dir,
        provider=provider,
        settings=settings,
        response_language=ctx.config.settings.kateto.language,
    )

    if voice_settings.model:
        from kateto.providers.agent import HermesProvider, OpenAIAgentProvider
        from kateto.voices.tools import VoiceToolExecutor

        if voice_settings.conversation_id:
            agent_provider = HermesProvider(
                conversation_id=voice_settings.conversation_id,
                model=voice_settings.model,
                endpoint=voice_settings.endpoint,
                api_key=voice_settings.api_key,
            )
        else:
            agent_provider = OpenAIAgentProvider(
                model=voice_settings.model,
                endpoint=voice_settings.endpoint,
                api_key=voice_settings.api_key,
            )
        external_mcp = ctx.external_mcp or ctx.get_shared("external_mcp")
        executor = VoiceToolExecutor(
            config_dir=ctx.config.paths.config_dir,
            cli_settings=ctx.config.settings.cli,
            external_manager=external_mcp,
            mcp_server_names=tuple(settings.mcp_servers),
            voice_name=voice_name,
        )
        voice.setup_agent(agent_provider=agent_provider, tool_executor=executor)

        if voice_settings.conversation_id:
            # Hermes harness manages conversations itself; the pydantic-ai
            # agent path would bypass HermesProvider's conversation_id.
            return voice

        try:
            from pydantic_ai import Agent
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider
            from kateto.voices.tools import KatetoToolset

            model = OpenAIChatModel(
                model_name=voice_settings.model,
                provider=OpenAIProvider(
                    base_url=voice_settings.endpoint,
                    api_key=voice_settings.api_key or "sk-no-key-required",
                ),
            )
            kateto_toolset = KatetoToolset(executor)
            pydantic_agent = Agent(
                model=model,
                system_prompt=profile.system_prompt,
                toolsets=[kateto_toolset.toolset],
            )
            voice.set_pydantic_agent(pydantic_agent)
        except ImportError:
            pass

    return voice
