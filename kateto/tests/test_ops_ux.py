from __future__ import annotations

from datetime import datetime, timezone

from kateto.cli.doctor import (
    DoctorEnv,
    CheckResult,
    OllamaStatus,
    ServerStatus,
    check_config,
    check_keys,
    check_ollama_models,
    check_servers,
    check_vad,
    mask_key,
    run_doctor,
)
from kateto.cli.setup_wizard import deep_merge, dumps_toml, read_env_file, write_secrets
from kateto.cli.trace import EventTracer, TraceFilters, format_trace_line


class TestMaskKey:
    def test_masks_middle_of_key(self) -> None:
        assert mask_key("sk-ef23919x6599") == "sk-e...6599"

    def test_short_key_is_fully_masked(self) -> None:
        assert mask_key("abcdef") == "****"


class TestCheckConfig:
    _VALID = "[kateto]\nlog_level = 'INFO'\n[cli]\nallowlist = []\n"

    def test_valid_config_passes(self) -> None:
        assert check_config(self._VALID).ok is True

    def test_malformed_toml_fails(self) -> None:
        result = check_config("[plugin\nbad")
        assert result.ok is False
        assert "TOML" in result.detail

    def test_bad_schema_fails(self) -> None:
        result = check_config("[plugin]\nfoo = 'bar'\n")
        assert result.ok is False
        assert "foo" in result.detail


class TestCheckVad:
    def test_returns_result_without_crashing(self) -> None:
        assert isinstance(check_vad(), CheckResult)


class TestCheckKeys:
    def test_masked_present_key(self) -> None:
        raw = {
            "plugin": {
                "audio_output_camb": {"enabled": True, "api_key": "sk-ef23919x6599"}
            }
        }
        results = check_keys(raw)
        assert results and results[0].ok is True
        assert "sk-e...6599" in results[0].detail

    def test_missing_key_on_required_plugin_fails(self) -> None:
        raw = {"plugin": {"audio_output_camb": {"enabled": True, "api_key": ""}}}
        results = check_keys(raw)
        assert any(not result.ok for result in results)

    def test_env_reference_is_resolved(self) -> None:
        import os

        os.environ["KATETO_TEST_KEY"] = "sk-12345678"
        try:
            raw = {"plugin": {"audio_output_camb": {"enabled": True, "api_key": "env:KATETO_TEST_KEY"}}}
            results = check_keys(raw)
            assert any("sk-1...5678" in result.detail for result in results)
        finally:
            del os.environ["KATETO_TEST_KEY"]


class TestCheckServers:
    def test_unreachable_reports_actionable_message(self) -> None:
        env = DoctorEnv(config_text="", servers={"whisper": ServerStatus(reachable=False, error="conn refused")})
        results = check_servers(env)
        assert any(not result.ok and "doctor" in result.detail for result in results)


class TestCheckOllama:
    def test_unreachable_fails(self) -> None:
        env = DoctorEnv(config_text="", ollama=OllamaStatus(reachable=False, error="conn refused"))
        results = check_ollama_models(env)
        assert any(not result.ok for result in results)

    def test_no_tool_calling_fails_for_probed_model(self) -> None:
        env = DoctorEnv(
            config_text="",
            ollama=OllamaStatus(reachable=True, models=("llama3",), loaded=("llama3",), tool_calling=False, tool_probe_model="llama3"),
        )
        results = check_ollama_models(env)
        assert any("tools" in result.name and not result.ok for result in results)

    def test_skipped_when_no_ollama_endpoint(self) -> None:
        env = DoctorEnv(config_text="", ollama=None)
        results = check_ollama_models(env)
        assert all(result.ok for result in results)


