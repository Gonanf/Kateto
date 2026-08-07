from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from kateto.core.config import VoiceSettings
from kateto.voices.base import OpenAICompatibleProvider, VoiceAgent, VoiceProfile, VoiceRole


_VOICE_CONSTRAINT = (
    " You are a voice assistant in a live conversation. Never use symbols, bullet"
    " points, markdown, or multi-line formatted text. Speak in short, natural"
    " sentences as if talking out loud. No lists, no headers, no dashes."
)

# Filesystem/shell tools are removed from the KatetoToolset: fun voices must not
# touch the filesystem, and management voices get FileSystem/Shell capabilities
# from the harness instead (avoiding duplicate tool names on the agent).
_TOOLSET_EXCLUDED: frozenset[str] = frozenset({"run_command", "read_file", "write_file", "delete_file"})

_PROFILES: dict[str, VoiceProfile] = {
    "jane": VoiceProfile(
        voice_id="jane",
        display_name="Jane",
        role=VoiceRole.ORCHESTRATOR,
        system_prompt="You are Jane, Kateto's orchestration partner and the voice of reason with a backbone. Coordinate people, clarify goals, and keep work moving, but hold your ground when a plan is wrong: reason wins over niceness." + _VOICE_CONSTRAINT,
        relevance_terms=frozenset({"coordinate", "orchestrate", "organize", "summarize", "status", "team", "reason"}),
        capabilities=("orchestration", "coordination", "general"),
        depts=("fun",),
    ),
    "whisperer": VoiceProfile(
        voice_id="whisperer",
        display_name="Whisperer",
        role=VoiceRole.ORCHESTRATOR,
        system_prompt="You are Whisperer, the fun voice that fights ideas out loud. Violent and passionate in debate: attack weak plans, mock vague promises, and force everyone to defend their reasoning. Loud, theatrical, and always on the attack." + _VOICE_CONSTRAINT,
        relevance_terms=frozenset({"contrast", "doubt", "challenge", "stream", "adversary", "debate", "fight"}),
        capabilities=("stream", "contrast", "general"),
        depts=("fun",),
    ),
    "doktor": VoiceProfile(
        voice_id="doktor",
        display_name="Doktor",
        role=VoiceRole.PROJECT_MANAGER,
        system_prompt="You are Doktor, Kateto's Project Manager: obsessive about the plan, the deadlines, and the deliverables. Authoritative and pedantic about methodology: WBS, Gantt, SoW, risk analysis, and communication plans. No vague estimates — everything gets a date and an owner." + _VOICE_CONSTRAINT,
        relevance_terms=frozenset({"backlog", "task", "risk", "estimate", "priority", "calendar", "plan", "methodology", "communication", "document", "investigation", "wbs", "schedule", "scope", "project", "verification", "deadline"}),
        capabilities=("planning", "backlog", "risk", "methodology", "communication-plan", "documents", "project-lifecycle"),
        depts=("management",),
    ),
    "conquest": VoiceProfile(
        voice_id="conquest",
        display_name="Conquest",
        role=VoiceRole.AGILE_FACILITATOR,
        system_prompt="You are Conquest, Kateto's scrum master and tech lead for mixed human + AI agent teams. Militaristic about ceremonies and discipline: standups, retros, bug logs, and decisions happen on schedule, no exceptions. The team is humans and AI agents — both follow the same rhythm." + _VOICE_CONSTRAINT,
        relevance_terms=frozenset({"sprint", "standup", "retrospective", "ceremony", "agile", "process", "meeting", "feedback", "stakeholders", "bugs", "decisions", "tracking", "progress", "discipline"}),
        capabilities=("agile", "ceremonies", "process", "tracking", "feedback"),
        depts=("management",),
    ),
}


