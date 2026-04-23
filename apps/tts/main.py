from concurrent import futures
from RealtimeTTS import TextToAudioStream, SystemEngine, AzureEngine, ElevenlabsEngine
import tts_pb
import grpc


class TTS(tts_pb.TTSServicer):
    def __init__(self) -> None:
        super().__init__()
        self.engine = SystemEngine(voice="Spanish (Latin America)")
        self.stream = TextToAudioStream(self.engine, log_characters=True)

    def Speak(self, request_iterator, context):
        for token in request_iterator:
            print("=" * 50)
            print(token.token, end="")
            self.stream.feed(token.token)
            self.stream.play_async()

        print("=" * 50)
        return tts_pb.SpeakResponse()

    def serve(self):
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
        tts_pb.add_TTSServicer_to_server(self, server)
        server.add_insecure_port("[::]:50052")
        server.start()
        server.wait_for_termination()


def main():
    print("Hello from tts!")
    runner = TTS()
    runner.serve()


if __name__ == "__main__":
    main()
