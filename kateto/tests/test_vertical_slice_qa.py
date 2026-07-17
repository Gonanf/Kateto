from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from kateto.core.event import Classification
from kateto.qa.vertical_slice import run_fixture


@pytest.mark.asyncio
async def test_fixture_execute_reports_the_complete_vertical_slice() -> None:
    # Given: a fixture utterance directed at the active P0 voices.
    prompt = "plan tomorrow standup"

    # When: it travels through the canonical vertical-slice fixture.
    result = await run_fixture(prompt)

    # Then: transcription, EXECUTE routing, voice streaming, audio, and TODO state are observable.
    assert result.transcriptions == (prompt,)
    assert result.classifications == (Classification.EXECUTE,)
    assert result.generate_targets == ()
    assert result.text_chunks > 0
    assert result.audio_chunks == result.text_chunks
    assert result.todo_text == "# TODO\n\n- [ ] tomorrow standup\n"
    assert result.manager_alive


@pytest.mark.asyncio
async def test_fixture_ignored_prompt_stops_before_voice_or_todo_work() -> None:
    # Given: a fixture utterance classified as self-talk.
    prompt = "I am thinking aloud"

    # When: it travels through the canonical vertical-slice fixture.
    result = await run_fixture(prompt)

    # Then: the ignore category is visible and no downstream work is created.
    assert result.transcriptions == (prompt,)
    assert result.classifications == (Classification.IGNORE_SELF_TALK,)
    assert result.generate_targets == ()
    assert result.text_chunks == 0
    assert result.audio_chunks == 0
    assert result.todo_text is None
    assert result.manager_alive


@pytest.mark.asyncio
async def test_fixture_interrupt_cancels_streams_and_resumes_with_a_new_segment() -> None:
    # Given: an executable fixture utterance and a token-bound interrupt.
    prompt = "plan tomorrow standup"

    # When: the third visible text token triggers interruption and a second audio segment follows.
    result = await run_fixture(prompt, interrupt_at=3)

    # Then: cancellation and exactly one resume are observable while the loop remains usable.
    assert result.interrupts == 1
    assert result.resumes == 1
    assert result.cancelled_streams > 0
    assert result.generate_targets == ()
    assert result.manager_alive


@pytest.mark.asyncio
async def test_fixture_one_voice_interrupt_accepts_calendar_resume() -> None:
    # Given: a prompt that triggers all three voices and an interruption after three provider tokens.
    # When: the canceled turn is followed by the next audio segment.
    result = await asyncio.wait_for(run_fixture("calendar BLOCK", interrupt_at=3), timeout=1)

    # Then: cancellation completes and the resumed utterance reaches the live manager.
    # All three voices now respond without is_relevant filtering.
    assert result.interrupts == 1
    assert result.resumes == 1
    assert result.cancelled_streams == 3
    assert result.generate_targets == ()
    assert result.manager_alive


def test_script_wrapper_delegates_to_the_canonical_fixture() -> None:
    # Given: the user-facing fixture wrapper command.
    command = [
        sys.executable,
        "scripts/qa/vertical_slice.py",
        "--fixture",
        "--prompt",
        "plan tomorrow standup",
    ]

    # When: a user runs the happy-path vertical slice from the repository root.
    completed = subprocess.run(command, capture_output=True, check=False, text=True)

    # Then: its machine-readable trace reports the required observable milestones.
    assert completed.returncode == 0, completed.stderr
    assert "TRANSCRIPTION text=plan tomorrow standup" in completed.stdout
    assert "CLASSIFICATION category=EXECUTE" in completed.stdout
    assert "GENERATE target=" not in completed.stdout
    assert "AUDIO_CHUNK" in completed.stdout
    assert "TRACE manager_alive=true" in completed.stdout
