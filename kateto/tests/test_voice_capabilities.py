from pathlib import Path
from kateto.core.config import VoiceSettings
from kateto.voices.factory import _capabilities_for, _PROFILES
from kateto.voices.tools import VoiceToolExecutor


def test_capabilities_for_contains_only_callable_or_valid_capabilities(tmp_path: Path):
    # Given: a valid voice profile and settings
    profile = _PROFILES["jane"]
    settings = VoiceSettings(enabled=True)
    executor = VoiceToolExecutor(config_dir=tmp_path)

    # When: capabilities are resolved for the voice
    caps = _capabilities_for(
        voice=None,
        profile=profile,
        settings=settings,
        config_dir=tmp_path,
        executor=executor,
        cli_allowlist=None,
    )

    # Then: no DiskMediaStore, WebSearch, or WebFetch objects exist in capabilities for OpenAIChatModel compatibility
    names = {type(cap).__name__ for cap in caps}
    assert "DiskMediaStore" not in names, "DiskMediaStore is not a capability"
    assert "WebSearch" not in names, "WebSearch is incompatible with OpenAIChatModel"
    assert "WebFetch" not in names, "WebFetch is incompatible with OpenAIChatModel"


def test_create_voice_supports_custom_dynamic_voices(tmp_path: Path):
    from kateto.core.config import CliSettings, KatetoConfig, KatetoSettings, PluginSettings
    from kateto.core.discovery import DiscoveryContext
    from kateto.voices.factory import create_voice

    # Given: a user-defined custom voice directory with SOUL.md
    custom_voice_dir = tmp_path / "voices" / "custom_agent"
    custom_voice_dir.mkdir(parents=True, exist_ok=True)
    (custom_voice_dir / "SOUL.md").write_text("You are Custom Agent.", encoding="utf-8")

    from kateto.core.config import ConfigPaths, LoadedConfig

    config = LoadedConfig(
        settings=KatetoConfig(
            kateto=KatetoSettings(),
            plugin={"voice_llm": PluginSettings(model="gpt-4o-mini", endpoint="http://localhost:8000/v1")},
            cli=CliSettings(),
        ),
        paths=ConfigPaths(
            config_dir=tmp_path,
            config_file=tmp_path / "config.toml",
            dotenv_file=tmp_path / ".env",
            secrets_dir=tmp_path / "secrets",
        ),
    )
    ctx = DiscoveryContext(config=config, shared={})
    settings = VoiceSettings(enabled=True)

    # When: create_voice is invoked for an un-profiled voice name
    voice = create_voice(ctx, settings, voice_name="custom_agent")

    # Then: it dynamically builds the VoiceAgent without KeyError
    assert voice.name == "custom_agent"
    assert "Custom Agent" in voice.profile.system_prompt




def test_capabilities_skip_thinking_when_disabled(tmp_path: Path):
    # Given: thinking explicitly disabled (e.g. Hermes manages it server-side)
    profile = _PROFILES["jane"]
    settings = VoiceSettings(enabled=True, thinking=False)
    executor = VoiceToolExecutor(config_dir=tmp_path)

    # When: capabilities are resolved
    caps = _capabilities_for(
        voice=None,
        profile=profile,
        settings=settings,
        config_dir=tmp_path,
        executor=executor,
        cli_allowlist=None,
    )

    # Then: no Thinking capability is injected
    assert "Thinking" not in {type(cap).__name__ for cap in caps}


def test_capabilities_include_thinking_by_default(tmp_path: Path):
    # Given: default settings
    profile = _PROFILES["jane"]
    settings = VoiceSettings(enabled=True)
    executor = VoiceToolExecutor(config_dir=tmp_path)

    # When: capabilities are resolved
    caps = _capabilities_for(
        voice=None,
        profile=profile,
        settings=settings,
        config_dir=tmp_path,
        executor=executor,
        cli_allowlist=None,
    )

    # Then: Thinking stays on unless opted out
    assert "Thinking" in {type(cap).__name__ for cap in caps}


def test_prefill_skipped_when_disabled(tmp_path: Path):
    import asyncio

    from kateto.tests.conversation_support import StreamingFixtureProvider
    from kateto.voices.base import VoiceAgent

    # Given: a voice with prefill disabled
    voice = VoiceAgent(
        profile=_PROFILES["jane"],
        config_dir=tmp_path,
        provider=StreamingFixtureProvider(),
        settings=VoiceSettings(enabled=True, prefill=False),
    )

    # When: prefill runs
    result = asyncio.run(voice.prefill())

    # Then: no-op without touching the provider
    assert result is False
