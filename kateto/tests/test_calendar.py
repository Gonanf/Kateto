from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import SecretStr

from kateto.core import PluginManager
from kateto.plugins.connector.calendar import (
    CalendarEvent,
    CalendarEventCreatedData,
    CalendarErrorData,
    CalendarEventsData,
    CalendarGetData,
    CalendarSetData,
    GoogleCalendarConnector,
    GoogleInstalledAppOAuthAdapter,
    GoogleTokenCache,
    OAuthToken,
)


@dataclass(frozen=True, slots=True)
class FixtureCredentials:
    token: str
    refresh_token: str | None
    expiry: datetime | None


@dataclass(slots=True)
class FixtureInstalledAppFlow:
    credentials: FixtureCredentials
    calls: int = 0

    def run_local_server(self, *, port: int) -> FixtureCredentials:
        assert port == 0
        self.calls += 1
        return self.credentials


@dataclass(slots=True)
class FixtureCalendarTransport:
    events: tuple[CalendarEvent, ...] = ()
    delay_seconds: float = 0.0
    cancelled: bool = False
    created: list[CalendarEvent] = field(default_factory=list)
    requested_tokens: list[str] = field(default_factory=list)

    async def get_events(self, *, token: OAuthToken, request: CalendarGetData) -> tuple[CalendarEvent, ...]:
        self.requested_tokens.append(token.access_token.get_secret_value())
        try:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return self.events

    async def create_event(self, *, token: OAuthToken, request: CalendarSetData) -> CalendarEvent:
        self.requested_tokens.append(token.access_token.get_secret_value())
        self.created.append(request.event)
        return request.event


def _event() -> CalendarEvent:
    starts_at = datetime(2026, 7, 15, 12, tzinfo=UTC)
    return CalendarEvent(
        id="calendar-event-1",
        summary="Daily standup",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
    )


def _connector(
    tmp_path: Path,
    *,
    transport: FixtureCalendarTransport,
    flow: FixtureInstalledAppFlow,
    timeout_seconds: float = 0.1,
) -> GoogleCalendarConnector:
    return GoogleCalendarConnector(
        config_dir=tmp_path,
        transport=transport,
        oauth=GoogleInstalledAppOAuthAdapter(flow),
        timeout_seconds=timeout_seconds,
    )


@pytest.mark.asyncio
async def test_google_token_cache_round_trips_without_exposing_secrets_when_set_then_get(tmp_path: Path) -> None:
    # Given
    token_path = tmp_path / "secrets" / "google-calendar-token.json"
    cache = GoogleTokenCache(token_path)
    token = OAuthToken(
        access_token=SecretStr("access-token-value"),
        refresh_token=SecretStr("refresh-token-value"),
        expires_at=datetime(2026, 7, 15, 13, tzinfo=UTC),
    )

    # When
    await cache.set(token)
    loaded = await cache.get()

    # Then
    assert token_path.is_file()
    assert loaded == token
    assert "access-token-value" not in repr(loaded)
    assert "refresh-token-value" not in repr(loaded)


@pytest.mark.asyncio
async def test_calendar_get_uses_cached_token_and_targets_typed_reply_when_requested(tmp_path: Path) -> None:
    # Given
    transport = FixtureCalendarTransport(events=(_event(),))
    flow = FixtureInstalledAppFlow(
        FixtureCredentials("flow-token", "flow-refresh", datetime(2026, 7, 15, 13, tzinfo=UTC)),
    )
    connector = _connector(tmp_path, transport=transport, flow=flow)
    cache = GoogleTokenCache(tmp_path / "secrets" / "google-calendar-token.json")
    await cache.set(OAuthToken(access_token=SecretStr("cached-token")))
    manager = PluginManager()
    await manager.enable_plugin(connector)
    request = CalendarGetData(
        starts_at=datetime(2026, 7, 15, 0, tzinfo=UTC),
        ends_at=datetime(2026, 7, 16, 0, tzinfo=UTC),
        reply_to="doktor",
        correlation_id="get-1",
    )

    # When
    await manager.emit("calendar_get", request, source="voice")
    await manager.wait_for_idle()

    # Then
    responses = [event for event in manager.get_events() if event.name == "calendar_events"]
    assert len(responses) == 1
    assert responses[0].target == "doktor"
    assert isinstance(responses[0].data, CalendarEventsData)
    assert responses[0].data.correlation_id == "get-1"
    assert responses[0].data.events == [_event()]
    assert transport.requested_tokens == ["cached-token"]
    assert flow.calls == 0
    await manager.close()


