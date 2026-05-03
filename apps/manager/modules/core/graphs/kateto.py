from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import InMemorySaver
from modules.core.agents import AGENTS


class KatetoState(TypedDict):
    input: str
    agent: str
    output: str


graph = StateGraph(KatetoState)

graph.add_node("llm_node", AGENTS[agent].invoke)
graph.add_edge(START, "llm_node")
graph.add_edge("llm_node", END)

checkpointer = InMemorySaver()

KATETO = graph.compile(checkpointer=checkpointer)
