from RealtimeTTS import TextToAudioStream, SystemEngine, AzureEngine, ElevenlabsEngine


def main():
    print("Hello from tts!")
    engine = SystemEngine(
        voice="Spanish (Latin America)"
    )  # replace with your TTS engine
    stream = TextToAudioStream(engine, log_characters=True)

    stream.feed("Hola, como estas?")
    stream.play_async()


if __name__ == "__main__":
    main()
