from re import A
import manager_pb
import grpc
import sys
import pytest
import threading
import time

import modules.mock_prompt
import modules.prompt
from modules.server import Manager


@pytest.fixture
def start_mock_server():
    server = Manager(modules.mock_prompt.PromptFunction)

    server.start()

    time.sleep(1)

    yield

    server.stop()


@pytest.fixture
def start_server():
    server = Manager(modules.prompt.PromptFunction)

    server.start()

    time.sleep(1)

    yield

    server.stop()


class Client:
    def __init__(self) -> None:
        self.channel = grpc.insecure_channel("0.0.0.0:50051")
        self.stub = manager_pb.ManagerStub(self.channel)
        self.agent = manager_pb.Agents.DREAMER

    def Agent(self, agent: int):
        self.agent = agent
        return self

    def Prompt(self, text):
        return self.stub.Prompt(manager_pb.PromptRequest(text=text, agent=self.agent))


def test_mock_prompt(start_mock_server):
    stream = Client().Prompt("Amogas")
    print(stream)
    buffer = ""
    for i in stream:
        print(i)
        buffer += i.token + " "
    buffer = buffer[:-1]
    assert buffer == modules.mock_prompt.MOCK_DATA


def test_prompt(start_server):
    stream = Client().Prompt("Amogas")
    buffer = ""
    for i in stream:
        print(i)
        buffer += i.token
    print("PRINT:", buffer)
    assert len(buffer) > 0


def test_kateto_prompt(start_server):
    stream = Client().Agent(0).Prompt("Kateto, insulta todo lo que puedas.")
    buffer = ""
    for i in stream:
        buffer += i.token
    print("PRINT:", buffer)
    assert len(buffer) > 0
