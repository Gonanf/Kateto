import ctranslate2

ctranslate2.get_cuda_device_count()  # Force ROCm/HIP runtime init before RealtimeSTT's imports corrupt it
from RealtimeSTT import AudioToTextRecorder
import manager_pb
import tts_pb
import classifier_pb
import grpc


class Manager:
    def __init__(self) -> None:
        self.channel = grpc.insecure_channel("localhost:50051")
        self.stub = manager_pb.ManagerStub(self.channel)


class TTS:
    def __init__(self) -> None:
        self.channel = grpc.insecure_channel("localhost:50052")
        self.stub = tts_pb.TTSStub(self.channel)


class Classifier:
    def __init__(self) -> None:
        self.channel = grpc.insecure_channel("localhost:50053")
        self.stub = classifier_pb.ClassifierStub(self.channel)


def speak_requests_from_prompt(prompt_stream):
    for token in prompt_stream:
        yield tts_pb.SpeakRequest(token=token.token)


class Orchestator:
    def process_text(self, text):
        print(text)

        label = self.classifier.stub.Classify(classifier_pb.BertRequest(prompt=text))

        print(label.label)

        prompt_stream = self.manager.stub.Prompt(
            manager_pb.PromptRequest(text=text, agent=label.label)
        )

        if label.label == 0:
            speech_result = self.tts.stub.Speak(
                speak_requests_from_prompt(prompt_stream)
            )

    def __init__(self) -> None:
        print("Wait until it says 'speak now'")
        self.manager = Manager()
        self.tts = TTS()
        self.classifier = Classifier()
        self.recorder = AudioToTextRecorder(
            language="es",
            post_speech_silence_duration=2.0,
            model="medium",
            device="cuda",
        )

    def start(self):
        while True:
            self.recorder.text(self.process_text)


if __name__ == "__main__":
    runner = Orchestator()
    runner.start()
