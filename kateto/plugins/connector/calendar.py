from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator

from kateto.core.event import EventModel
from kateto.core.plugin import Plugin
from kateto.core.storage import atomic_write_text


@dataclass(slots=True)
class CalendarFailure(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


class CalendarEvent(EventModel):
    id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    starts_at: datetime
    ends_at: datetime
    description: str = ""

    @field_validator("starts_at", "ends_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("calendar timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ensure_positive_duration(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("calendar event must end after it starts")
        return self


class CalendarGetData(EventModel):
    calendar_id: str = Field(default="primary", min_length=1)
    starts_at: datetime
    ends_at: datetime
    reply_to: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("calendar timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ensure_range(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("calendar query must end after it starts")
        return self


class CalendarSetData(EventModel):
    calendar_id: str = Field(default="primary", min_length=1)
    event: CalendarEvent
    reply_to: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)


class CalendarEventsData(EventModel):
    events: list[CalendarEvent]
    correlation_id: str = Field(min_length=1)


class CalendarEventCreatedData(EventModel):
    event: CalendarEvent
    correlation_id: str = Field(min_length=1)


class CalendarErrorData(EventModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)


class OAuthToken(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    access_token: SecretStr
    refresh_token: SecretStr | None = None
    expires_at: datetime | None = None


class InstalledAppCredentials(Protocol):
    @property
    def token(self) -> str: ...

    @property
    def refresh_token(self) -> str | None: ...

    @property
    def expiry(self) -> datetime | None: ...


class InstalledAppFlow(Protocol):
    def run_local_server(self, *, port: int) -> InstalledAppCredentials: ...


class OAuthTokenProvider(Protocol):
    async def get_token(self) -> OAuthToken: ...


class CalendarTransport(Protocol):
    async def get_events(self, *, token: OAuthToken, request: CalendarGetData) -> tuple[CalendarEvent, ...]: ...

    async def create_event(self, *, token: OAuthToken, request: CalendarSetData) -> CalendarEvent: ...


GOOGLE_CALENDAR_ENDPOINT = "https://www.googleapis.com/calendar/v3"
GOOGLE_CALENDAR_SCOPES = ("https://www.googleapis.com/auth/calendar",)


class GoogleCalendarHttpTransport:
    """Call the Google Calendar REST API using the connector's cached token."""

    def __init__(self, endpoint: str = GOOGLE_CALENDAR_ENDPOINT) -> None:
        if not endpoint.startswith(("http://", "https://")):
            raise CalendarFailure(code="endpoint", message="calendar endpoint must be an http(s) URL")
        self._endpoint = endpoint.rstrip("/")

    async def get_events(self, *, token: OAuthToken, request: CalendarGetData) -> tuple[CalendarEvent, ...]:
        params = {
            "timeMin": request.starts_at.isoformat(),
            "timeMax": request.ends_at.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        payload = await self._request(
            "GET",
            f"/calendars/{request.calendar_id}/events",
            token=token,
            params=params,
        )
        raw_events = payload.get("items", [])
        if not isinstance(raw_events, list):
            raise CalendarFailure(code="response", message="Google Calendar returned an invalid events list")
        return tuple(_calendar_event_from_google(item) for item in raw_events if isinstance(item, dict))

    async def create_event(self, *, token: OAuthToken, request: CalendarSetData) -> CalendarEvent:
        event = request.event
        payload = await self._request(
            "POST",
            f"/calendars/{request.calendar_id}/events",
            token=token,
            json_payload={
                "summary": event.summary,
                "description": event.description,
                "start": {"dateTime": event.starts_at.isoformat()},
                "end": {"dateTime": event.ends_at.isoformat()},
            },
        )
        return _calendar_event_from_google(payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: OAuthToken,
        params: dict[str, str] | None = None,
        json_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.request(
                    method,
                    f"{self._endpoint}{path}",
                    headers={"Authorization": f"Bearer {token.access_token.get_secret_value()}"},
                    params=params,
                    json=json_payload,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as error:
            raise CalendarFailure(code="http", message=f"Google Calendar rejected the request ({error.response.status_code})") from error
        except (httpx.HTTPError, ValueError) as error:
            raise CalendarFailure(code="http", message="Google Calendar endpoint is unavailable") from error
        if not isinstance(payload, dict):
            raise CalendarFailure(code="response", message="Google Calendar returned an invalid response")
        return payload


def _calendar_event_from_google(raw: dict[str, object]) -> CalendarEvent:
    event_id = raw.get("id")
    summary = raw.get("summary")
    start = raw.get("start")
    end = raw.get("end")
    if not isinstance(event_id, str) or not isinstance(summary, str) or not isinstance(start, dict) or not isinstance(end, dict):
        raise CalendarFailure(code="response", message="Google Calendar returned an incomplete event")
    starts_at = start.get("dateTime")
    ends_at = end.get("dateTime")
    if not isinstance(starts_at, str) or not isinstance(ends_at, str):
        raise CalendarFailure(code="response", message="Google Calendar returned an event without timestamps")
    description = raw.get("description", "")
    return CalendarEvent(
        id=event_id,
        summary=summary,
        starts_at=datetime.fromisoformat(starts_at),
        ends_at=datetime.fromisoformat(ends_at),
        description=description if isinstance(description, str) else "",
    )


class GoogleInstalledAppOAuthAdapter:
    def __init__(self, flow: InstalledAppFlow) -> None:
        self._flow = flow

    async def get_token(self) -> OAuthToken:
        credentials = await asyncio.to_thread(self._flow.run_local_server, port=0)
        if not credentials.token:
            raise CalendarFailure(code="oauth", message="installed-app OAuth returned no access token")
        return OAuthToken(
            access_token=SecretStr(credentials.token),
            refresh_token=SecretStr(credentials.refresh_token) if credentials.refresh_token else None,
            expires_at=credentials.expiry,
        )


def build_google_calendar_connector(
    config_dir: Path,
    *,
    endpoint: str | None = None,
) -> GoogleCalendarConnector:
    """Build the production Calendar connector from local installed-app credentials."""
    credentials_path = config_dir / "secrets" / "google-calendar-credentials.json"
    if not credentials_path.is_file():
        raise CalendarFailure(
            code="credentials",
            message=(
                f"Google Calendar credentials are missing at {credentials_path}; "
                "download an installed-app OAuth client JSON there"
            ),
        )
    try:
        flow_module = importlib.import_module("google_auth_oauthlib.flow")
    except ModuleNotFoundError as error:
        raise CalendarFailure(
            code="credentials",
            message="Google Calendar OAuth support is unavailable; install google-auth-oauthlib",
        ) from error
    flow_type = getattr(flow_module, "InstalledAppFlow")
    flow = flow_type.from_client_secrets_file(str(credentials_path), list(GOOGLE_CALENDAR_SCOPES))
    return GoogleCalendarConnector(
        config_dir=config_dir,
        transport=GoogleCalendarHttpTransport(endpoint or GOOGLE_CALENDAR_ENDPOINT),
        oauth=GoogleInstalledAppOAuthAdapter(flow),
    )


class GoogleTokenCache:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    async def get(self) -> OAuthToken | None:
        if not self.path.is_file():
            return None
        try:
            contents = self.path.read_text(encoding="utf-8")
        except OSError as error:
            raise CalendarFailure(code="token_cache", message="calendar token cache is unreadable") from error
        try:
            return OAuthToken.model_validate_json(contents)
        except ValidationError as error:
            raise CalendarFailure(code="token_cache", message="calendar token cache is malformed") from error

    async def set(self, token: OAuthToken) -> None:
        payload = {
            "access_token": token.access_token.get_secret_value(),
            "refresh_token": token.refresh_token.get_secret_value() if token.refresh_token else None,
            "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        }
        contents = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        await atomic_write_text(self.path, f"{contents}\n")


class GoogleCalendarConnector(Plugin):
    def __init__(
        self,
        *,
        config_dir: Path,
        transport: CalendarTransport,
        oauth: OAuthTokenProvider,
        timeout_seconds: float = 5.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("calendar timeout must be positive")
        super().__init__("connector_calendar", capabilities=("calendar",))
        self._transport = transport
        self._oauth = oauth
        self._timeout_seconds = timeout_seconds
        self._token_cache = GoogleTokenCache(config_dir / "secrets" / "google-calendar-token.json")

    async def initialize(self) -> None:
        if self.manager is None:
            raise RuntimeError("calendar connector requires a plugin manager")
        self.manager.register_event("calendar_get", CalendarGetData)
        self.manager.register_event("calendar_set", CalendarSetData)
        self.manager.register_event("calendar_events", CalendarEventsData)
        self.manager.register_event("calendar_event_created", CalendarEventCreatedData)
        self.manager.register_event("calendar_error", CalendarErrorData)

    async def on_calendar_get(self, data: CalendarGetData) -> None:
        try:
            token = await self._token()
            events = await asyncio.wait_for(
                self._transport.get_events(token=token, request=data),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            await self._emit_error(data, CalendarFailure(code="timeout", message="calendar request timed out"))
            return
        except CalendarFailure as error:
            await self._emit_error(data, error)
            return
        await self._manager_emit(
            "calendar_events",
            CalendarEventsData(events=list(events), correlation_id=data.correlation_id),
            target=data.reply_to,
        )

    async def on_calendar_set(self, data: CalendarSetData) -> None:
        try:
            token = await self._token()
            event = await asyncio.wait_for(
                self._transport.create_event(token=token, request=data),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            await self._emit_error(data, CalendarFailure(code="timeout", message="calendar request timed out"))
            return
        except CalendarFailure as error:
            await self._emit_error(data, error)
            return
        await self._manager_emit(
            "calendar_event_created",
            CalendarEventCreatedData(event=event, correlation_id=data.correlation_id),
            target=data.reply_to,
        )

    async def _token(self) -> OAuthToken:
        cached_token = await self._token_cache.get()
        if cached_token is not None:
            return cached_token
        token = await self._oauth.get_token()
        await self._token_cache.set(token)
        return token

    async def _emit_error(self, request: CalendarGetData | CalendarSetData, error: CalendarFailure) -> None:
        await self._manager_emit(
            "calendar_error",
            CalendarErrorData(code=error.code, message=error.message, correlation_id=request.correlation_id),
            target=request.reply_to,
        )

    async def _manager_emit(self, event_name: str, data: EventModel, *, target: str) -> None:
        if self.manager is None:
            raise RuntimeError("calendar connector requires a plugin manager")
        await self.manager.emit(event_name, data, source=self.name, target=target)
