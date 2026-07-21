import pytest
import httpx
import json

from space.app import accept_provider, select_provider
from space.contracts import MAX_BYOK_KEY_LENGTH, ProviderChoiceError, ProviderSelection
from space.providers import (
    InvalidModelError,
    ProviderRateLimitError,
    SpaceProviderConfig,
    build_provider,
)


def test_bonsai_selection_does_not_require_a_key() -> None:
    selection = select_provider("Bonsai", "")

    assert selection == ProviderSelection(provider="bonsai", session_key=None)


def test_none_provider_is_rejected_at_selection_boundary() -> None:
    with pytest.raises(ProviderChoiceError):
        _ = select_provider(None, "")


def test_byok_selection_requires_a_bounded_key() -> None:
    selection = select_provider("BYOK", "sk-test-key")

    assert selection == ProviderSelection(provider="byok", session_key="sk-test-key")


def test_accept_provider_invokes_runtime_seam_only_after_valid_selection() -> None:
    received: list[ProviderSelection] = []

    status = accept_provider("Bonsai", "", received.append)

    assert received == [ProviderSelection(provider="bonsai", session_key=None)]
    assert "provider: Bonsai" in status
    assert "sk-" not in status


@pytest.mark.parametrize(
    "raw_provider, raw_key",
    [
        ("", "sk-test-key"),
        ("Unknown", "sk-test-key"),
        ("BYOK", ""),
        ("BYOK", "   "),
        ("BYOK", "x" * (MAX_BYOK_KEY_LENGTH + 1)),
    ],
)
def test_malformed_provider_input_is_rejected(raw_provider: str, raw_key: str) -> None:
    with pytest.raises(ProviderChoiceError):
        _ = select_provider(raw_provider, raw_key)


def test_provider_selection_routes_byok_to_openrouter_and_bonsai_without_key() -> None:
    config = SpaceProviderConfig(
        allowed_models=("test/model",),
        byok_model="test/model",
        bonsai_endpoint="http://bonsai.test/v1",
        bonsai_model="test/model",
    )

    assert build_provider(ProviderSelection("byok", "sk-session"), config).name == "openrouter"
    assert build_provider(ProviderSelection("bonsai", None), config).name == "bonsai"


def test_invalid_model_is_rejected_before_provider_call() -> None:
    with pytest.raises(InvalidModelError):
        _ = SpaceProviderConfig(
            allowed_models=("allowed/model",),
            byok_model="blocked/model",
            bonsai_endpoint="http://bonsai.test/v1",
            bonsai_model="allowed/model",
        )


def test_provider_config_bounds_requests_and_output() -> None:
    config = SpaceProviderConfig(
        allowed_models=("test/model",),
        byok_model="test/model",
        bonsai_endpoint="http://bonsai.test/v1",
        bonsai_model="test/model",
        timeout_s=3,
        max_output_tokens=128,
        requests_per_window=1,
    )

    assert config.timeout_s == 3
    assert config.max_output_tokens == 128
    assert config.requests_per_window == 1
    provider = build_provider(ProviderSelection("bonsai", None), config)
    provider.reserve_request()
    with pytest.raises(ProviderRateLimitError):
        provider.reserve_request()


@pytest.mark.asyncio
async def test_openrouter_provider_uses_session_key_and_output_cap_without_returning_key() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["payload"] = request.read().decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "model result"}}]})

    config = SpaceProviderConfig(
        allowed_models=("test/model",),
        byok_model="test/model",
        bonsai_endpoint="http://bonsai.test/v1",
        bonsai_model="test/model",
        max_output_tokens=12,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = build_provider(ProviderSelection("byok", "sk-session"), config, client=client)
        result = await provider.complete("plan this")

    assert result == "model result"
    assert seen["authorization"] == "Bearer sk-session"
    assert json.loads(seen["payload"])["max_tokens"] == 12
