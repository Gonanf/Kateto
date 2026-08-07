"""WorkflowCapability: run_workflow tool for management voices.

Wraps the declarative workflow engine: emitting a `workflow_run` event
targets `workflow_engine` (a `Plugin` with the `workflow` capability), which
loads the definition and drives phases/checkpoints.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import FunctionToolset
from pydantic_ai.capabilities import Capability

from kateto.core.event import WorkflowRunData
from kateto.voices.base import VoiceAgent


class WorkflowToolset:
    def __init__(self, voice: VoiceAgent) -> None:
        self._voice = voice
        ts = FunctionToolset()
        ts.add_function(
            self._run_workflow,
            name="run_workflow",
            description=(
                "Start a declarative workflow for this voice. Use the exact workflow "
                "name from your available workflows. The workflow engine drives the "
                "phases and verifies checkpoints automatically."
            ),
        )
        self._toolset = ts

    async def _run_workflow(self, name: str, inputs: dict[str, Any] | None = None) -> str:
        manager = self._voice.manager
        if manager is None:
            return json.dumps({"status": "error", "error": "no plugin manager available"})
        context = {
            key: value
            for key, value in (inputs or {}).items()
            if value is None or isinstance(value, (str, int, float, bool))
        }
        await manager.emit(
            "workflow_run",
            WorkflowRunData(workflow=name, voice=self._voice.name, context=context),
            source=self._voice.name,
            target="workflow_engine",
        )
        return json.dumps({"status": "started", "workflow": name, "voice": self._voice.name})

    @property
    def toolset(self) -> Any:
        return self._toolset


class WorkflowCapability(Capability[None]):
    def __init__(self, voice: VoiceAgent) -> None:
        super().__init__(
            toolsets=[WorkflowToolset(voice).toolset],
            description="Run declarative workflows through the workflow engine.",
        )
