from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import InMemorySaver
from modules.product_owner.states.project import Document
from modules.product_owner.agents.project_creation import (
    ProductOwnerAgent,
    ProductBacklogItemAgent,
)

graph = StateGraph(Document)

graph.add_node("product_owner", ProductOwnerAgent)
graph.add_node("product_backlog_item", ProductBacklogItemAgent)
graph.add_edge(START, "product_owner")
graph.add_edge("product_owner", "product_backlog_item")
graph.add_edge("product_backlog_item", END)
graph.add_edge("product_owner", END)
graph.add_edge("product_owner", END)

checkpointer = InMemorySaver()

PROJECT_CREATION = graph.compile(checkpointer=checkpointer)
