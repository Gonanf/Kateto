from typing import Generator
import manager_pb
import time

MOCK_DATA = """I get no kick from champagne
Mere alcohol doesn't thrill me at all
So tell me why shouldn't it be true?
I get a kick out of brew"""


def PromptFunction(request, context) -> Generator[manager_pb.PromptResponse]:
    for text in MOCK_DATA.split(" "):
        time.sleep(0.1)
        yield manager_pb.PromptResponse(token=text)
