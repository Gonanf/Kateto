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

# from langchain.schema import HumanMessage
from modules.server import Manager

llm = ChatOpenAI(
    model="KatetoDreamer",
    base_url="http://localhost:11434/v1",
    # streaming=True,
    api_key="Hello",
)

response = llm.invoke("Hello, how are you?")
print(response.content)


class AgentState(TypedDict):
    input: str
    output: str


graph = StateGraph(AgentState)


def process_input(state):
    response = llm.invoke(state["input"])
    return {"output": response}
    for token in response:
        print("TOKEN:", token)
        yield {"output": token.content}
    # print("RESPONSE", response.content)
    # return {"output": response.content}


graph.add_node("llm_node", process_input)
graph.add_edge(START, "llm_node")
graph.add_edge("llm_node", END)

checkpointer = InMemorySaver()

agent = graph.compile(checkpointer=checkpointer)

kateto_prompt = ""

# TODO: Abrir todos los archivos  y generar un diccionario para cada uno con su contenido
with open("data/kateto-charlatan.md", "r") as file:
    kateto_prompt = file.read()


def PromptFunction(request, context) -> Generator[manager_pb.PromptResponse]:
    stream = agent.stream(
        {"input": kateto_prompt + "\n\n**PROMPT**\n\n" + request.text},
        {"configurable": {"thread_id": "1"}},
        stream_mode=["messages"],
        version="v2",
    )
    for token in stream:
        print(token)
        message_chunk, metadata = token["data"]
        print("MESSAGE:", message_chunk, "METADATA:", metadata)
        yield manager_pb.PromptResponse(token=message_chunk.content)
        # for name, state in token["data"].items():
        #     print("NAME:", name, "STATE:", state)
        #     yield manager_pb.PromptResponse(token="a")
