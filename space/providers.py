from __future__ import annotations

import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import Final, ParamSpec, Protocol, Self, TypeVar, final

import httpx
from pydantic import TypeAdapter, ValidationError

from space.contracts import ProviderSelection

P = ParamSpec("P")
R = TypeVar("R")
GpuDecorator = Callable[[Callable[..., Awaitable[str]]], Callable[..., Awaitable[str]]]


def _identity_gpu(function: Callable[P, R]) -> Callable[P, R]:
    return function


try:
    _gpu_decorator: GpuDecorator = getattr(import_module("spaces"), "GPU", _identity_gpu)
except ModuleNotFoundError:
    _gpu_decorator = _identity_gpu


OPENROUTER_ENDPOINT: Final[str] = "https://openrouter.ai/api/v1"
DEFAULT_ALLOWED_MODELS: Final[tuple[str, ...]] = ("openai/gpt-4o-mini",)


class SpaceProviderError(Exception):
    pass


class InvalidModelError(SpaceProviderError):
    pass


class ProviderRateLimitError(SpaceProviderError):
    pass


class ProviderTimeoutError(SpaceProviderError):
    pass


class ProviderUnavailableError(SpaceProviderError):
    pass


class ProviderResponseError(SpaceProviderError):
    pass


@dataclass(frozen=True, slots=True)
class SpaceProviderConfig:
    allowed_models: tuple[str, ...] = DEFAULT_ALLOWED_MODELS
    byok_model: str = "openai/gpt-4o-mini"
    bonsai_endpoint: str | None = None
    bonsai_model: str | None = None
    timeout_s: float = 10.0
    max_output_tokens: int = 512
    requests_per_window: int = 6
    rate_window_s: float = 60.0

    def __post_init__(self) -> None:
        if not self.allowed_models:
            raise ValueError("allowed_models must not be empty")
        if self.timeout_s <= 0 or self.max_output_tokens <= 0:
            raise ValueError("provider limits must be positive")
        if self.requests_per_window <= 0 or self.rate_window_s <= 0:
            raise ValueError("rate limits must be positive")
        if self.byok_model not in self.allowed_models:
            raise InvalidModelError("BYOK model is not allowed")
        if self.bonsai_model is not None and self.bonsai_model not in self.allowed_models:
            raise InvalidModelError("Bonsai model is not allowed")

    @classmethod
    def from_env(cls) -> Self:
        raw_model = os.getenv("KATETO_SPACE_BYOK_MODEL", cls.byok_model)
        bonsai_model = os.getenv("KATETO_SPACE_BONSAI_MODEL")
        bonsai_endpoint = os.getenv("KATETO_SPACE_BONSAI_ENDPOINT")
        allowed = tuple(
            item.strip()
            for item in os.getenv("KATETO_SPACE_ALLOWED_MODELS", ",".join(DEFAULT_ALLOWED_MODELS)).split(",")
            if item.strip()
        )
        return cls(
            allowed_models=allowed,
            byok_model=raw_model,
            bonsai_endpoint=bonsai_endpoint,
            bonsai_model=bonsai_model,
        )


class SpaceProvider(Protocol):
    name: str

    def reserve_request(self) -> None: ...

    async def complete(self, prompt: str) -> str: ...


@final
class _CompatibleProvider:
    name: str
    _endpoint: str
    _model: str
    _config: SpaceProviderConfig
    _headers: dict[str, str]
    _client: httpx.AsyncClient | None

    def __init__(
        self,
        *,
        name: str,
        endpoint: str,
        model: str,
        config: SpaceProviderConfig,
        headers: Mapping[str, str],
        client: httpx.AsyncClient | None,
    ) -> None:
        self.name = name
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._config = config
        self._headers = dict(headers)
        self._client = client
        self._request_times: list[float] = []

    def reserve_request(self) -> None:
        now = time.monotonic()
        self._request_times = [stamp for stamp in self._request_times if now - stamp < self._config.rate_window_s]
        if len(self._request_times) >= self._config.requests_per_window:
            raise ProviderRateLimitError("provider request limit reached; retry later")
        self._request_times.append(now)

    async def complete(self, prompt: str) -> str:
        self.reserve_request()
        return await _gpu_inference(self, prompt)

    async def request(self, prompt: str) -> str:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self._config.max_output_tokens,
        }
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=self._config.timeout_s) as client:
                    response = await client.post(f"{self._endpoint}/chat/completions", json=payload, headers=self._headers)
            else:
                response = await self._client.post(
                    f"{self._endpoint}/chat/completions",
                    json=payload,
                    headers=self._headers,
                    timeout=self._config.timeout_s,
                )
            _ = response.raise_for_status()
            body = TypeAdapter(dict[str, object]).validate_json(response.content)
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ValueError("response choices are invalid")
            typed_choices = TypeAdapter(list[dict[str, object]]).validate_python(choices)
            message = typed_choices[0].get("message")
            if not isinstance(message, dict):
                raise ValueError("response message is invalid")
            content = TypeAdapter(dict[str, object]).validate_python(message).get("content")
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError(f"{self.name} provider timed out") from error
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError) as error:
            raise ProviderResponseError(f"{self.name} provider returned an invalid response") from error
        if not isinstance(content, str) or not content.strip():
            raise ProviderResponseError(f"{self.name} provider returned empty output")
        if len(content) > self._config.max_output_tokens * 4:
            raise ProviderResponseError(f"{self.name} provider exceeded the output cap")
        return content


@_gpu_decorator
async def _gpu_inference(provider: _CompatibleProvider, prompt: str) -> str:
    return await provider.request(prompt)


@final
class FixtureProvider:
    name = "fixture"

    def reserve_request(self) -> None:
        return None

    async def complete(self, prompt: str) -> str:
        if prompt == "provider-error":
            raise ProviderUnavailableError("fixture provider is unavailable")
        return f"Plan ready for: {prompt}"


def build_provider(
    selection: ProviderSelection,
    config: SpaceProviderConfig,
    *,
    client: httpx.AsyncClient | None = None,
) -> SpaceProvider:
    if selection.provider == "byok":
        return _CompatibleProvider(
            name="openrouter",
            endpoint=OPENROUTER_ENDPOINT,
            model=config.byok_model,
            config=config,
            headers={"Authorization": f"Bearer {selection.session_key}"},
            client=client,
        )
    if config.bonsai_endpoint is None or config.bonsai_model is None:
        raise ProviderUnavailableError("Bonsai provider is not configured")
    return _CompatibleProvider(
        name="bonsai",
        endpoint=config.bonsai_endpoint,
        model=config.bonsai_model,
        config=config,
        headers={},
        client=client,
    )
