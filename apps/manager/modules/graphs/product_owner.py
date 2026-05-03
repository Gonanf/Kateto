from typing import List, Literal, TypedDict

from langgraph.types import Command, interrupt
from modules.agents import AGENTS
from typing_extensions import Doc, TypedDict
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import InMemorySaver


class IsBusy(TypedDict):
    priority: int
    effort_days: int
    effort_start: str  # Date class?
    effort_end: str


class PBI(TypedDict):
    description: str
    project_values: list[str]
    dependencies: list[str]


class Critery(TypedDict):
    given_clause: str
    when_clause: str
    then_clause: str


class DOD(TypedDict):
    category: Literal[
        "Code Quality", "Testing", "Documentation", "Deployment", "Performance"
    ]
    dod_items: list[str]


class UserStory(TypedDict):
    title: str
    description: str
    score: int
    notes: str
    criteries: list[Critery]


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


class Document(TypedDict):
    title: str
    team: list[Asignee]
    pbi: PBI
    is_busy: IsBusy
    user_stories: list[UserStory]
    dod: list[DOD]
    phases: list[Phase]
    events: list[Event]
    messages: list[str] | None


## Nodes
def ProductOwner(state: Document):
    if not state.get("title"):
        title = interrupt("Titulos")
        return Command(update={"title": title["title"]}, goto="product_owner")
    if not state.get("team"):
        state["team"] = [Asignee(type="Human", name="Chaos")]


def ProductBacklogItem(state: Document):
    agent = AGENTS["PRODUCT_OWNER"]
    agent.model.with_structured_output(PBI)

    prompt = f"""
        Create the Product Backlog Item for this:

        # IDEA 
        {state["title"]}

        # TEAM
        {state["team"]} 
    """

    pbi = agent.invoke({"input": prompt})
    return {"pbi": pbi}

def IsBusy(stete: Document):


##Graph

graph = StateGraph(Document)

graph.add_node("product_owner", ProductOwner)
graph.add_node("product_backlog_item", ProductBacklogItem)
graph.add_edge(START, "product_owner")
graph.add_edge("product_owner", "product_backlog_item")
graph.add_edge("product_backlog_item", END)
graph.add_edge("product_owner", END)
graph.add_edge("product_owner", END)

checkpointer = InMemorySaver()

DREAMER = graph.compile(checkpointer=checkpointer)
