from __future__ import annotations


def test_voice_constraint_copies_match() -> None:
    # Given: the two synchronized copies of the voice constraint
    from kateto.plugins.bate_debate.orchestrator import (
        _VOICE_CONSTRAINT as _DEBATE_CONSTRAINT,
    )
    from kateto.voices.factory import _VOICE_CONSTRAINT as _FACTORY_CONSTRAINT

    # Then: they are byte-for-byte identical so the debate strip keeps matching
    assert _FACTORY_CONSTRAINT == _DEBATE_CONSTRAINT


def test_voice_constraint_has_no_assistant_sentence() -> None:
    # Given: the shared voice constraint text
    from kateto.voices.factory import _VOICE_CONSTRAINT

    lowered = _VOICE_CONSTRAINT.lower()
    # Then: the voice never presents itself as an assistant (en/es)
    assert "assistant" not in lowered
    assert "asistente" not in lowered
