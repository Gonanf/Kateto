from typing import Type, TypedDict, Literal, Union


class IsBusy(TypedDict):
    effort_days: int
    effort_start: str  # ISO date string (YYYY-MM-DD)
    effort_end: str  # ISO date string (YYYY-MM-DD)


class Critery(TypedDict):
    given_clause: str
    when_clause: str
    then_clause: str


class PBI_Content(TypedDict):
    score: int
    notes: str
    criteries: list[Critery]


class PBI_Data(TypedDict):
    type: Literal[
        "User Story", "Epic", "Task"
    ]  # TODO: Add Bug and Epic?, when implementing in existing projects
    title: str
    description: str
    score: int
    priority: int
    notes: str
    criteries: list[Critery]


class PBI(TypedDict):
    data: PBI_Data
    is_busy: IsBusy | None


class DOD(TypedDict):
    category: Literal[
        "Code Quality", "Testing", "Documentation", "Deployment", "Performance"
    ]
    dod_items: list[str]


class Asignee(TypedDict):
    type: Literal["Human", "Agent"]
    name: str


class PhaseTask(TypedDict):
    description: str
    asignee: Asignee
    effort_hours: float


class Phase(TypedDict):
    title: str
    duration_days: int


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
    start_time: str  # date class
    end_time: str


class DocumentData(TypedDict):
    description: str
    project_values: list[str]
    dependencies: list[str]


class Document(TypedDict):
    title: str
    team: list[Asignee] | None
    pbi_count: int
    data: DocumentData | None
    pbi: list[PBI] | None
    dod: list[DOD] | None
    phases: list[Phase] | None
    events: list[Event] | None
    messages: list[str] | None
