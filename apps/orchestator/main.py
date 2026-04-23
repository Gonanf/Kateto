import ctranslate2

ctranslate2.get_cuda_device_count()  # Force ROCm/HIP runtime init before RealtimeSTT's imports corrupt it
from RealtimeSTT import AudioToTextRecorder
import manager_pb
import grpc


class Orchestator:
    def process_text(self, text):
        print(text)

        for token in self.stub.Prompt(manager_pb.PromptRequest(text=text)):
            print(token.token)
            # TODO: 23/04/2026 send to TTS

    def __init__(self) -> None:
        self.channel = grpc.insecure_channel("localhost:50051")
        self.stub = manager_pb.ManagerStub(self.channel)

    def start(self):
        print("Wait until it says 'speak now'")
        recorder = AudioToTextRecorder()

        while True:
            recorder.text(self.process_text)


if __name__ == "__main__":
    runner = Orchestator()
    runner.start()
