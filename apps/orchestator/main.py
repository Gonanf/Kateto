import ctranslate2

ctranslate2.get_cuda_device_count()  # Force ROCm/HIP runtime init before RealtimeSTT's imports corrupt it
from RealtimeSTT import AudioToTextRecorder
import manager_pb
import tts_pb
import grpc


class Manager:
    def __init__(self) -> None:
        self.channel = grpc.insecure_channel("localhost:50051")
        self.stub = manager_pb.ManagerStub(self.channel)


class TTS:
    def __init__(self) -> None:
        self.channel = grpc.insecure_channel("localhost:50052")
        self.stub = tts_pb.TTSStub(self.channel)


def speak_requests_from_prompt(prompt_stream):
    for token in prompt_stream:
        yield tts_pb.SpeakRequest(token=token.token)


class Orchestator:
    def process_text(self, text):
        print(text)

        # for token in self.manager.stub.Prompt(manager_pb.PromptRequest(text=text)):
        #     print(token.token)
        #     # TODO: 23/04/2026 send to TTS
        #     self.tts.stub.Speak(tts_pb.SpeakRequest(token=token))
        #
        prompt_stream = self.manager.stub.Prompt(manager_pb.PromptRequest(text=text))

        speech_result = self.tts.stub.Speak(speak_requests_from_prompt(prompt_stream))

    def __init__(self) -> None:
        self.manager = Manager()
        self.tts = TTS()

    def start(self):
        print("Wait until it says 'speak now'")
        recorder = AudioToTextRecorder()

        while True:
            recorder.text(self.process_text)


if __name__ == "__main__":
    runner = Orchestator()
    runner.start()
