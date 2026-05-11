from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import InMemorySaver
from modules.core.agents import AGENTS


class DreamerState(TypedDict):
    input: str
    output: str


graph = StateGraph(DreamerState)

graph.add_node("llm_node", AGENTS["DREAMER"].invoke)
graph.add_edge(START, "llm_node")
graph.add_edge("llm_node", END)

checkpointer = InMemorySaver()

DREAMER = graph.compile(checkpointer=checkpointer)
