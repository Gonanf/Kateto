from os import listdir
from langchain_openai import ChatOpenAI
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage


class Agent:
    def __init__(self, model: str, prompt_file: Path) -> None:
        self.model_name = model
        self.base_url = "http://localhost:11434/v1"
        self.api_key = "Hello"
        self.model = ChatOpenAI(
            model=model,
            base_url=self.base_url,
            api_key=self.api_key,
            max_tokens=1024,
            streaming=True,
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

        try:
            response = self.model.invoke(messages)
            content = response.content or ""
        except Exception:
            content = self._invoke_raw(state["input"])

        return {"output": content}

    def _invoke_raw(self, user_input: str) -> str:
        import requests
        import json

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": user_input},
            ],
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            return message.get("content") or message.get("reasoning_content", "")
        except Exception as e:
            return f"Error: {str(e)}"


AGENTS = dict(
    TALKER=Agent("KatetoTalker", Path("data/agents/kateto-charlatan.md")),
    DREAMER=Agent("KatetoDreamer", Path("data/agents/kateto-soñador.md")),
    PRODUCT_OWNER=Agent(
        "KatetoProductOwner", Path("data/agents/kateto-product-owner.md")
    ),
)
