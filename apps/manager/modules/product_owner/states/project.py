from typing import Annotated, Literal
from modules.product_owner.openproject.models import OpenProjectReadContext
from pydantic import BaseModel, Field
import operator


class Critery(BaseModel):
    given_clause: str
    when_clause: str
    then_clause: str


class PBI(BaseModel):
    type: Literal["User Story", "Epic", "Task", "Bug"]
    title: str
    description: str
    score: int
    priority: int
    notes: str
    criteries: list[Critery] = Field(min_length=1, max_length=3)


class DOD(BaseModel):
    category: Literal[
        "Code Quality", "Testing", "Documentation", "Deployment", "Performance"
    ]
    dod_items: list[str] = Field(min_length=3, max_length=5)


class Asignee(BaseModel):
    type: Literal["Human", "Agent"]
    name: str


class SprintTask(BaseModel):
    title: str
    description: str
    asignee: Asignee
    effort_hours: float


class SprintDraft(BaseModel):
    goal: str
    description: str
    duration_weeks: int


class Sprint(BaseModel):
    data: SprintDraft
    tasks: list[SprintTask] = Field(min_length=3, max_length=6)


class Phase(BaseModel):
    title: str
    duration_days: int
    tasks: list[SprintTask] = Field(min_length=3, max_length=6)


class DocumentData(BaseModel):
    description: str
    project_values: list[str] = Field(
        min_length=3,
        max_length=5,
        description="The values (Businness and educational) that the project provides",
    )
    dependencies: list[str] = Field(
        min_length=3,
        max_length=5,
        description="The things that the project need to get done before starting",
    )


class Document(BaseModel):
    title: str
    description: str | None = None
    team: list[Asignee] | None
    data: DocumentData | None
    pbi: list[PBI] | None
    dod: list[DOD] | None
    draft_sprints: list[SprintDraft] | None
    completed_sprints: Annotated[list[Sprint], operator.add]
    openproject_context: OpenProjectReadContext | None = None


# ── LLM structured output schemas ──────────────────────────────────────────


class DODList(BaseModel):
    dods: list[DOD] = Field(min_length=5, max_length=6)


class PBIList(BaseModel):
    pbis: list[PBI] = Field(min_length=5, max_length=10)


class SprintList(BaseModel):
    sprints: list[SprintDraft] = Field(min_length=2, max_length=4)


class SprintTasksList(BaseModel):
    tasks: list[SprintTask] = Field(min_length=2, max_length=6)


# ── Sub-state for fan-out to SprintTasksAgent ──────────────────────────────


class SprintState(BaseModel):
    document: Document
    current: SprintDraft
    week: int
