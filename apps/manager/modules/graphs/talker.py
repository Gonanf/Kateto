from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import InMemorySaver
from modules.agents import AGENTS


class TalkerState(TypedDict):
    input: str
    output: str


graph = StateGraph(TalkerState)

graph.add_node("llm_node", AGENTS["TALKER"].invoke)
graph.add_edge(START, "llm_node")
graph.add_edge("llm_node", END)

checkpointer = InMemorySaver()

TALKER = graph.compile(checkpointer=checkpointer)
