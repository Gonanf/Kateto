from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_fixture(*arguments: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "scripts/qa/backlog_fixture.py", *arguments]
    return subprocess.run(command, check=False, capture_output=True, text=True)


def test_backlog_fixture_persists_one_item_when_add_command_is_called() -> None:
    # Given
    command_arguments = ("add", "--title", "Demo task", "--priority", "Must")

    # When
    result = _run_fixture(*command_arguments)

    # Then
    assert result.returncode == 0, result.stderr
    assert "ASSERT persisted_items=1 status=PASS" in result.stdout
    assert "CANONICAL_STORE product_backlog.json" in result.stdout
    assert "CLEANUP temporary_dir_removed=true" in result.stdout


def test_backlog_fixture_preserves_file_when_two_invalid_updates_are_concurrent() -> None:
    # Given
    command_arguments = ("invalid-concurrent",)

    # When
    result = _run_fixture(*command_arguments)

    # Then
    assert result.returncode == 0, result.stderr
    assert "ASSERT error_events=2 file_unchanged=true status=PASS" in result.stdout
    assert "CLEANUP temporary_dir_removed=true" in result.stdout


def test_backlog_fixture_treats_injected_text_as_data_when_injection_is_requested() -> None:
    # Given
    command_arguments = ("injection",)

    # When
    result = _run_fixture(*command_arguments)

    # Then
    assert result.returncode == 0, result.stderr
    assert "ASSERT untrusted_text_preserved=true status=PASS" in result.stdout
