from __future__ import annotations

from pathlib import Path

from kateto.core.config import load_config
from kateto.live import build_event_runtime


class QuietVad:
    def is_speech(self, samples: bytes) -> bool:
        return False


def test_packaged_defaults_assemble_classifier_fan_out(tmp_path: Path) -> None:
    # Given: a fresh user configuration bootstrapped from the shipped defaults.
    config = load_config(config_dir=tmp_path)

    # When: the default live graph is assembled without opening audio hardware.
    _, plugins = build_event_runtime(
        config,
        shared={"vad": QuietVad()},
    )

    # Then: the classifier and its P0 voice fan-out targets are present.
    plugin_names = {plugin.name for plugin in plugins}
    assert {"executor_classifier", "jane", "doktor", "conquest"} <= plugin_names
