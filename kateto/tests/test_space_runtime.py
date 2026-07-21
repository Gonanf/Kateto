from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from space.app import submit_prompt
from space.contracts import ProviderSelection
from space.runtime import RuntimeSnapshot, create_runtime_session


@pytest.mark.asyncio
async def test_sessions_have_independent_event_state_and_structured_outputs() -> None:
    # Given: two provider selections made by two browser sessions.
    first = create_runtime_session(ProviderSelection(provider="byok", session_key="sk-first"))
    second = create_runtime_session(ProviderSelection(provider="bonsai", session_key=None))

    # When: each session sends one prompt through its own PluginManager.
    _ = await first.prompt("plan the first release")
    _ = await second.prompt("plan the second release")

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
    _ = await session.prompt("plan cleanup")
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
    _ = await session.prompt("provider-error")

    # Then: the bus records a notification and the session remains usable.
    failed_state = session.snapshot()
    assert any(notification["kind"] == "error" for notification in failed_state.notifications)
    _ = await session.prompt("plan after recovery")
    assert any(item["prompt"] == "plan after recovery" for item in session.snapshot().plans)
    await session.close()


def test_repeated_gradio_callbacks_reuse_one_session_runtime() -> None:
    # Given: one browser session and the synchronous Gradio callback seam.
    session = create_runtime_session(ProviderSelection(provider="bonsai", session_key=None))

    # When: the same session receives two prompts from separate callbacks.
    first_status, first_outputs = submit_prompt(session, "first callback")
    second_status, _ = submit_prompt(session, "second callback")

    # Then: both callbacks complete and retain the session's complete event history.
    assert "Runtime ready" in first_status
    assert "Runtime ready" in second_status
    assert [plan["prompt"] for plan in session.snapshot().plans] == [
        "first callback",
        "second callback",
    ]
    assert first_outputs["closed"] is False

    _ = session.close_sync()
    assert session.snapshot().closed


def test_concurrent_gradio_callbacks_share_one_session_runtime() -> None:
    # Given: one browser session with callbacks dispatched by separate workers.
    session = create_runtime_session(ProviderSelection(provider="bonsai", session_key=None))

    # When: two synchronous Gradio callbacks arrive at the same time.
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [
            workers.submit(submit_prompt, session, value)
            for value in ("parallel one", "parallel two")
        ]
        statuses = [future.result()[0] for future in futures]

    # Then: both callbacks use the same runtime loop and retain both plans.
    assert all("Runtime ready" in status for status in statuses)
    prompts = tuple(plan["prompt"] for plan in session.snapshot().plans)
    assert all(isinstance(prompt, str) for prompt in prompts)
    assert set(prompt for prompt in prompts if isinstance(prompt, str)) == {
        "parallel one",
        "parallel two",
    }
    session.close_sync()


def test_provider_key_is_absent_from_snapshot_outputs() -> None:
    # Given: a BYOK session with a credential that must remain session-private.
    session = create_runtime_session(ProviderSelection(provider="byok", session_key="sk-secret"))

    # When: the provider processes a prompt.
    _, outputs = submit_prompt(session, "private plan")

    # Then: no event-derived output contains the provider credential.
    assert "sk-secret" not in str(outputs)
    session.close_sync()


def test_gradio_callback_reports_degraded_status_for_provider_notification() -> None:
    # Given: a session whose fixture provider emits an error notification.
    session = create_runtime_session(ProviderSelection(provider="bonsai", session_key=None))

    # When: the callback submits the provider failure probe.
    status, outputs = submit_prompt(session, "provider-error")

    # Then: the browser receives an explicit degraded/error status, not success.
    assert "Runtime degraded" in status
    assert "Runtime ready" not in status
    assert outputs["notifications"]

    _ = session.close_sync()
