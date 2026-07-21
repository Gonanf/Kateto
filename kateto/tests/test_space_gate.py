import pytest

from space.app import accept_provider, select_provider
from space.contracts import MAX_BYOK_KEY_LENGTH, ProviderChoiceError, ProviderSelection


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
