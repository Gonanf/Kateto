import ctranslate2

ctranslate2.get_cuda_device_count()  # Force ROCm/HIP runtime init before RealtimeSTT's imports corrupt it
import torch
import torchaudio
from huggingface_hub import hf_hub_download
from transformers import (
    AutoModel,
    AutoFeatureExtractor,
    Wav2Vec2ForCTC,
    Wav2Vec2Processor,
)
from faster_whisper import WhisperModel
import librosa
from datasets import load_dataset
from torch.utils.data import DataLoader


def test_whisper():

    model = WhisperModel("deepdml/faster-whisper-large-v3-turbo-ct2")

    segments, info = model.transcribe("audio.mp3")
    for segment in segments:
        print("[%.2fs -> %.2fs] %s" % (segment.start, segment.end, segment.text))


# Preprocessing the datasets.
# We need to read the audio files as arrays
def speech_file_to_array_fn(batch):
    speech_array, sampling_rate = librosa.load(batch["path"], sr=16_000)
    batch["audio"] = speech_array
    batch["text"] = batch["text"].upper()
    return batch


def test_wav2vec():

    LANG_ID = "default"
    MODEL_ID = "jonatasgrosman/wav2vec2-large-xlsr-53-spanish"
    SAMPLES = 10

    test_dataset = load_dataset(
        "GianDiego/latam-spanish-speech-orpheus-tts-24khz",
        LANG_ID,
        split="train",
        streaming=True,
    )

    processor = Wav2Vec2Processor.from_pretrained(MODEL_ID)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL_ID)
    print(test_dataset)
    loader = DataLoader(test_dataset)

    for i, batch in enumerate(loader):
        batch = batch.map(speech_file_to_array_fn)
        inputs = processor(
            batch["audio"], sampling_rate=16_000, return_tensors="pt", padding=True
        )

        with torch.no_grad():
            logits = model(
                inputs.input_values, attention_mask=inputs.attention_mask
            ).logits

        predicted_ids = torch.argmax(logits, dim=-1)
        predicted_sentences = processor.batch_decode(predicted_ids)

        for i, predicted_sentence in enumerate(predicted_sentences):
            print("-" * 100)
            print("Reference:", test_dataset[i]["text"])
            print("Prediction:", predicted_sentence)
        break


def test_granite():
    # device = "cuda" if torch.cuda.is_available() else "cpu"
    # device = "cpu"

    model_name = "ibm-granite/granite-speech-4.1-2b-nar"
    model = AutoModel.from_pretrained(
        model_name,
        trust_remote_code=True,
        device_map=device,
        dtype=torch.bfloat16,
    ).eval()
    feature_extractor = AutoFeatureExtractor.from_pretrained(
        model_name, trust_remote_code=True
    )

    # Load sample audio from the repo
    audio_path = hf_hub_download(repo_id=model_name, filename="10226_10111_000000.wav")
    waveform, sr = torchaudio.load(audio_path)
    if sr != 16000:
        waveform = torchaudio.functional.resample(waveform, sr, 16000)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    waveform = waveform.squeeze(0)

    # Extract features and run inference
    inputs = feature_extractor([waveform], device=device)
    output = model.generate(**inputs)

    print(f"Prediction: {output.text_preds[0]}")
