import logging
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
from modules.graphs import GRAPHS

logger = logging.getLogger(__name__)


def PromptFunction(request, context) -> Generator[manager_pb.PromptResponse]:
    stream = GRAPHS[request.agent].stream(
        {"input": request.text},
        {"configurable": {"thread_id": "1"}},
        stream_mode=["messages"],
        version="v2",
    )

    for token in stream:
        message_chunk, metadata = token["data"]

        for block in message_chunk.content:
            print("BLOCK:", block)
            if block["type"] == "text":
                yield manager_pb.PromptResponse(token=block["text"])
