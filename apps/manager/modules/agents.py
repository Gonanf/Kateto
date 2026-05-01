from os import listdir
from langchain_openai import ChatOpenAI
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage


class Agent:
    def __init__(self, model: str, prompt_file: Path) -> None:
        self.model_name = model
        self.base_url = "http://localhost:11434/v1"
        self.api_key = "Hello"
        reasoning = {
            "effort": "high",  # 'low', 'medium', or 'high'
            "thinking_budget_tokens": 1024,
        }
        self.model = ChatOpenAI(
            model=model,
            base_url=self.base_url,
            api_key=self.api_key,
            max_tokens=4096,
            # streaming=True,
            reasoning=reasoning,
        )
        if not prompt_file.exists():
            raise TypeError(
                f"File: {prompt_file} does not exists, Current path: {listdir()}."
            )
        with open(prompt_file, "r") as file:
            self.prompt = file.read()

    def invoke(self, state):
        messages = [
            SystemMessage(content=self.prompt),
            HumanMessage(content=state["input"]),
        ]
        response = self.model.invoke(messages)

        for i in response.content:
            if i["type"] == "text":
                return {"output": i["text"]}


AGENTS = dict(
    TALKER=Agent("KatetoTalker", Path("data/agents/kateto-charlatan.md")),
    DREAMER=Agent("KatetoDreamer", Path("data/agents/kateto-soñador.md")),
    PRODUCT_OWNER=Agent(
        "KatetoProductOwner", Path("data/agents/kateto-product-owner.md")
    ),
)
