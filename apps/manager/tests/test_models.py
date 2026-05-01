import pytest
import time
from modules.agents import AGENTS


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
    print("\n\nTEXT:", text, "\n\nREASONING\n\n", reasoning)
    return {text, reasoning}


def test_dreamer():
    process_response(AGENTS["DREAMER"].invoke({"input": "Como anda, la rulobanda"}))


def test_talker():
    process_response(AGENTS["TALKER"].invoke({"input": "Como anda, la rulobanda"}))
