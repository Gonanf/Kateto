from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import InMemorySaver
from modules.agents import AGENTS


class ClassifierState(TypedDict):
    input: str
    agent: int
    output: str


def process_input(state: ClassifierState):
    pass


graph = StateGraph(ClassifierState)

graph.add_node("llm_node", process_input)
graph.add_edge(START, "llm_node")
graph.add_edge("llm_node", END)

checkpointer = InMemorySaver()

TALKER = graph.compile(checkpointer=checkpointer)
