from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Final, Self

import httpx

from kateto.core.config import PluginSettings

from kateto.core.exceptions import ProviderError


DEFAULT_TIMEOUT_S: Final = 10.0


@dataclass(frozen=True, slots=True)
class SseEvent:
    event: str | None
    data: str


def configured_endpoint(
    settings: PluginSettings,
    *,
    provider: str,
    use_model_endpoint: bool = False,
    endpoint: str | None = None,
) -> str:
    configured = endpoint
    if configured is None:
        configured = settings.model_endpoint if use_model_endpoint else settings.endpoint
    if configured is None or not configured.strip():
        setting = "model_endpoint" if use_model_endpoint else "endpoint"
        raise ProviderError(f"{provider} missing required setting: {setting}")
    return configured.rstrip("/")


class HttpProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        endpoint: str,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if timeout_s <= 0:
            raise ProviderError(f"{provider_name} invalid timeout_s")
        self._provider_name = provider_name
        self._endpoint = endpoint
        self._provided_client = client
        self._client: httpx.AsyncClient | None = None
        self._owns_client = False
        self._active = False
        self._timeout_s = timeout_s
        self._headers = dict(headers) if headers is not None else {}

    @property
    def is_closed(self) -> bool:
        return self._client is None or self._client.is_closed

    async def __aenter__(self) -> Self:
        if self._active:
            raise ProviderError(f"{self._provider_name} already active")
        if self._provided_client is not None:
            if self._provided_client.is_closed:
                raise ProviderError(f"{self._provider_name} injected client is closed")
            self._client = self._provided_client
            self._owns_client = False
        else:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout_s), follow_redirects=True)
            self._owns_client = True
        self._active = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if not self._active:
            return
        client = self._client
        if client is not None and self._owns_client and not client.is_closed:
            await client.aclose()
        self._active = False

    def _client_or_raise(self) -> httpx.AsyncClient:
        client = self._client
        if not self._active or client is None or client.is_closed:
            raise ProviderError(f"{self._provider_name} used outside an active lifecycle")
        return client

    def _url(self, path: str) -> str:
        return f"{self._endpoint}/{path.lstrip('/')}"

    @property
    def _request_headers(self) -> Mapping[str, str]:
        return self._headers


async def iter_sse_events(response: httpx.Response) -> AsyncIterator[SseEvent]:
    event_name: str | None = None
    async for line in response.aiter_lines():
        if not line:
            event_name = None
            continue
        field, separator, value = line.partition(":")
        if not separator:
            continue
        match field:
            case "event":
                event_name = value.lstrip()
            case "data":
                yield SseEvent(event=event_name, data=value.lstrip())
            case _:
                continue
