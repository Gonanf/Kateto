from __future__ import annotations

import pytest

from space.runtime import RuntimeSnapshot, SpaceRuntimeSession, create_runtime_session
from space.app import ProviderSelection


@pytest.mark.asyncio
async def test_sessions_have_independent_event_state_and_structured_outputs() -> None:
    # Given: two provider selections made by two browser sessions.
    first = create_runtime_session(ProviderSelection(provider="byok", session_key="sk-first"))
    second = create_runtime_session(ProviderSelection(provider="bonsai", session_key=None))

    # When: each session sends one prompt through its own PluginManager.
    await first.prompt("plan the first release")
    await second.prompt("plan the second release")

    # Then: event history and derived work state stay isolated and structured.
    first_state = first.snapshot()
    second_state = second.snapshot()
    assert isinstance(first_state, RuntimeSnapshot)
    assert first_state.provider == "byok"
    assert second_state.provider == "bonsai"
    assert any(item["prompt"] == "plan the first release" for item in first_state.plans)
    assert all(item["prompt"] != "plan the first release" for item in second_state.plans)
    assert first_state.agent_statuses
    assert first_state.workflows
    assert first_state.plugins
    assert first_state.mcp
    assert first_state.artifacts
    assert all("sk-first" not in str(item) for item in first_state.events)

    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_cleanup_closes_plugins_and_clears_provider_credentials() -> None:
    # Given: a started BYOK session holding a session-only credential.
    session = create_runtime_session(ProviderSelection(provider="byok", session_key="sk-secret"))
    await session.prompt("plan cleanup")
    assert session.has_session_credentials
    assert any(plugin.enabled for plugin in session.manager.get_plugins())

    # When: the browser session is unloaded.
    await session.close()

    # Then: every plugin is disabled and the credential is gone.
    assert not session.has_session_credentials
    assert all(not plugin.enabled for plugin in session.manager.get_plugins())
    assert session.snapshot().closed


@pytest.mark.asyncio
async def test_provider_failure_is_an_event_notification_and_runtime_survives() -> None:
    # Given: the deterministic fixture provider is selected.
    session = create_runtime_session(ProviderSelection(provider="bonsai", session_key=None))

    # When: the fixture provider reports an upstream failure.
    await session.prompt("provider-error")

    # Then: the bus records a notification and the session remains usable.
    failed_state = session.snapshot()
    assert any(notification["kind"] == "error" for notification in failed_state.notifications)
    await session.prompt("plan after recovery")
    assert any(item["prompt"] == "plan after recovery" for item in session.snapshot().plans)
    await session.close()
