from __future__ import annotations

import pytest
from pydantic import BaseModel

from kateto.core import Plugin, PluginManager
from kateto.core.config import KatetoSettings, VoiceSettings
from kateto.core.event import EventEnvelope, TextChunk, TranscriptionData


class _NoteData(BaseModel):
    text: str = "note"


class RecordingPlugin(Plugin):
    def __init__(
        self,
        name: str,
        *,
        depts: tuple[str, ...] = (),
        capabilities: tuple[str, ...] = (),
    ) -> None:
        super().__init__(name, depts=depts, capabilities=capabilities)
        self.received: list[BaseModel] = []

    async def initialize(self) -> None:
        manager = self.manager
        assert manager is not None
        manager.register_event("note", _NoteData)

    async def on_note(self, data: _NoteData) -> None:
        self.received.append(data)


class VoicePlugin(RecordingPlugin):
    def __init__(self, name: str, *, depts: tuple[str, ...]) -> None:
        super().__init__(name, capabilities=("voice",), depts=depts)


async def _emit_note(
    manager: PluginManager,
    *,
    source: str = "test",
    dept: str | None = None,
    target: str | None = None,
    capabilities: tuple[str, ...] = (),
) -> EventEnvelope[BaseModel]:
    return await manager.emit(
        "note",
        _NoteData(),
        source=source,
        dept=dept,
        target=target,
        capabilities=capabilities,
    )


@pytest.mark.asyncio
async def test_envelope_carries_dept_field_defaulting_to_none() -> None:
    # Given: a fresh manager
    manager = PluginManager()
    # When: an event is emitted without a dept
    envelope = await _emit_note(manager)
    # Then: dept defaults to None and validates as a string when set
    assert envelope.dept is None
    tagged = await _emit_note(manager, dept="Fun")
    assert tagged.dept == "fun"


@pytest.mark.asyncio
async def test_dept_filter_routes_only_to_matching_departments() -> None:
    # Given: three plugins in two departments
    manager = PluginManager()
    fun = RecordingPlugin("fun_worker", depts=("fun",))
    mgmt = RecordingPlugin("mgmt_worker", depts=("management",))
    both = RecordingPlugin("both_worker", depts=("fun", "management"))
    for plugin in (fun, mgmt, both):
        await manager.enable_plugin(plugin)
    # When: an event is emitted into the fun department
    await _emit_note(manager, dept="fun")
    await manager.wait_for_idle(timeout=5)
    # Then: only fun-department plugins receive it
    assert len(fun.received) == 1
    assert len(mgmt.received) == 0
    assert len(both.received) == 1


@pytest.mark.asyncio
async def test_untagged_events_still_broadcast_to_all() -> None:
    # Given: plugins in different departments
    manager = PluginManager()
    fun = RecordingPlugin("fun_worker", depts=("fun",))
    mgmt = RecordingPlugin("mgmt_worker", depts=("management",))
    for plugin in (fun, mgmt):
        await manager.enable_plugin(plugin)
    # When: an event is emitted without a dept
    await _emit_note(manager)
    await manager.wait_for_idle(timeout=5)
    # Then: all plugins receive it (broadcast behaviour unchanged)
    assert len(fun.received) == 1
    assert len(mgmt.received) == 1


@pytest.mark.asyncio
async def test_dept_composes_with_target() -> None:
    # Given: two fun-department plugins
    manager = PluginManager()
    alice = RecordingPlugin("alice", depts=("fun",))
    bob = RecordingPlugin("bob", depts=("fun",))
    for plugin in (alice, bob):
        await manager.enable_plugin(plugin)
    # When: an event targets one plugin inside a department
    await _emit_note(manager, dept="fun", target="alice")
    await manager.wait_for_idle(timeout=5)
    # Then: only the targeted plugin within the department receives it
    assert len(alice.received) == 1
    assert len(bob.received) == 0


@pytest.mark.asyncio
async def test_dept_composes_with_capabilities() -> None:
    # Given: two fun-department plugins, one with the 'shout' capability
    manager = PluginManager()
    plain = RecordingPlugin("plain", depts=("fun",))
    shout = RecordingPlugin("shout", depts=("fun",), capabilities=("shout",))
    for plugin in (plain, shout):
        await manager.enable_plugin(plugin)
    # When: an event is emitted with dept and a capability filter
    await _emit_note(manager, dept="fun", capabilities=("shout",))
    await manager.wait_for_idle(timeout=5)
    # Then: both filters must match
    assert len(plain.received) == 0
    assert len(shout.received) == 1


