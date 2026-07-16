from __future__ import annotations

import subprocess
import sys


def test_module_help_when_bootstrapped() -> None:
    # Given: the package is invoked through Python's module entry point.
    # When: a user asks for command help.
    completed_process = subprocess.run(
        [sys.executable, "-m", "kateto", "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    # Then: import and CLI help are both available to the caller.
    assert completed_process.returncode == 0, completed_process.stderr
    assert "kateto" in completed_process.stdout
