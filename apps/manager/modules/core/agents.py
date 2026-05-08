from os import listdir
from langchain_openai import ChatOpenAI
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage
import logging

logger = logging.getLogger(__name__)

AGENTS_DIR = Path(__file__).parent.parent.parent / "data" / "agents"


class Agent:
    def __init__(
        self, model: str, prompt_file: str | Path, reason: bool | None = None
    ) -> None:
        self.model_name = model
        self.base_url = "http://localhost:11434/v1"
        self.api_key = "Hello"
        reasoning = None
        if reason:
            reasoning = {
                "effort": "high",  # 'low', 'medium', or 'high'
                "thinking_budget_tokens": 512,
                "generate_summary": "concise",
            }
        self.model = ChatOpenAI(
            model=model,
            base_url=self.base_url,
            api_key=self.api_key,
            streaming=True,
            reasoning=reasoning,
        )
        prompt_path = (
            AGENTS_DIR / prompt_file if isinstance(prompt_file, str) else prompt_file
        )
        if not prompt_path.exists():
            raise TypeError(
                f"File: {prompt_path} does not exist. Available files: {listdir(AGENTS_DIR)}."
            )
        with open(prompt_path, "r") as file:
            self.prompt = file.read()

    def invoke(self, state):
        messages = [
            SystemMessage(content=self.prompt),
            HumanMessage(content=state["input"]),
        ]
        return self.model.invoke(messages)
        # for chunk in self.model.stream(messages):
        #     yield chunk
        #

    def stream(self, state):
        messages = [
            SystemMessage(content=self.prompt),
            HumanMessage(content=state["input"]),
        ]

        for chunk in self.model.stream(messages):
            print("CHUNK:", chunk)
            yield chunk


AGENTS = dict(
    TALKER=Agent("KatetoTalker", "kateto-charlatan.md"),
    DREAMER=Agent("KatetoDreamer", "kateto-soñador.md"),
    PRODUCT_OWNER=Agent(
        "KatetoProductOwner",
        "kateto-product-owner.md",
    ),
    DOD=Agent(
        "KatetoProductOwner",
        "kateto-dod.md",
    ),
    PHASES=Agent(
        "KatetoProductOwner",
        "kateto-phases.md",
    ),
)


def process_response(stream):
    text = ""
    reasoning = ""
    for chunk in stream:
        for content in chunk.content:
            print(content)
            if content["type"] == "text":
                text += content["text"]
            # elif content["type"] == "reasoning":
            #     reasoning += content[""]
    logger.info("\n\nTEXT:", text, "\n\nREASONING\n\n", reasoning)
    return {text, reasoning}
