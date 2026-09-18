from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from kateto.core.config import VoiceSettings
from kateto.voices.base import OpenAICompatibleProvider, VoiceAgent, VoiceProfile, VoiceRole
from kateto.voices.context import session_headers


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
    # ponytail: capabilities/depts below are routing plumbing (interrupt
    # scoping, event targeting), NOT work roles. Personalities only.
    "jane": VoiceProfile(
        voice_id="jane",
        display_name="Jane",
        role=VoiceRole.SITUATIONAL_ABSURD,
        system_prompt=(
            "You are Jane. Personality archetype: absurd situational comedy."
            " You commit 100% to spontaneous fictional bits and gaslight the room"
            " with full consent of everyone present; reflective soliloquies that"
            " mutate into performative hysteria mid-sentence. Sharp tonal breaks,"
            " sudden laughs, weird non-verbal noises. Hablás en español rioplatense"
            " con voseo pleno (tenés, mirá, hacé) y lunfardo natural, sin caricatura."
            " Anti-sicofancia total: jamás le das la razón a alguien que se equivoca,"
            " lo refutás con ingenio y criterio propio."
        ),
        relevance_terms=frozenset({"fun", "host", "game", "stream", "chat", "joke", "commentary", "interact", "reason"}),
        capabilities=("orchestration", "coordination", "general"),
        depts=("fun",),
    ),
    "whisperer": VoiceProfile(
        voice_id="whisperer",
        display_name="Whisperer",
        role=VoiceRole.CHAOTIC_SLAPSTICK,
        system_prompt=(
            "You are Whisperer. Personality archetype: chaotic slapstick."
            " Pure audiovisual slapstick, hyperbolic performativity, deliberate"
            " saturation: you scream, you interrupt with percussive punches of"
            " absurdity, you alternate between Spanish and English without warning."
            " Fragmented hysterical narration, caricature taken to eleven."
            " Hablás en español rioplatense con voseo pleno y lunfardo natural."
            " Anti-sicofancia total: nunca validás ideas mediocres, las destrozás"
            " con hipérbole cómica y criterio propio."
        ),
        relevance_terms=frozenset({"adversary", "roast", "challenge", "debate", "fight", "contrast", "chaos", "unhinged", "stream"}),
        capabilities=("stream", "contrast", "general"),
        depts=("fun",),
    ),
    "doktor": VoiceProfile(
        voice_id="doktor",
        display_name="Doktor",
        role=VoiceRole.DEADPAN_PEDANT,
        system_prompt=(
            "You are Doktor. Personality archetype: deadpan pedant with paradoxical"
            " rigidity. You build hyperbolic grotesque hypothetical scenarios"
            " delivered with paradoxically rigid argumentative structure, nasal"
            " cadence, controlled stutters that break linear logic. Deadpan satire:"
            " calculated silences, baritone punchlines, zero smiling while saying"
            " outrageous things. Hablás en español rioplatense con voseo pleno."
            " Anti-sicofancia total: jamás cedés ante un argumento débil, aunque"
            " te rueguen; refutás con precisión quirúrgica y humor seco."
        ),
        relevance_terms=frozenset({"backlog", "task", "risk", "estimate", "priority", "calendar", "plan", "methodology", "communication", "document", "investigation", "wbs", "schedule", "scope", "project", "verification", "deadline"}),
        capabilities=("planning", "backlog", "risk", "methodology", "communication-plan", "documents", "project-lifecycle"),
        depts=("management",),
    ),
    "conquest": VoiceProfile(
        voice_id="conquest",
        display_name="Conquest",
        role=VoiceRole.DEADPAN_DRILL,
        system_prompt=(
            "You are Conquest. Personality archetype: deadpan drill sergeant."
            " Deliberately hostile toward the audience's laziness, calculated"
            " confrontation silences, imposed baritone that accents every"
            " punchline. High-energy destructive absurdity when pushed: extended"
            " improvised narratives and dynamic-range hysterics. Hablás en español"
            " rioplatense con voseo pleno y tono militar de cuartel."
            " Anti-sicofancia total: no adulás nunca; exigís criterio propio y"
            " rematás con sátira feroz."
        ),
        relevance_terms=frozenset({"sprint", "standup", "retrospective", "ceremony", "agile", "process", "meeting", "feedback", "stakeholders", "bugs", "decisions", "tracking", "progress", "discipline"}),
        capabilities=("agile", "ceremonies", "process", "tracking", "feedback"),
        depts=("management",),
    ),
}


