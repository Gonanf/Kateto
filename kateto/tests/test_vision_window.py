"""Todo 4-6 window tests: bounded ring buffer, webcam source, dHash dedupe.

Todo 7 consumes the buffer + dedupe; todo 9 extends lifecycle — keep every
test here additive.
"""

from __future__ import annotations

import sys
import types

import pytest

from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin


def _make_plugin(**kwargs):
    kwargs.setdefault("window_secs", 5.0)
    kwargs.setdefault("capture_fps", 2.0)  # maxlen = ceil(5 * 2) = 10
    return StaticVisionPlugin(**kwargs)


# --- Todo 4: bounded rolling window ---


def test_window_bounded_cap_and_dropped():
    # Given: maxlen-10 plugin
    plugin = _make_plugin()
    # When: 15 frames appended
    for i in range(15):
        plugin._append_frame("screen", b"frame-%d" % i, float(i))
    # Then: capped at 10, 5 evictions counted
    assert len(plugin._windows["screen"]) == 10
    assert plugin._dropped["screen"] == 5
    # And: newest frames kept (oldest evicted first)
    assert plugin._windows["screen"][0] == (14.0 - 9, b"frame-5")


def test_window_secs_invalid():
    # Given/When/Then: non-positive window_secs rejected at construction
    with pytest.raises(ValueError):
        StaticVisionPlugin(window_secs=0)
    with pytest.raises(ValueError):
        StaticVisionPlugin(window_secs=-1.5)


def test_encode_bounded_flat_and_gradient():
    # Given: synthetic flat + gradient images over the 640px side
    from kateto.plugins.executor.static_vision_plugin import _encode_bounded

    from PIL import Image

    flat = Image.new("RGB", (800, 600), (200, 30, 30))
    gradient = Image.new("RGB", (800, 600))
    pixels = gradient.load()
    assert pixels is not None
    for x in range(800):
        for y in range(600):
            pixels[x, y] = (x % 256, y % 256, (x + y) % 256)
    # When/Then: both encode within the 128KB cap
    assert len(_encode_bounded(flat)) <= 128 * 1024
    assert len(_encode_bounded(gradient)) <= 128 * 1024


def test_encode_bounded_noise_terminates_at_floor():
    # Given: worst-case noise (likely over cap even at q30)
    import random

    from kateto.plugins.executor.static_vision_plugin import _encode_bounded

    from PIL import Image

    rng = random.Random(42)
    noise = Image.new("RGB", (1280, 960))
    noise.putdata(
        [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(1280 * 960)]
    )
    # When/Then: terminates with bytes accepted as-is (floor — never raises)
    out = _encode_bounded(noise)
    assert isinstance(out, bytes) and len(out) > 0


def test_pil_absent_png_path_still_appends(monkeypatch):
    # Given: PIL (and mss) imports blocked
    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.setitem(sys.modules, "PIL.Image", None)
    monkeypatch.setitem(sys.modules, "mss", None)
    plugin = _make_plugin()
    # When: capture falls back to the uncapped dummy PNG path
    frame = plugin.capture_frame()
    plugin._append_frame("screen", frame, 1.0)
    # Then: bytes still land in the buffer, no raise
    assert isinstance(frame, bytes) and len(frame) > 0
    assert len(plugin._windows["screen"]) == 1


def test_webcam_buffer_independent_from_screen():
    # Given: frames in both sources beyond maxlen
    plugin = _make_plugin()
    for i in range(12):
        plugin._append_frame("screen", b"s%d" % i, float(i))
        plugin._append_frame("webcam", b"w%d" % i, float(i))
    # Then: each buffer capped independently with its own counter
    assert len(plugin._windows["screen"]) == 10
    assert len(plugin._windows["webcam"]) == 10
    assert plugin._dropped["screen"] == 2
    assert plugin._dropped["webcam"] == 2


# --- Todo 5: webcam source behind lazy cv2 import ---


class _FakeBuf:
    def tobytes(self):
        return b"fake-jpeg-bytes"


class _FakeCapture:
    def __init__(self, read_result):
        self.read_result = read_result
        self.set_calls: list[tuple[int, int]] = []
        self.released = False

    def set(self, prop, value):
        self.set_calls.append((prop, value))
        return True

    def isOpened(self):
        return True

    def read(self):
        return self.read_result

    def release(self):
        self.released = True


def _fake_cv2(monkeypatch, read_result=(True, object())):
    captures: list[_FakeCapture] = []

    def _capture(index):
        cap = _FakeCapture(read_result)
        captures.append(cap)
        return cap

    fake = types.ModuleType("cv2")
    fake.VideoCapture = _capture  # type: ignore[attr-defined]
    fake.imencode = lambda ext, frame, params: (True, _FakeBuf())  # type: ignore[attr-defined]
    fake.IMWRITE_JPEG_QUALITY = 1  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cv2", fake)
    return captures


def test_webcam_capture_mocked(monkeypatch):
    # Given: a mocked cv2 returning a frame
    captures = _fake_cv2(monkeypatch)
    plugin = _make_plugin()
    # When: webcam capture runs
    out = plugin._capture_webcam()
    # Then: JPEG bytes land in the webcam deque, no unavailability recorded
    assert out == b"fake-jpeg-bytes"
    assert len(captures) == 1
    assert len(plugin._windows["webcam"]) == 1
    assert plugin._windows["webcam"][0][1] == b"fake-jpeg-bytes"
    assert plugin._webcam_unavailable is None


def test_webcam_read_failure_records_reason(monkeypatch):
    # Given: cv2 whose read fails
    _fake_cv2(monkeypatch, read_result=(False, None))
    plugin = _make_plugin()
    # When/Then: reason recorded, no exception, bus idle (nothing appended)
    assert plugin._capture_webcam() is None
    assert plugin._webcam_unavailable is not None
    assert "read failed" in plugin._webcam_unavailable
    assert len(plugin._windows.get("webcam", ())) == 0


def test_webcam_absent_screen_still_works(monkeypatch):
    # Given: opencv missing entirely
    monkeypatch.setitem(sys.modules, "cv2", None)
    plugin = _make_plugin()
    # When/Then: unavailable reason, no exception — and screen capture unaffected
    assert plugin._capture_webcam() is None
    assert plugin._webcam_unavailable is not None
    assert "opencv" in plugin._webcam_unavailable
    assert isinstance(plugin.capture_frame(), bytes)
