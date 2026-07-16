from __future__ import annotations

import subprocess
import sys


def test_mcp_fixture_persists_the_expected_backlog_item_through_the_mcp_tool() -> None:
    # Given: the executable MCP QA fixture and its canonical backlog action.
    command = [sys.executable, "scripts/qa/mcp_fixture.py", "backlog_add"]

    # When: the fixture dispatches the generated MCP backlog_add tool.
    result = subprocess.run(command, check=False, capture_output=True, text=True)

    # Then: the canonical JSON mutation and atomic replacement are observable.
    assert result.returncode == 0, result.stderr
    assert "MCP_BACKLOG_ADD event=backlog_add target=backlog" in result.stdout
    assert "CANONICAL_STORE product_backlog.json" in result.stdout
    assert "ASSERT valid_json=true expected_item=true atomic_replace=true status=PASS" in result.stdout
    assert "CLEANUP temporary_dir_removed=true" in result.stdout
