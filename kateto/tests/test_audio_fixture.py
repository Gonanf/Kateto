from __future__ import annotations

import subprocess
import sys


def test_audio_fixture_reports_happy_and_missing_device_outcomes() -> None:
    # Given: the deterministic fixture command and its built-in utterance WAV path.
    command = [sys.executable, "-m", "kateto.qa.audio_fixture"]

    # When: users run microphone capture and a missing Meet loopback device.
    microphone = subprocess.run(
        [*command, "--source", "mic", "--wav", "fixtures/utterance.wav"],
        capture_output=True,
        check=False,
        text=True,
    )
    missing_device = subprocess.run(
        [*command, "--source", "meet", "--device", "missing"],
        capture_output=True,
        check=False,
        text=True,
    )

    # Then: the fixture makes the audio/resume and failure/cleanup states observable.
    assert microphone.returncode == 0, microphone.stderr
    assert "audio_chunk" in microphone.stdout
    assert "resumed-listening" in microphone.stdout
    assert missing_device.returncode == 2
    assert "configured device 'missing'" in missing_device.stderr
    assert "capture_task=none" in missing_device.stderr
