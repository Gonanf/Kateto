from typing import Literal
from pydantic import BaseModel, Field


class ScheduledSlot(BaseModel):
    part_number: int
    part_total: int
    start: str
    end: str
    event_id: str | None


class IsBusy(BaseModel):
    effort_days: int
    effort_start: str
    effort_end: str
    scheduled_slots: list[ScheduledSlot]


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


class PhaseTask(BaseModel):
    title: str
    description: str
    asignee: Asignee
    effort_hours: float
    is_busy: IsBusy | None


class Phase(BaseModel):
    title: str
    duration_days: int
    tasks: list[PhaseTask] = Field(min_length=3, max_length=6)


class Event(BaseModel):
    type: Literal[
        "Sprint Planning",
        "Daily Stand Up",
        "Sprint Review",
        "Sprint Retrospective",
        "Work",
    ]
    title: str
    description: str
    start_time: str
    end_time: str


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
    team: list[Asignee] | None
    data: DocumentData | None
    pbi: list[PBI] | None
    dod: list[DOD] | None
    phases: list[Phase] | None
