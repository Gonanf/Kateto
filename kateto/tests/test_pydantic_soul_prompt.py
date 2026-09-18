"""El path pydantic-ai usa el prompt estable congelado (SOUL incluido)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kateto.core.config import VoiceSettings
from kateto.voices.base import VoiceAgent, VoiceProfile, VoiceRole

ARCHETYPE = "You are Jane. Personality archetype: test absurd."
SOUL = "Soy Jane, hablo con voseo y lunfardo, odio la sicofancia."
LANGUAGE = "español rioplatense"


class _FakeAgent:
    """Doble mínimo con el atributo real que pydantic-ai resuelve por run."""

    def __init__(self, system_prompt: str = "") -> None:
        self._system_prompts = (system_prompt,)


def _voice(tmp_path: Path, soul_text: str | None) -> VoiceAgent:
    if soul_text is not None:
        voice_dir = tmp_path / "voices" / "jane"
        voice_dir.mkdir(parents=True, exist_ok=True)
        (voice_dir / "SOUL.md").write_text(soul_text, encoding="utf-8")
    return VoiceAgent(
        profile=VoiceProfile(
            voice_id="jane",
            display_name="Jane",
            role=VoiceRole.SITUATIONAL_ABSURD,
            system_prompt=ARCHETYPE,
            relevance_terms=frozenset(),
        ),
        config_dir=tmp_path,
        provider=MagicMock(),
        settings=VoiceSettings(),
        response_language=LANGUAGE,
    )


@pytest.mark.asyncio
async def test_pydantic_agent_gets_stable_prompt_with_soul(tmp_path: Path) -> None:
    # Given: SOUL.md custom y un agente con sólo el arquetipo (como factory).
    voice = _voice(tmp_path, SOUL)
    agent = _FakeAgent(system_prompt=ARCHETYPE)
    voice.set_pydantic_agent(agent)

    # When: se congela el prompt estable.
    stable = await voice.build_stable_prompt()

    # Then: el agente ve SOUL + arquetipo + regla de idioma.
    assert agent._system_prompts == (stable,)
    assert SOUL in stable
    assert ARCHETYPE in stable
    assert LANGUAGE in stable


@pytest.mark.asyncio
async def test_pydantic_prompt_matches_non_pydantic_system_message(tmp_path: Path) -> None:
    # Given: voz congelada con agente pydantic.
    voice = _voice(tmp_path, SOUL)
    agent = _FakeAgent(system_prompt=ARCHETYPE)
    voice.set_pydantic_agent(agent)
    stable = await voice.build_stable_prompt()

    # When: se arman los mensajes del path no-pydantic.
    messages = await voice._messages_for("hola", workflow=None, phase_id=None)

    # Then: mismo texto en ambos paths, sin divergencia posible.
    assert messages[0].role == "system"
    assert messages[0].content == stable
    assert agent._system_prompts == (messages[0].content,)
    assert await voice._stable_prompt() == stable


@pytest.mark.asyncio
async def test_duplicate_soul_not_duplicated_in_agent(tmp_path: Path) -> None:
    # Given: SOUL idéntico al arquetipo del perfil.
    voice = _voice(tmp_path, ARCHETYPE)
    agent = _FakeAgent(system_prompt=ARCHETYPE)
    voice.set_pydantic_agent(agent)

    # When: se congela.
    stable = await voice.build_stable_prompt()

    # Then: la personalidad aparece una sola vez.
    assert stable.count(ARCHETYPE) == 1
    assert agent._system_prompts == (stable,)


@pytest.mark.asyncio
async def test_mid_session_soul_write_keeps_frozen_prompt(tmp_path: Path) -> None:
    # Given: prompt ya congelado.
    voice = _voice(tmp_path, SOUL)
    agent = _FakeAgent(system_prompt=ARCHETYPE)
    voice.set_pydantic_agent(agent)
    frozen = await voice.build_stable_prompt()

    # When: se escribe otro SOUL a mitad de sesión.
    (tmp_path / "voices" / "jane" / "SOUL.md").write_text(
        "Soy otra persona completamente distinta.", encoding="utf-8"
    )

    # Then: el congelado no cambia (aplica al próximo spawn).
    assert await voice.build_stable_prompt() == frozen
    assert agent._system_prompts == (frozen,)


@pytest.mark.asyncio
async def test_late_agent_attach_syncs_frozen_prompt(tmp_path: Path) -> None:
    # Given: estable congelado sin agente.
    voice = _voice(tmp_path, SOUL)
    frozen = await voice.build_stable_prompt()

    # When: el agente se adjunta después.
    agent = _FakeAgent(system_prompt=ARCHETYPE)
    voice.set_pydantic_agent(agent)

    # Then: recibe el congelado de inmediato.
    assert agent._system_prompts == (frozen,)
