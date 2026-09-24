from __future__ import annotations

"""Unit tests for voice output sanitizer (deterministic, pure function).

Verifies that leaked tool calls (function syntax, CLI positional syntax, markdown code blocks)
are stripped before hitting TTS, while legitimate dialogue (including parenthesized phrases)
is preserved intact.
"""

import pytest

from kateto.voices.sanitizer import sanitize_voice_output


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Real observed defect case 1: function call syntax with keyword args
        (
            "workflow_run(workflow='project-initiation', voice='Jane')\nMirá chango. El finde es para hacer lo que te dé la gana.",
            "Mirá chango. El finde es para hacer lo que te dé la gana.",
        ),
        (
            'workflow_run(workflow="project-initiation", voice="Jane")\nMirá chango.',
            "Mirá chango.",
        ),
        # Real observed defect case 2: CLI syntax positional / keyword
        (
            "workflow_run project-initiation voice_jane\n¡Mirá, mirá! Lo compensamos con marketing y publicidad.",
            "¡Mirá, mirá! Lo compensamos con marketing y publicidad.",
        ),
        (
            "workflow_run workflow project-initiation voice Jane\n\nMirá, dos semanas o un mes.",
            "Mirá, dos semanas o un mes.",
        ),
        (
            "workflow_run workflow=project-initiation voice=Jane\n\nMirá, el tema de los planes.",
            "Mirá, el tema de los planes.",
        ),
        # Built-in tools in the catalog
        (
            "request_generation(target_voice='Doktor', prompt='revisar')\nDale.",
            "Dale.",
        ),
        (
            "create_workflow(name='test')\nListo el pollo.",
            "Listo el pollo.",
        ),
        (
            "schedule_event(event='ping', delay=10)\nBancame diez.",
            "Bancame diez.",
        ),
        # Markdown code block wrapping tool calls
        (
            "```python\nworkflow_run(workflow='project-initiation', voice='Jane')\n```\nHola capo.",
            "Hola capo.",
        ),
        (
            "```\nworkflow_run project-initiation voice Jane\n```\nBuenas.",
            "Buenas.",
        ),
        # Arbitrary function syntax with voice/workflow params
        (
            "custom_dispatch(workflow='init', voice='Jane')\nTexto de respuesta.",
            "Texto de respuesta.",
        ),
        # Only tool call (no dialogue) -> empty string
        (
            "workflow_run(workflow='project-initiation')",
            "",
        ),
        (
            "workflow_run project-initiation voice Jane",
            "",
        ),
    ],
)
def test_sanitizer_strips_tool_calls(raw: str, expected: str) -> None:
    assert sanitize_voice_output(raw) == expected


@pytest.mark.parametrize(
    "dialogue",
    [
        "Mirá (che), no sé.",
        "Dale (amigo), vamos.",
        "El proyecto (que empezamos ayer) está listo.",
        "El workflow del equipo está funcionando bien.",
        "¿Querés (de verdad) que lo hagamos?",
        "Hola, ¿cómo estás?",
        "¡Che, pará un toque! ¿Qué finde? No te puedo decir nada.",
        "Tranqui, yo me encargo.",
    ],
)
def test_sanitizer_preserves_legitimate_dialogue(dialogue: str) -> None:
    assert sanitize_voice_output(dialogue) == dialogue


def test_sanitizer_handles_empty_and_whitespace() -> None:
    assert sanitize_voice_output("") == ""
    assert sanitize_voice_output("   ") == ""