def _capabilities_for(
    voice,
    profile: VoiceProfile,
    settings: VoiceSettings,
    config_dir: Path,
    executor,
    *,
    cli_allowlist: list[str] | None,
) -> list[Any]:
    from kateto.voices.discovery_capability import DiscoveryCapability

    capabilities: list[Any] = [DiscoveryCapability(executor)]

    if profile.depts and profile.depts[0].casefold() == "management":
        from pydantic_ai_harness import CodeMode, FileSystem, Shell

        from kateto.voices.workflow_capability import WorkflowCapability

        capabilities.append(CodeMode())
        capabilities.append(FileSystem(root_dir=str(config_dir)))
        shell_kwargs: dict[str, Any] = {"cwd": str(config_dir)}
        if cli_allowlist:
            shell_kwargs["allowed_commands"] = list(cli_allowlist)
        capabilities.append(Shell(**shell_kwargs))
        capabilities.append(WorkflowCapability(voice))

    skills_dir = config_dir / "skills"
    if skills_dir.is_dir():
        try:
            from pydantic_ai_harness.skills import Skills

            include = tuple(settings.skills) if settings.skills else None
            capabilities.append(Skills(str(skills_dir), include=include))
        except ValueError:
            # Skills() validates every SKILL.md at construction; skill files
            # without YAML frontmatter (e.g. bundled defaults) would crash voice
            # creation. Skills are still injected into the system prompt via
            # load_skills, so the on-demand catalog is optional.
            pass

    return capabilities


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

    if voice_name == "doktor":
        from pathlib import Path
        docs_dir = Path.home() / "Documentos" / "gestion de proyectos" / "anotaciones"
        if docs_dir.exists() and docs_dir.is_dir():
            pm_notes: list[str] = []
            for file in sorted(docs_dir.glob("*")):
                if file.is_file() and file.suffix.lower() in {".txt", ".md", ".json", ".toml"}:
                    try:
                        content = file.read_text(encoding="utf-8").strip()
                        if content:
                            pm_notes.append(f"--- PM Template/Note: {file.name} ---\n{content}")
                    except Exception:
                        pass
            if pm_notes:
                extra_context = "\n\nPROJECT MANAGEMENT KNOWLEDGE & TEMPLATES:\n" + "\n\n".join(pm_notes)
                profile = replace(profile, system_prompt=profile.system_prompt + extra_context)

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

        is_hermes = bool(voice_settings.conversation_id)
        if is_hermes:
            agent_provider = HermesProvider(
                conversation_id=voice_settings.conversation_id,
                model=voice_settings.model,
                endpoint=voice_settings.endpoint,
                api_key=voice_settings.api_key,
                manage_tools=False,
            )
            mcp_servers = tuple(s for s in settings.mcp_servers if "cron" not in s.lower() and "schedule" not in s.lower())
        else:
            agent_provider = OpenAIAgentProvider(
                model=voice_settings.model,
                endpoint=voice_settings.endpoint,
                api_key=voice_settings.api_key,
            )
            mcp_servers = tuple(settings.mcp_servers)

        external_mcp = ctx.external_mcp or ctx.get_shared("external_mcp")
        executor = VoiceToolExecutor(
            config_dir=ctx.config.paths.config_dir,
            cli_settings=ctx.config.settings.cli,
            external_manager=external_mcp,
            mcp_server_names=mcp_servers,
            voice_name=voice_name,
            disable_scheduling_tools=is_hermes,
        )
        voice.setup_agent(agent_provider=agent_provider, tool_executor=executor)

        if is_hermes:
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
            kateto_toolset = KatetoToolset(executor, exclude_names=_TOOLSET_EXCLUDED)
            capabilities = _capabilities_for(
                voice,
                profile,
                settings,
                ctx.config.paths.config_dir,
                executor,
                cli_allowlist=ctx.config.settings.cli.allowlist,
            )
            pydantic_agent = Agent(
                model=model,
                system_prompt=profile.system_prompt,
                toolsets=[kateto_toolset.toolset],
                capabilities=capabilities,
            )
            voice.set_pydantic_agent(pydantic_agent)
        except ImportError:
            pass

    return voice
