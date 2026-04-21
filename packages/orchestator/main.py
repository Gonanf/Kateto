import ctranslate2

ctranslate2.get_cuda_device_count()  # Force ROCm/HIP runtime init before RealtimeSTT's imports corrupt it
from RealtimeSTT import AudioToTextRecorder


def process_text(text):
    print(text)


if __name__ == "__main__":
    print("Wait until it says 'speak now'")
    recorder = AudioToTextRecorder()

    while True:
        recorder.text(process_text)
