"""Intervalo aleatorio dentro de un rango para la visión periódica.

El tick del scheduler corre al mínimo del rango; el plugin sortea un objetivo
en [min, max] por voz y sólo narra cuando el tiempo acumulado lo alcanza (más
el portón de imagen repetida, que evita el costo VLM). La fuente de azar se
inyecta (random.Random con seed o callable) para que todo sea determinista.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path

import pytest
from loguru import logger

from kateto.core.config import load_config
from kateto.core.discovery import DiscoveryContext
from kateto.core.event import ScheduleRequestData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.executor import create_plugins
from kateto.plugins.executor.scheduler import SchedulerPlugin
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


def _vision_plugins(ctx: DiscoveryContext) -> list[StaticVisionPlugin]:
    return [p for p in create_plugins(ctx) if p.name == "static_vision"]


def _waits(plugin: StaticVisionPlugin, voice: str, rounds: int) -> list[int]:
    waits: list[int] = []
    for _ in range(rounds):
        ticks = 0
        while not plugin._periodic_time_due(voice):
            ticks += 1
            assert ticks < 100, "time gate never opened"
        waits.append(int(plugin._vision_elapsed[voice]))
        plugin._after_narration(voice)
    return waits


def test_range_draws_within_range_and_not_constant() -> None:
    plugin = StaticVisionPlugin(
        opted_in=(("jane", "20s", "90s"),), rng=random.Random(7), config_dir=None
    )
    assert plugin._vision_range["jane"] == (20, 90)
    waits = _waits(plugin, "jane", 8)
    assert all(20 <= w <= 90 for w in waits)
    assert all(w % 20 == 0 for w in waits)
    assert len(set(waits)) > 1, f"waits look fixed: {waits}"


def test_same_seed_same_sequence() -> None:
    first = _waits(
        StaticVisionPlugin(
            opted_in=(("jane", "20s", "90s"),), rng=random.Random(7), config_dir=None
        ),
        "jane",
        6,
    )
    second = _waits(
        StaticVisionPlugin(
            opted_in=(("jane", "20s", "90s"),), rng=random.Random(7), config_dir=None
        ),
        "jane",
        6,
    )
    assert first == second


def test_callable_rng_supported() -> None:
    calls: list[tuple[int, int]] = []

    def fake_randint(lo: int, hi: int) -> int:
        calls.append((lo, hi))
        return hi

    plugin = StaticVisionPlugin(
        opted_in=(("jane", "20s", "90s"),), rng=fake_randint, config_dir=None
    )
    assert plugin._vision_next["jane"] == 80
    assert calls == [(1, 4)]


def test_waits_never_exceed_max_when_not_a_multiple() -> None:
    plugin = StaticVisionPlugin(
        opted_in=(("jane", "30s", "45s"),), rng=random.Random(3), config_dir=None
    )
    waits = _waits(plugin, "jane", 6)
    assert all(30 <= w <= 45 for w in waits)


def test_min_eq_max_behaves_fixed() -> None:
    plugin = StaticVisionPlugin(opted_in=(("jane", "30s", "30s"),), config_dir=None)
    assert plugin._vision_range["jane"] == (30, 30)
    assert "jane" not in plugin._vision_next
    assert all(plugin._periodic_time_due("jane") for _ in range(5))


def test_legacy_interval_unchanged() -> None:
    plugin = StaticVisionPlugin(opted_in=(("jane", "30s"),), config_dir=None)
    assert plugin._vision_range["jane"] == (30, 30)
    assert "jane" not in plugin._vision_next
    assert all(plugin._periodic_time_due("jane") for _ in range(5))


def test_min_gt_max_warns_and_stays_fixed() -> None:
    messages: list[str] = []
    sink = logger.add(messages.append, format="{message}")
    try:
        plugin = StaticVisionPlugin(opted_in=(("jane", "90s", "20s"),), config_dir=None)
    finally:
        logger.remove(sink)
    joined = "\n".join(messages)
    assert "invalid range" in joined and "jane" in joined
    lo, hi = plugin._vision_range["jane"]
    assert lo == hi
    assert all(plugin._periodic_time_due("jane") for _ in range(3))


def test_zero_min_warns_and_stays_fixed() -> None:
    messages: list[str] = []
    sink = logger.add(messages.append, format="{message}")
    try:
        plugin = StaticVisionPlugin(opted_in=(("jane", "0s", "90s"),), config_dir=None)
    finally:
        logger.remove(sink)
    assert "invalid range" in "\n".join(messages)
    lo, hi = plugin._vision_range["jane"]
    assert lo == hi and lo > 0


def test_factory_builds_range_and_single_sided_and_invalid(tmp_path: Path) -> None:
    config_dir = tmp_path / "kateto"
    _write_config(
        config_dir,
        _MINIMAL_CONFIG
        + "\n[plugin.executor_vision]\n"
        + '\n[voice.jane]\nvision_periodic = true\nvision_interval_min = "20s"\nvision_interval_max = "90s"\n'
        + '\n[voice.doktor]\nvision_periodic = true\nvision_interval_min = "45s"\n'
        + '\n[voice.conquest]\nvision_periodic = true\nvision_interval_min = "90s"\nvision_interval_max = "20s"\n',
    )
    loaded = load_config(config_dir=config_dir)
    found = _vision_plugins(DiscoveryContext(config=loaded, shared={}))
    assert len(found) == 1
    assert found[0].opted_in == (("jane", "20s", "90s"), ("doktor", "45s"), ("conquest", "30s"))


class _Voice(Plugin):
    def __init__(self, name: str = "jane") -> None:
        super().__init__(name=name, capabilities=("voice",))


class _ScheduleRequestRecorder(Plugin):
    def __init__(self) -> None:
        super().__init__(name="schedule_recorder")
        self.seen: list[ScheduleRequestData] = []

    async def on_schedule_request(self, data: ScheduleRequestData) -> None:
        self.seen.append(data)


@pytest.mark.asyncio
async def test_job_registered_with_minimum_interval() -> None:
    manager = PluginManager()
    scheduler = SchedulerPlugin()
    await manager.enable_plugin(scheduler)
    requests = _ScheduleRequestRecorder()
    await manager.enable_plugin(requests)
    await manager.enable_plugin(_Voice("jane"))
    plugin = StaticVisionPlugin(
        opted_in=(("jane", "20s", "90s"),),
        rng=random.Random(7),
        capture_fps=20.0,
        config_dir=None,
    )
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    messages: list[str] = []
    sink = logger.add(messages.append, format="{message}")
    try:
        await manager.enable_plugin(plugin)
        await manager.wait_for_idle()
    finally:
        logger.remove(sink)
    vision_requests = [r for r in requests.seen if r.event_name == "vision_describe_request"]
    assert len(vision_requests) == 1
    assert vision_requests[0].job_id == "vision-describe-jane"
    assert vision_requests[0].expression == "20s"
    assert plugin._periodic_jobs == ["vision-describe-jane"]
    joined = "\n".join(messages)
    assert "[vision] next jane narration in " in joined
    assert "(range 20-90s)" in joined
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    await asyncio.wait_for(manager.disable_plugin(scheduler.name), timeout=5.0)
