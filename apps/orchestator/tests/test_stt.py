import torch
import torchaudio
from huggingface_hub import hf_hub_download
from transformers import AutoModel, AutoFeatureExtractor


def test_granite():
    # device = "cuda" if torch.cuda.is_available() else "cpu"
    device = "cpu"

    model_name = "ibm-granite/granite-speech-4.1-2b-nar"
    model = AutoModel.from_pretrained(
        model_name,
        trust_remote_code=True,
        attn_implementation="flash_attention_2",
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
