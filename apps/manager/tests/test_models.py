import pytest
import time
from modules.agents import AGENTS


def process_response(stream):
    text = ""
    reasoning = ""
    for chunk in stream.content:
        if chunk["type"] == "text":
            text += chunk["text"]
        elif chunk["type"] == "reasoning":
            reasoning += chunk["reasoning"]
    print("\n\nTEXT:", text, "\n\nREASONING\n\n", reasoning)
    return {text, reasoning}


def test_dreamer():
    process_response(AGENTS["DREAMER"].invoke({"input": "Como anda, la rulobanda"}))


def test_talker():
    process_response(AGENTS["TALKER"].invoke({"input": "Como anda, la rulobanda"}))