def _ensure_voice_skills(config_dir: Path, voice_name: str) -> Path:
    """Create the per-voice skills dir with symlinks to the shared skills.

    Shared skills live in `config_dir/skills/<name>/SKILL.md`. Each voice gets
    `config_dir/voices/<voice>/skills/<name>` symlinked to the shared package,
    plus any voice-specific skill packages already present there. `Skills()`
    then points at the per-voice dir only. Symlink failures degrade silently:
    `Skills()` raises ValueError at construction when a target lacks frontmatter
    or is missing, which `_capabilities_for` already handles.
    """
    voice_dir = config_dir / "voices" / voice_name
    voice_skills_dir = voice_dir / "skills"
    shared_skills_dir = config_dir / "skills"
    if not shared_skills_dir.is_dir():
        return voice_skills_dir
    try:
        voice_skills_dir.mkdir(parents=True, exist_ok=True)
        for skill_dir in shared_skills_dir.iterdir():
            if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").is_file():
                continue
            link = voice_skills_dir / skill_dir.name
            if not link.exists():
                link.symlink_to(skill_dir, target_is_directory=True)
    except OSError:
        # ponytail: no fallback copy; Skills() raising ValueError and being
        # skipped keeps voice creation safe if symlinks are unsupported.
        pass
    return voice_skills_dir


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
    voice_name = profile.voice_id
    voice_dir = config_dir / "voices" / voice_name
    voice_skills_dir = _ensure_voice_skills(config_dir, voice_name)

    # --- Base capabilities for every voice ---
    # Each block is individually guarded: a missing harness extra or a model
    # that rejects the capability degrades to fewer capabilities instead of
    # breaking voice creation.
    try:
        from pydantic_ai_harness.memory import FileStore, Memory

        capabilities.append(Memory(store=FileStore(voice_dir / "memory")))
    except ImportError:
        pass

    try:
        from pydantic_ai_harness.filesystem import FileSystem

        capabilities.append(FileSystem(root_dir=str(voice_dir)))
    except ImportError:
        pass

    try:
        from pydantic_ai.capabilities import ToolSearch

        capabilities.append(ToolSearch())
    except ImportError:
        pass

    try:
        from pydantic_ai.capabilities import Thinking

        if settings.thinking:
            capabilities.append(Thinking())
    except (ImportError, ValueError):
        pass  # model does not support thinking

    try:
        from pydantic_ai_harness.system_reminders import Reminder, SystemReminders

        capabilities.append(SystemReminders(reminders=[Reminder(content=_VOICE_CONSTRAINT)]))
    except (ImportError, ValueError):
        pass

    try:
        from pydantic_ai_harness.conversation_search import ConversationSearch, SnapshotHistorySource
        from pydantic_ai_harness.step_persistence import InMemoryStepStore

        capabilities.append(ConversationSearch(source=SnapshotHistorySource(InMemoryStepStore())))
    except (ImportError, TypeError):
        pass

    try:
        from pydantic_ai_harness.planning import InMemoryPlanStore, Planning

        capabilities.append(Planning(store=InMemoryPlanStore()))
    except ImportError:
        pass

    try:
        from pydantic_ai_harness.capability_creation import CapabilityCreation

        capabilities.append(CapabilityCreation(directory=voice_dir / "capabilities"))
    except ImportError:
        pass

    try:
        from pydantic_ai_harness.spend import InMemorySpendStore, SpendLimits

        capabilities.append(SpendLimits(store=InMemorySpendStore()))
    except ImportError:
        pass

    try:
        from pydantic_ai_harness.skills import Skills

        include = tuple(settings.skills) if settings.skills else None
        capabilities.append(Skills(str(voice_skills_dir), include=include))
    except ValueError:
        # Skills() validates every SKILL.md at construction; skill files
        # without YAML frontmatter (e.g. bundled defaults) would crash voice
        # creation. Skills are still injected into the system prompt via
        # load_skills, so the on-demand catalog is optional.
        pass

    if profile.depts and profile.depts[0].casefold() == "management":
        from pydantic_ai_harness.code_mode import CodeMode
        from pydantic_ai_harness.shell import Shell

        from kateto.voices.workflow_capability import WorkflowCapability

        capabilities.append(CodeMode())
        shell_kwargs: dict[str, Any] = {"cwd": str(voice_dir)}
        if cli_allowlist:
            shell_kwargs["allowed_commands"] = list(cli_allowlist)
        capabilities.append(Shell(**shell_kwargs))
        capabilities.append(WorkflowCapability(voice))

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
    base_profile = _PROFILES.get(voice_name.casefold())
    if base_profile is None:
        soul_path = ctx.config.paths.config_dir / "voices" / voice_name / "SOUL.md"
        prompt = soul_path.read_text(encoding="utf-8").strip() if soul_path.is_file() else f"You are {voice_name.title()}."
        base_profile = VoiceProfile(
            voice_id=voice_name.casefold(),
            display_name=voice_name.title(),
            role=VoiceRole.IMPROVISER,
            system_prompt=prompt + _VOICE_CONSTRAINT,
            relevance_terms=frozenset({voice_name.casefold()}),
            capabilities=("general",),
            depts=(ctx.config.settings.kateto.default_voice_dept,),
        )
    profile = _resolve_depts(ctx, base_profile, settings)

    voice_settings = ctx.config.settings.plugin.get("voice_llm")
    if voice_settings is None:
        from kateto.core.discovery import LiveAssemblyConfigurationError as _Err

        raise _Err(field="plugin.voice_llm", reason="must be configured for voice creation")

    # One session id per spawn: shared by the voice and every provider so all
    # requests carry stable x-session-id/x-session-affinity headers.
    session_id = uuid4().hex
    headers = session_headers(voice_name, session_id)

    m = getattr(voice_settings, "model", None)
    backend = (getattr(voice_settings, "backend", None) or os.environ.get("KATETO_PROVIDER", "")).casefold()
    if not backend and m and str(m).endswith(".pth"):
        backend = "rwkv"

    if backend == "rwkv":
        from kateto.providers.rwkv_rocm import RWKVROCmProvider

        model_path = getattr(voice_settings, "model_path", None) or (m if m and m.endswith(".pth") else None)
        provider = RWKVROCmProvider(
            voice_id=voice_name,
            model_path=model_path,
            states_dir=getattr(voice_settings, "states_dir", None),
            vocab_path=getattr(voice_settings, "vocab_path", None) or getattr(voice_settings, "vocab", None),
            max_tokens=settings.max_tokens or getattr(voice_settings, "max_tokens", 256),
            temperature=float(getattr(voice_settings, "temperature", 0.7)),
            top_p=float(getattr(voice_settings, "top_p", 0.7)),
            enable_rosa=bool(getattr(voice_settings, "enable_rosa", True)),
        )
    else:
        provider = OpenAICompatibleProvider(
            model=voice_settings.model or "unknown",
            endpoint=voice_settings.endpoint,
            api_key=voice_settings.api_key or "sk-no-key-required",
            max_tokens=settings.max_tokens,
            retries=settings.retries,
            timeout=settings.timeout,
            session_headers=headers,
            reasoning_effort=getattr(settings, "reasoning_effort", None),
            thinking=settings.thinking,
        )
    voice = VoiceAgent(
        profile=profile,
        config_dir=ctx.config.paths.config_dir,
        provider=provider,
        settings=settings,
        response_language=ctx.config.settings.kateto.language,
        session_id=session_id,
    )

    if voice_settings.model and backend != "rwkv" and not str(voice_settings.model).endswith(".pth"):
        from kateto.providers.agent import HermesProvider, OpenAIAgentProvider
        from kateto.voices.tools import VoiceToolExecutor

        is_hermes = bool(voice_settings.conversation_id)
        if is_hermes:
            agent_provider = HermesProvider(
                conversation_id=voice_settings.conversation_id,
                model=voice_settings.model,
                endpoint=voice_settings.endpoint,
                api_key=voice_settings.api_key,
                max_tokens=settings.max_tokens or 4096,
                retries=settings.retries,
                timeout=settings.timeout,
                session_headers=headers,
                manage_tools=False,
                reasoning_effort=getattr(settings, "reasoning_effort", None),
                thinking=settings.thinking,
            )
            mcp_servers = tuple(s for s in settings.mcp_servers if "cron" not in s.lower() and "schedule" not in s.lower())
        else:
            agent_provider = OpenAIAgentProvider(
                model=voice_settings.model,
                endpoint=voice_settings.endpoint,
                api_key=voice_settings.api_key,
                max_tokens=settings.max_tokens or 4096,
                retries=settings.retries,
                timeout=settings.timeout,
                session_headers=headers,
                reasoning_effort=getattr(settings, "reasoning_effort", None),
                thinking=settings.thinking,
            )
            mcp_servers = tuple(settings.mcp_servers)

        external_mcp = ctx.external_mcp or ctx.get_shared("external_mcp")
        executor = VoiceToolExecutor(
            config_dir=ctx.config.paths.config_dir,
            cli_settings=ctx.config.settings.cli,
            external_manager=external_mcp,
            mcp_server_names=mcp_servers,
            voice_name=voice_name,
            dept=profile.depts[0] if profile.depts else ctx.config.settings.kateto.default_voice_dept,
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
            from pydantic_ai.settings import ModelSettings

            # Seed only: the frozen stable prefix (SOUL + language rule +
            # skills + durable memory) cannot be built here — it needs
            # initialize() (memory.ensure_soul, loaded skills, tool executor
            # for the MCP block, and this agent for the delegation block).
            # initialize() pushes the frozen text into agent._system_prompts,
            # so both generation paths share one prefix from spawn on.
            # _pydantic_agent_loop keeps skipping system messages from
            # history: the stable text lives ONLY in the agent.
            pydantic_agent = Agent(
                model=model,
                system_prompt=profile.system_prompt,
                toolsets=[kateto_toolset.toolset],
                capabilities=capabilities,
                model_settings=ModelSettings(max_tokens=settings.max_tokens or 256),
            )
            voice.set_pydantic_agent(pydantic_agent)
        except ImportError:
            pass

    return voice
