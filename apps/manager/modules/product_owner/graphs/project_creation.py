from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import InMemorySaver
from modules.product_owner.states.project import Document
from modules.product_owner.agents.project_creation import (
    ProductOwnerAgent,
    ProductBacklogItemAgent,
    DODAgent,
    PhasesAgent,
    IsBusyAgent,
)

graph = StateGraph(Document)

graph.add_node("product_owner", ProductOwnerAgent)
graph.add_node("product_backlog_item", ProductBacklogItemAgent)
graph.add_node("dod", DODAgent)
graph.add_node("phases", PhasesAgent)
graph.add_node("is_busy", IsBusyAgent)

graph.add_edge(START, "product_owner")
graph.add_edge("product_owner", "product_backlog_item")
graph.add_edge("product_backlog_item", "dod")
graph.add_edge("dod", "phases")
graph.add_edge("phases", "is_busy")
graph.add_edge("is_busy", END)

checkpointer = InMemorySaver()

PROJECT_CREATION = graph.compile(checkpointer=checkpointer)
