from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import RetryPolicy, Send
from modules.product_owner.states.project import Document, SprintState
from modules.product_owner.agents.product_owner import (
    ProductOwnerAgent,
    ProductBacklogItemAgent,
    DODAgent,
)
from modules.product_owner.agents.sprint import (
    SprintAgent,
    SprintTasksAgent,
    IsBusyAgent,
)
from modules.product_owner.agents.output import createAffineDocument
from modules.product_owner.agents.openproject import ReadOpenProjectContext, SyncToOpenProject

graph = StateGraph(Document)

graph.add_node("product_owner", ProductOwnerAgent)
graph.add_node("product_backlog_item", ProductBacklogItemAgent)
graph.add_node("dod", DODAgent)
graph.add_node(
    "sprint",
    SprintAgent,
    retry_policy=RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0),
)
graph.add_node(
    "sprint_tasks",
    SprintTasksAgent,
    retry_policy=RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0),
)
graph.add_node("is_busy", IsBusyAgent)
graph.add_node("create_affine", createAffineDocument)
graph.add_node("read_openproject_context", ReadOpenProjectContext)
graph.add_node("sync_to_openproject", SyncToOpenProject)


def route_to_sprints(state: Document):
    if not state.draft_sprints:
        return
    temp = []
    week = 0
    for sprint in state.draft_sprints:
        temp.append(
            Send(
                "sprint_tasks",
                SprintState(document=state, current=sprint, week=week),
            )
        )
        week += sprint.duration_weeks

    return temp


graph.add_edge(START, "read_openproject_context")
graph.add_edge("read_openproject_context", "product_owner")
graph.add_edge("product_owner", "product_backlog_item")
graph.add_edge("product_backlog_item", "dod")
graph.add_edge("dod", "sprint")
graph.add_conditional_edges("sprint", route_to_sprints)
graph.add_edge("sprint_tasks", "is_busy")
graph.add_edge("is_busy", "sync_to_openproject")
graph.add_edge("sync_to_openproject", END)

checkpointer = InMemorySaver()

PROJECT_CREATION = graph.compile(checkpointer=checkpointer)
