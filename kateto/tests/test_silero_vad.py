from __future__ import annotations

import pytest

import kateto.plugins.audio_input.silero as silero_module
from kateto.plugins.audio_input.base import AudioInputConfigurationError
from kateto.plugins.audio_input.silero import (
    InstalledSileroBackend,
    SileroBackendUnavailableError,
    load_silero_model,
)


class DependencyMissingSileroModelLoader:
    def load_model(self) -> object:
        raise ModuleNotFoundError("No module named 'silero_vad'")


class ModelMissingSileroModelLoader:
    def load_model(self) -> object:
        raise FileNotFoundError("silero_vad/data/silero_vad.onnx")


def test_backend_reports_install_command_when_silero_runtime_is_missing() -> None:
    # Given: the configured Silero runtime dependency cannot be imported.
    backend = InstalledSileroBackend(model_loader=DependencyMissingSileroModelLoader())

    # When: live assembly requests its Silero model.
    with pytest.raises(SileroBackendUnavailableError, match=r"uv add silero-vad"):
        backend.load_model()

    # Then: startup stops with an actionable dependency remediation.


def test_backend_reports_model_remediation_when_silero_assets_are_missing() -> None:
    # Given: the Silero package exists but its packaged model assets are unavailable.
    backend = InstalledSileroBackend(model_loader=ModelMissingSileroModelLoader())

    # When: live assembly requests its Silero model.
    with pytest.raises(SileroBackendUnavailableError, match=r"reinstall `silero-vad`"):
        backend.load_model()

    # Then: startup stops with an actionable model remediation.


def test_loader_reports_missing_backend_as_audio_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: the production loader cannot import the installed Silero backend.
    def missing_backend(name: str) -> object:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(silero_module.importlib, "import_module", missing_backend)

    # When: configured live audio requests the real Silero model loader.
    with pytest.raises(AudioInputConfigurationError, match=r"uv add silero-vad torch"):
        load_silero_model()

    # Then: configuration fails with installation remediation at the audio boundary.