@pytest.mark.asyncio
async def test_calendar_set_runs_installed_app_flow_caches_token_and_returns_typed_reply_when_missing_cache(
    tmp_path: Path,
) -> None:
    # Given
    transport = FixtureCalendarTransport()
    flow = FixtureInstalledAppFlow(
        FixtureCredentials("flow-token", "flow-refresh", datetime(2026, 7, 15, 13, tzinfo=UTC)),
    )
    connector = _connector(tmp_path, transport=transport, flow=flow)
    manager = PluginManager()
    await manager.enable_plugin(connector)
    request = CalendarSetData(event=_event(), reply_to="jane", correlation_id="set-1")

    # When
    await manager.emit("calendar_set", request, source="voice")
    await manager.wait_for_idle()

    # Then
    responses = [event for event in manager.get_events() if event.name == "calendar_event_created"]
    assert len(responses) == 1
    assert responses[0].target == "jane"
    assert isinstance(responses[0].data, CalendarEventCreatedData)
    assert responses[0].data.correlation_id == "set-1"
    assert responses[0].data.event == _event()
    assert transport.created == [_event()]
    assert flow.calls == 1
    assert (tmp_path / "secrets" / "google-calendar-token.json").is_file()
    await manager.close()


@pytest.mark.asyncio
async def test_calendar_emits_bounded_timeout_failure_without_leaking_token_when_transport_stalls(
    tmp_path: Path,
) -> None:
    # Given
    transport = FixtureCalendarTransport(delay_seconds=1)
    flow = FixtureInstalledAppFlow(FixtureCredentials("secret-token", None, None))
    connector = _connector(tmp_path, transport=transport, flow=flow, timeout_seconds=0.01)
    manager = PluginManager()
    await manager.enable_plugin(connector)
    request = CalendarGetData(
        starts_at=datetime(2026, 7, 15, 0, tzinfo=UTC),
        ends_at=datetime(2026, 7, 16, 0, tzinfo=UTC),
        reply_to="conquest",
        correlation_id="timeout-1",
    )

    # When
    await manager.emit("calendar_get", request, source="voice")
    await manager.wait_for_idle()

    # Then
    failures = [
        (event.target, event.data)
        for event in manager.get_events()
        if event.name == "calendar_error" and isinstance(event.data, CalendarErrorData)
    ]
    assert len(failures) == 1
    failure_target, failure = failures[0]
    assert failure_target == "conquest"
    assert failure.correlation_id == "timeout-1"
    assert failure.code == "timeout"
    assert "secret-token" not in failure.message
    assert transport.cancelled
    await manager.close()


@pytest.mark.asyncio
async def test_calendar_emits_cache_failure_without_rewriting_stale_json_when_cache_is_malformed(tmp_path: Path) -> None:
    # Given
    token_path = tmp_path / "secrets" / "google-calendar-token.json"
    token_path.parent.mkdir(parents=True)
    stale_json = "{\"access_token\": [\"wrong-shape\"]}"
    token_path.write_text(stale_json, encoding="utf-8")
    transport = FixtureCalendarTransport()
    flow = FixtureInstalledAppFlow(FixtureCredentials("secret-token", None, None))
    connector = _connector(tmp_path, transport=transport, flow=flow)
    manager = PluginManager()
    await manager.enable_plugin(connector)
    request = CalendarGetData(
        starts_at=datetime(2026, 7, 15, 0, tzinfo=UTC),
        ends_at=datetime(2026, 7, 16, 0, tzinfo=UTC),
        reply_to="doktor",
        correlation_id="stale-cache-1",
    )

    # When
    await manager.emit("calendar_get", request, source="voice")
    await manager.wait_for_idle()

    # Then
    failures = [
        (event.target, event.data)
        for event in manager.get_events()
        if event.name == "calendar_error" and isinstance(event.data, CalendarErrorData)
    ]
    assert len(failures) == 1
    failure_target, failure = failures[0]
    assert failure_target == "doktor"
    assert failure.code == "token_cache"
    assert "secret-token" not in failure.message
    assert token_path.read_text(encoding="utf-8") == stale_json
    assert flow.calls == 0
    await manager.close()
