from dataclasses import dataclass


@dataclass(slots=True)
class ProviderConfigurationError(Exception):
    provider: str
    setting: str

    def __str__(self) -> str:
        return f"{self.provider} provider requires config setting {self.setting}"


@dataclass(slots=True)
class ProviderLifecycleError(Exception):
    provider: str
    reason: str

    def __str__(self) -> str:
        return f"{self.provider} provider lifecycle error: {self.reason}"


@dataclass(slots=True)
class MalformedUpstreamResponse(Exception):
    provider: str
    reason: str

    def __str__(self) -> str:
        return f"{self.provider} returned malformed upstream data: {self.reason}"


@dataclass(slots=True)
class UnsupportedAudioPayload(Exception):
    format: str

    def __str__(self) -> str:
        return f"unsupported audio payload format: {self.format}"
