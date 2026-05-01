from typing import Generator
import manager_pb
import time
from langgraph.graph import StateGraph
from pydantic import SecretStr
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END, START
from langchain_openai import ChatOpenAI
import subprocess
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage, SystemMessage
from modules.server import Manager
from modules.agents import AGENTS


class AgentState(TypedDict):
    input: str
    output: str


graph = StateGraph(AgentState)

graph.add_node("llm_node", AGENTS["TALKER"].invoke)
graph.add_edge(START, "llm_node")
graph.add_edge("llm_node", END)

checkpointer = InMemorySaver()

agent = graph.compile(checkpointer=checkpointer)


def PromptFunction(request, context) -> Generator[manager_pb.PromptResponse]:
    stream = agent.stream(
        {"input": request.text},
        {"configurable": {"thread_id": "1"}},
        stream_mode=["messages"],
        version="v2",
    )

    print(request.agent)

    for token in stream:
        print(token)
        message_chunk, metadata = token["data"]
        print("MESSAGE:", message_chunk)

        for block in message_chunk.content:
            print("BLOCK:", block)
            if block["type"] == "text":
                yield manager_pb.PromptResponse(token=block["text"])
