from langgraph.graph import StateGraph
from pydantic import SecretStr
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END, START
from langchain_openai import ChatOpenAI

# from langchain.schema import HumanMessage
from modules.server import Manager
from modules.prompt import PromptFunction

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
    print("RESPONSE", response)
    return {"output": response.content}


graph.add_node("llm_node", process_input)
graph.add_edge(START, "llm_node")
graph.add_edge("llm_node", END)


agent = graph.compile()

result = agent.invoke({"input": "What is Python?"})
print(result)

server = Manager(PromptFunction)
server.serve()
