from dataclasses import dataclass
from typing import Final, Literal

ProviderName = Literal["byok", "bonsai"]
MAX_BYOK_KEY_LENGTH: Final = 256


class ProviderChoiceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    provider: ProviderName
    session_key: str | None