class TestRunDoctor:
    def test_missing_config_fails(self) -> None:
        exit_code, results = run_doctor(DoctorEnv(config_text=None))
        assert exit_code != 0
        assert any(not result.ok for result in results)

    def test_injected_env_drives_report_without_network(self) -> None:
        env = DoctorEnv(
            config_text="[kateto]\nlog_level = 'INFO'\n[cli]\nallowlist = []\n",
            servers={"whisper": ServerStatus(reachable=True)},
            ollama=OllamaStatus(reachable=True, models=("llama3",), loaded=("llama3",), tool_calling=True, tool_probe_model="llama3"),
        )
        exit_code, results = run_doctor(env)
        assert exit_code == 0
        assert all(result.ok for result in results)


class TestDeepMerge:
    def test_overlay_wins_over_base(self) -> None:
        merged = deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"c": 3}})
        assert merged == {"a": {"b": 1, "c": 3}}

    def test_new_keys_are_added(self) -> None:
        merged = deep_merge({"a": 1}, {"b": 2})
        assert merged == {"a": 1, "b": 2}


class TestDumpsToml:
    def test_round_trips_scalars_and_lists(self) -> None:
        raw = {"plugin.voice_llm": {"endpoint": "http://127.0.0.1:8092/v1", "model": "voice", "stream": True}}
        text = dumps_toml(raw)
        assert "[plugin.voice_llm]" in text
        assert 'endpoint = "http://127.0.0.1:8092/v1"' in text
        assert "stream = true" in text


class TestSecretsFile:
    def test_write_and_read_round_trip(self, tmp_path) -> None:
        path = write_secrets(tmp_path, {"KATETO_CAMB_API_KEY": "sk-12345678"})
        assert read_env_file(path) == {"KATETO_CAMB_API_KEY": "sk-12345678"}

    def test_read_ignores_comments_and_blank_lines(self, tmp_path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nKATETO_CAMB_API_KEY=sk-1\n")
        assert read_env_file(env_file) == {"KATETO_CAMB_API_KEY": "sk-1"}


class TestFormatTraceLine:
    def test_formats_timestamp_delta_and_targets(self) -> None:
        ts = datetime(2026, 8, 13, 12, 0, 0, 500_000, tzinfo=timezone.utc)
        line = format_trace_line(timestamp=ts, delta_ms=250, event="user_transcript", source="whisper", targets=("jane",))
        assert "12:00:00.500" in line
        assert "+   250ms" in line
        assert "user_transcript whisper -> jane" in line

    def test_no_targets_renders_dash(self) -> None:
        ts = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
        line = format_trace_line(timestamp=ts, delta_ms=0, event="pcm_frame", source="mic", targets=())
        assert "-> -" in line


class TestEventTracer:
    def test_delta_between_events(self) -> None:
        from kateto.core.event import EventEnvelope, EventModel

        lines: list[str] = []
        tracer = EventTracer(writer=lines.append)
        tracer._last_timestamp = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
        envelope = EventEnvelope(
            name="user_transcript",
            source="whisper",
            timestamp=datetime(2026, 8, 13, 12, 0, 0, 250_000, tzinfo=timezone.utc),
            data=EventModel(),
        )
        tracer._on_dispatch(envelope, ("jane",))
        assert "+   250ms" in lines[0]

    def test_event_filter_skips_non_matching(self) -> None:
        from kateto.core.event import EventEnvelope, EventModel

        lines: list[str] = []
        tracer = EventTracer(filters=TraceFilters(events=frozenset({"user_transcript"})), writer=lines.append)
        envelope = EventEnvelope(name="pcm_frame", source="mic", timestamp=datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc), data=EventModel())
        tracer._on_dispatch(envelope, ())
        assert lines == []

    def test_voice_filter_matches_target(self) -> None:
        from kateto.core.event import EventEnvelope, EventModel

        lines: list[str] = []
        tracer = EventTracer(filters=TraceFilters(voices=frozenset({"jane"})), writer=lines.append)
        envelope = EventEnvelope(name="voice_request", source="conquest", timestamp=datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc), data=EventModel())
        tracer._on_dispatch(envelope, ("jane",))
        assert len(lines) == 1