@pytest.mark.asyncio
async def test_voice_cannot_emit_into_foreign_department() -> None:
    # Given: a voice bound to the management department
    manager = PluginManager()
    voice = VoicePlugin("doktor", depts=("management",))
    await manager.enable_plugin(voice)
    # When: the voice tries to emit into the fun department
    with pytest.raises(ValueError, match="cannot emit into dept 'fun'"):
        await _emit_note(manager, source="doktor", dept="fun")


@pytest.mark.asyncio
async def test_voice_can_emit_into_its_own_department() -> None:
    # Given: a fun-department voice and a fun-department worker
    manager = PluginManager()
    voice = VoicePlugin("jane", depts=("fun",))
    worker = RecordingPlugin("fun_worker", depts=("fun",))
    await manager.enable_plugin(voice)
    await manager.enable_plugin(worker)
    # When: the voice emits into its own department
    await _emit_note(manager, source="jane", dept="fun")
    await manager.wait_for_idle(timeout=5)
    # Then: it is allowed and routed
    assert len(worker.received) == 1


@pytest.mark.asyncio
async def test_non_voice_plugin_emits_with_dept_unconstrained() -> None:
    # Given: a non-voice source plugin with no dept policy
    manager = PluginManager()
    source = RecordingPlugin("cron_job")
    worker = RecordingPlugin("fun_worker", depts=("fun",))
    await manager.enable_plugin(source)
    await manager.enable_plugin(worker)
    # When: the non-voice plugin emits into the fun department
    await _emit_note(manager, source="cron_job", dept="fun")
    await manager.wait_for_idle(timeout=5)
    # Then: no anti-spoofing applies (only voices are restricted)
    assert len(worker.received) == 1


@pytest.mark.asyncio
async def test_empty_depts_excluded_from_dept_routing() -> None:
    # Given: a plugin with no department and one with the fun department
    manager = PluginManager()
    nodet = RecordingPlugin("no_department")
    fun = RecordingPlugin("fun_worker", depts=("fun",))
    await manager.enable_plugin(nodet)
    await manager.enable_plugin(fun)
    # When: an event is emitted into the fun department
    await _emit_note(manager, dept="fun")
    await manager.wait_for_idle(timeout=5)
    # Then: department-less plugins do not receive department-tagged events
    assert len(nodet.received) == 0
    assert len(fun.received) == 1


@pytest.mark.asyncio
async def test_plugin_dept_matching_is_case_insensitive() -> None:
    # Given: a plugin registered with mixed-case departments
    manager = PluginManager()
    worker = RecordingPlugin("worker", depts=("Management", "FUN"))
    await manager.enable_plugin(worker)
    # When: an event is emitted with a lower-case dept
    await _emit_note(manager, dept="management")
    await manager.wait_for_idle(timeout=5)
    # Then: casefolded matching routes it
    assert len(worker.received) == 1


def test_voice_settings_dept_and_depts_are_mutually_exclusive() -> None:
    # Given: a settings object naming both fields
    with pytest.raises(ValueError, match="mutually exclusive"):
        VoiceSettings(dept="fun", depts=["management"])


def test_voice_settings_dept_values_are_casefolded() -> None:
    # Given: settings with mixed-case department names
    settings = VoiceSettings(dept="Fun")
    # When: the values are read back
    # Then: they are normalized to lower case
    assert settings.dept == "fun"
    assert VoiceSettings(depts=["Fun", "MANAGEMENT"]).depts == ["fun", "management"]


def test_kateto_settings_default_voice_dept() -> None:
    # Given: default settings
    settings = KatetoSettings()
    # Then: the default department is 'fun'
    assert settings.default_voice_dept == "fun"


@pytest.mark.asyncio
async def test_voice_request_events_are_not_dept_restricted() -> None:
    # Given: a voice agent emitting text chunks carries no dept by default
    manager = PluginManager()
    voice = VoicePlugin("jane", depts=("fun",))
    await manager.enable_plugin(voice)
    # When: it emits a text_chunk without a dept
    envelope = await manager.emit(
        "note",
        _NoteData(text="hello"),
        source="jane",
    )
    # Then: the envelope dept is None (backwards compatible)
    assert envelope.dept is None


def test_envelope_dept_rejects_empty_string() -> None:
    manager = PluginManager()

    async def run() -> None:
        await _emit_note(manager, dept="")

    with pytest.raises(ValueError, match="non-empty"):
        import asyncio

        asyncio.run(run())
