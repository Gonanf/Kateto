from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kateto.core.storage import PathIsolationError, VoiceFileStore


_WORKFLOW_SEGMENT: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_DECLARATION_NAMES: Final[frozenset[str]] = frozenset(
    {"name", "description", "voice", "auto_advance", "can_stop", "phases"},
)


class WorkflowDefinitionError(Exception):
    def __init__(self, *, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"invalid workflow definition at {path}: {reason}")


class WorkflowNotFoundError(Exception):
    def __init__(self, *, workflow: str, voice: str) -> None:
        self.workflow = workflow
        self.voice = voice
        super().__init__(f"workflow {workflow!r} is unavailable for voice {voice!r}")


class WorkflowStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


class WorkflowPhaseStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class WorkflowPhase:
    id: str
    name: str
    instructions: tuple[str, ...]
    deliverables: tuple[str, ...]
    checkpoints: tuple[str, ...]
    calls_skills: tuple[str, ...]
    calls_voices: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    name: str
    description: str
    voice: str | None
    auto_advance: bool
    can_stop: bool
    phases: tuple[WorkflowPhase, ...]


class _PhaseDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    instructions: list[str] = Field(min_length=1)
    deliverables: list[str] = Field(default_factory=list)
    checkpoints: list[str] = Field(default_factory=list)
    calls_skills: list[str] = Field(default_factory=list)
    calls_voices: list[str] = Field(default_factory=list)


class _WorkflowDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str = Field(min_length=1)
    description: str = ""
    voice: str | None = None
    auto_advance: bool = True
    can_stop: bool = True
    phases: list[_PhaseDeclaration] = Field(min_length=1)


class WorkflowCatalog:
    def __init__(self, *, config_dir: Path) -> None:
        self._config_dir = config_dir.resolve()

    def discover(self, *, voice: str) -> tuple[WorkflowDefinition, ...]:
        definitions = {
            definition.name.casefold(): definition
            for definition in self._definitions_in(self._config_dir / "workflows", required_voice=None)
        }
        voice_workflows = self._voice_workflows_dir(voice)
        if voice_workflows is not None:
            definitions.update(
                {
                    definition.name.casefold(): definition
                    for definition in self._definitions_in(voice_workflows, required_voice=voice_workflows.parent.name)
                },
            )
        return tuple(sorted(definitions.values(), key=lambda definition: definition.name.casefold()))

    def load(self, *, workflow: str, voice: str) -> WorkflowDefinition:
        safe_workflow = _safe_segment(workflow, "workflow", self._config_dir)
        _safe_segment(voice, "voice", self._config_dir)
        voice_workflows = self._voice_workflows_dir(voice)
        if voice_workflows is not None:
            voice_path = self._workflow_file(voice_workflows, safe_workflow)
            if voice_path is not None:
                return _definition_from_file(voice_path, required_voice=voice_workflows.parent.name)
        global_path = self._workflow_file(self._config_dir / "workflows", safe_workflow)
        if global_path is not None:
            return _definition_from_file(global_path, required_voice=None)
        raise WorkflowNotFoundError(workflow=workflow, voice=voice)

    def _voice_workflows_dir(self, voice: str) -> Path | None:
        voices_root = self._config_dir / "voices"
        if not voices_root.is_dir():
            return None
        for voice_directory in voices_root.iterdir():
            if voice_directory.is_dir() and voice_directory.name.casefold() == voice.casefold():
                try:
                    voice_store = VoiceFileStore.for_voice(
                        config_dir=self._config_dir,
                        voice=voice_directory.name,
                    )
                except PathIsolationError as error:
                    raise WorkflowDefinitionError(
                        path=voice_directory,
                        reason="voice directory escapes config root",
                    ) from error
                return voice_store.root / "workflows"
        return None

    def _definitions_in(self, root: Path, *, required_voice: str | None) -> tuple[WorkflowDefinition, ...]:
        if not root.is_dir():
            return ()
        definitions = []
        for directory in root.iterdir():
            if directory.is_dir():
                workflow_file = self._contained_workflow_file(directory, root)
                if workflow_file is not None:
                    definitions.append(_definition_from_file(workflow_file, required_voice=required_voice))
        return tuple(definitions)

    def _workflow_file(self, root: Path, workflow: str) -> Path | None:
        if not root.is_dir():
            return None
        for directory in root.iterdir():
            if directory.is_dir() and directory.name.casefold() == workflow.casefold():
                return self._contained_workflow_file(directory, root)
        return None

    @staticmethod
    def _contained_workflow_file(directory: Path, root: Path) -> Path | None:
        workflow_file = (directory / "workflow.py").resolve()
        if not workflow_file.is_relative_to(root.resolve()):
            raise WorkflowDefinitionError(path=workflow_file, reason="definition escapes workflow root")
        if workflow_file.is_file():
            return workflow_file
        return None


def _safe_segment(value: str, label: str, root: Path) -> str:
    if _WORKFLOW_SEGMENT.fullmatch(value) is None:
        raise WorkflowDefinitionError(path=root, reason=f"{label} must be a simple workflow segment")
    return value


def _definition_from_file(path: Path, *, required_voice: str | None) -> WorkflowDefinition:
    declaration = _read_declaration(path)
    if declaration.name.casefold() != path.parent.name.casefold():
        raise WorkflowDefinitionError(path=path, reason="name must match its workflow directory")
    match required_voice, declaration.voice:
        case None, None:
            pass
        case None, _:
            raise WorkflowDefinitionError(path=path, reason="global workflows cannot restrict a voice")
        case configured_voice, declared_voice if declared_voice is not None and configured_voice.casefold() == declared_voice.casefold():
            pass
        case _:
            raise WorkflowDefinitionError(path=path, reason="voice does not match its workflow directory")
    return WorkflowDefinition(
        name=declaration.name,
        description=declaration.description,
        voice=declaration.voice,
        auto_advance=declaration.auto_advance,
        can_stop=declaration.can_stop,
        phases=tuple(
            WorkflowPhase(
                id=phase.id,
                name=phase.name,
                instructions=tuple(phase.instructions),
                deliverables=tuple(phase.deliverables),
                checkpoints=tuple(phase.checkpoints),
                calls_skills=tuple(phase.calls_skills),
                calls_voices=tuple(phase.calls_voices),
            )
            for phase in declaration.phases
        ),
    )


def _read_declaration(path: Path) -> _WorkflowDeclaration:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise WorkflowDefinitionError(path=path, reason="definition must be UTF-8") from error
    except OSError as error:
        raise WorkflowDefinitionError(path=path, reason=str(error)) from error
    try:
        tree = ast.parse(source, filename=str(path), mode="exec")
    except SyntaxError as error:
        raise WorkflowDefinitionError(path=path, reason="definition must be valid Python syntax") from error
    values = {}
    for statement in tree.body:
        match statement:
            case ast.Assign(targets=[ast.Name(id=name)], value=value) if name in _DECLARATION_NAMES:
                if name in values:
                    raise WorkflowDefinitionError(path=path, reason=f"duplicate declaration: {name}")
                try:
                    values[name] = ast.literal_eval(value)
                except (SyntaxError, TypeError, ValueError) as error:
                    raise WorkflowDefinitionError(path=path, reason=f"{name} must be a literal value") from error
            case _:
                raise WorkflowDefinitionError(path=path, reason="only supported literal assignments are allowed")
    try:
        return _WorkflowDeclaration.model_validate(values)
    except ValidationError as error:
        raise WorkflowDefinitionError(path=path, reason="declaration fields are invalid") from error
