from typing import Type, TypedDict, Literal, Union


class IsBusy(TypedDict):
    effort_days: int
    effort_start: str
    effort_end: str


class Critery(TypedDict):
    given_clause: str
    when_clause: str
    then_clause: str


class PBI(TypedDict):
    type: Literal["User Story", "Epic", "Task", "Bug"]
    title: str
    description: str
    score: int
    priority: int
    notes: str
    criteries: list[Critery]


class DOD(TypedDict):
    category: Literal[
        "Code Quality", "Testing", "Documentation", "Deployment", "Performance"
    ]
    dod_items: list[str]


class Asignee(TypedDict):
    type: Literal["Human", "Agent"]
    name: str


class PhaseTask(TypedDict):
    title: str
    description: str
    asignee: Asignee
    effort_hours: float
    is_busy: IsBusy | None


class Phase(TypedDict):
    title: str
    duration_days: int
    tasks: list[PhaseTask]


class Event(TypedDict):
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


class DocumentData(TypedDict):
    description: str
    project_values: list[str]
    dependencies: list[str]


class Document(TypedDict):
    title: str
    team: list[Asignee] | None
    data: DocumentData | None
    pbi: list[PBI] | None
    dod: list[DOD] | None
    phases: list[Phase] | None
    events: list[Event] | None
    messages: list[str] | None
