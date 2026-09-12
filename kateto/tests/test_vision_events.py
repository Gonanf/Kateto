import pytest
from pydantic import ValidationError

from kateto.core.event import (
    VisionCaptureTriggerData,
    VisionDescribeRequestData,
    VisionDescribeResultData,
    VisionFrameData,
)


def test_vision_frame_defaults_source():
    # Given: an old payload without source
    # When: validated
    # Then: source defaults to screen
    data = VisionFrameData(frame=b"x", ts=1.0)
    assert data.source == "screen"
    assert data.dept == "fun"


def test_vision_frame_stale_payload_still_validates():
    # Given: old serialized payload without source
    # When: model_validate on raw dict
    # Then: validates with default
    data = VisionFrameData.model_validate({"frame": b"x", "ts": 1.0})
    assert data.source == "screen"


def test_vision_frame_rejects_extra_keys():
    # Given: unknown key
    # When: validated
    # Then: ValidationError (forbid holds)
    with pytest.raises(ValidationError):
        VisionFrameData(frame=b"x", ts=1.0, foo=1)


def test_capture_trigger_defaults():
    # Given: empty trigger
    # When: validated
    # Then: dept defaults to fun
    assert VisionCaptureTriggerData().dept == "fun"


def test_capture_trigger_rejects_extra_keys():
    # Given: unknown key
    # When: validated
    # Then: ValidationError
    with pytest.raises(ValidationError):
        VisionCaptureTriggerData(foo=1)


def test_describe_request_defaults():
    # Given: minimal request
    # When: validated
    # Then: source auto, optionals None
    data = VisionDescribeRequestData(requester="jane")
    assert data.source == "auto"
    assert data.window_secs is None
    assert data.max_images is None
    assert data.correlation_id is None


def test_describe_request_rejects_extra_keys():
    # Given: unknown key
    # When: validated
    # Then: ValidationError
    with pytest.raises(ValidationError):
        VisionDescribeRequestData(requester="jane", foo=1)


def test_describe_request_round_trip():
    # Given: a full request
    # When: dump + validate
    # Then: equal
    data = VisionDescribeRequestData(
        requester="jane", source="screen", window_secs=5.0, max_images=3, correlation_id="c1"
    )
    assert VisionDescribeRequestData.model_validate(data.model_dump()) == data


def test_describe_result_defaults():
    # Given: minimal result
    # When: validated
    # Then: via primary
    data = VisionDescribeResultData(
        text="hi", frame_count=3, kept_count=1, dropped=2, window_start=0.0, window_end=5.0, source="screen"
    )
    assert data.via == "primary"
    assert data.correlation_id is None


def test_describe_result_missing_text_rejected():
    # Given: payload without text
    # When: validated
    # Then: ValidationError
    with pytest.raises(ValidationError):
        VisionDescribeResultData(
            frame_count=3, kept_count=1, dropped=0, window_start=0.0, window_end=5.0, source="screen"
        )


def test_describe_result_rejects_extra_keys():
    # Given: unknown key
    # When: validated
    # Then: ValidationError
    with pytest.raises(ValidationError):
        VisionDescribeResultData(
            text="hi",
            frame_count=3,
            kept_count=1,
            dropped=0,
            window_start=0.0,
            window_end=5.0,
            source="screen",
            foo=1,
        )


def test_describe_result_round_trip():
    # Given: a full result
    # When: dump + validate
    # Then: equal
    data = VisionDescribeResultData(
        text="hi",
        frame_count=3,
        kept_count=1,
        dropped=2,
        window_start=0.0,
        window_end=5.0,
        source="auto",
        via="recap",
        correlation_id="c1",
    )
    assert VisionDescribeResultData.model_validate(data.model_dump()) == data
