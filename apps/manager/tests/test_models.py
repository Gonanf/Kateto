import pytest
import time
from modules.agents import AGENTS


def test_dreamer():
    response = AGENTS["DREAMER"].invoke({"input": "Como anda, la rulobanda"})
    print("DREAMER:", response)


def test_talker():
    response = AGENTS["TALKER"].invoke({"input": "Como anda, la rulobanda"})
    print("TALKER:", response)
