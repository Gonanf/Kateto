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
from modules.core.server import Manager
from modules.core.agents import AGENTS
from modules.core.graphs.kateto import KATETO
import manager_pb

logger = logging.getLogger(__name__)


def PromptFunction(request, context) -> Generator[manager_pb.PromptResponse]:
    stream = KATETO.invoke(
        {"input": request.text, "agent": manager_pb.Agents.Name(request.agent)},
        {"configurable": {"thread_id": "1"}},
        stream_mode=["messages"],
        version=["v2"],
    )
    print("STREAM", stream)
    for token in stream:
        yield manager_pb.PromptResponse(token=token.text)
