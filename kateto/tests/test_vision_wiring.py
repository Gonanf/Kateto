"""Wiring tests for the static_vision executor plugin (plan todo 2).

Asserts factory behavior (presence/absence), NOT the todo-1 event contracts:
- `[plugin.executor_vision]` present -> factory includes `static_vision`.
- Section absent -> skipped silently, no error.
- `enabled = false` -> absent.
- `opted_in` built by the factory from the voice table (`vision_periodic`).
- Duplicate plugin name -> documented duplicate-name error.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from kateto.core.config import load_config
from kateto.core.discovery import DiscoveryContext
from kateto.core.manager import PluginManager
from kateto.plugins.executor import create_plugins
from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin

_MINIMAL_CONFIG = """\
[kateto]
debug = false

[cli]
allowlist = ["ls"]
"""


def _write_config(config_dir: Path, contents: str) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(contents, encoding="utf-8")


def _make_ctx(config_dir: Path) -> DiscoveryContext:
    loaded = load_config(config_dir=config_dir)
    return DiscoveryContext(config=loaded, shared={})


def _vision_plugins(ctx: DiscoveryContext) -> list[StaticVisionPlugin]:
    return [p for p in create_plugins(ctx) if p.name == "static_vision"]


def test_ctor_signature_matches_plan() -> None:
    # Given: the pinned ctor contract from the plan.
    sig = inspect.signature(StaticVisionPlugin.__init__)
    params = sig.parameters
    # Then: plan parameters in exact order with exact defaults
    # (plus a trailing capture_fps compat kwarg owned by the parallel lanes).
    assert list(params)[:7] == [
        "self",
        "settings",
        "name",
        "interval_seconds",
        "target_pid",
        "dept",
        "opted_in",
    ]
    assert params["settings"].default is None
    assert params["name"].default == "static_vision"
    assert params["name"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["interval_seconds"].default == 10.0
    assert params["target_pid"].default is None
    assert params["dept"].default == "fun"
    assert params["opted_in"].default == ()


def test_factory_includes_static_vision_when_section_present(tmp_path: Path) -> None:
    # Given: a config with the executor_vision section.
    config_dir = tmp_path / "kateto"
    _write_config(config_dir, _MINIMAL_CONFIG + '\n[plugin.executor_vision]\nwindow_secs = 5.0\n')

    # When: the executor factory runs.
    found = _vision_plugins(_make_ctx(config_dir))

    # Then: exactly one static_vision plugin with plan defaults.
    assert len(found) == 1
    plugin = found[0]
    assert isinstance(plugin, StaticVisionPlugin)
    assert plugin.name == "static_vision"
    assert plugin.source_default == "screen"
    assert plugin.window_secs == 5.0
    assert plugin.capture_fps == 1.0
    assert plugin.describe_interval == "30s"
    assert plugin.vision_max_tokens == 300
    assert plugin.vision_timeout == 60.0
    assert plugin.device_index == 0
    assert plugin.opted_in == ()


def test_factory_skips_silently_when_section_absent(tmp_path: Path) -> None:
    # Given: a config without the executor_vision section.
    config_dir = tmp_path / "kateto"
    _write_config(config_dir, _MINIMAL_CONFIG)

    # When: the executor factory runs.
    found = _vision_plugins(_make_ctx(config_dir))

    # Then: no vision plugin, and no error raised.
    assert found == []


def test_factory_respects_enabled_false(tmp_path: Path) -> None:
    # Given: the section present but disabled.
    config_dir = tmp_path / "kateto"
    _write_config(config_dir, _MINIMAL_CONFIG + "\n[plugin.executor_vision]\nenabled = false\n")

    # When: the executor factory runs.
    found = _vision_plugins(_make_ctx(config_dir))

    # Then: the plugin is absent.
    assert found == []


def test_factory_builds_opted_in_from_voice_table(tmp_path: Path) -> None:
    # Given: one opted-in voice with a custom interval, one plain voice.
    config_dir = tmp_path / "kateto"
    _write_config(
        config_dir,
        _MINIMAL_CONFIG
        + '\n[plugin.executor_vision]\n'
        + '\n[voice.jane]\nvision_periodic = true\nvision_interval = "10s"\n'
        + "\n[voice.doktor]\n",
    )

    # When: the executor factory runs.
    found = _vision_plugins(_make_ctx(config_dir))

    # Then: opted_in carries exactly the opted-in voice (factory-built).
    assert len(found) == 1
    assert found[0].opted_in == (("jane", "10s"),)


def test_factory_opted_in_defaults_to_30s(tmp_path: Path) -> None:
    # Given: an opted-in voice without an explicit interval.
    config_dir = tmp_path / "kateto"
    _write_config(
        config_dir,
        _MINIMAL_CONFIG + '\n[plugin.executor_vision]\n' + "\n[voice.jane]\nvision_periodic = true\n",
    )

    # When: the executor factory runs.
    found = _vision_plugins(_make_ctx(config_dir))

    # Then: the per-voice default interval applies.
    assert len(found) == 1
    assert found[0].opted_in == (("jane", "30s"),)


@pytest.mark.asyncio
async def test_duplicate_plugin_name_raises_documented_error() -> None:
    # Given: a fresh manager with static_vision already enabled.
    manager = PluginManager()
    await manager.enable_plugin(StaticVisionPlugin())

    # When/Then: enabling a second plugin under the same name raises.
    with pytest.raises(ValueError, match="plugin already registered: static_vision"):
        await manager.enable_plugin(StaticVisionPlugin())
