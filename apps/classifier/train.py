from datasets import Dataset
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    TrainingArguments,
    Trainer,
    pipeline,
)
import pandas as pd
import torch

# Load data
df = pd.read_csv("./data/coarse_grained.csv")
label2id = {"talk": 0, "think": 1}
id2label = {0: "talk", 1: "think"}
df["label"] = df["label"].map(label2id)

dataset = Dataset.from_pandas(df).train_test_split(test_size=0.2)

# Tokenize
tokenizer = AutoTokenizer.from_pretrained("distilbert-base-uncased")


def tokenize(batch):
    return tokenizer(batch["text"], truncation=True, padding=True)


dataset = dataset.map(tokenize, batched=True)

# Train
model = AutoModelForSequenceClassification.from_pretrained(
    "distilbert-base-uncased", num_labels=2, label2id=label2id
)

args = TrainingArguments(
    output_dir="./intent-classifier",
    num_train_epochs=3,
    per_device_train_batch_size=16,
    eval_strategy="epoch",
)

trainer = Trainer(
    model=model,
    args=args,
    train_dataset=dataset["train"],
    eval_dataset=dataset["test"],
)

trainer.train()

# Testing
fill_mask = pipeline("text-classification", model=model, tokenizer=tokenizer)

examples = [
    "Hoy necesito crear 10 proyectos.Cuantas tareas me faltan?",
    "Cuantas tareas me faltan hacer kateto?",
    "Kateto?",
    "Entonces... necesitare uno nuevo...",
]

for ex in examples:
    result = fill_mask(ex)
    print(ex, "LABEL:", result[0]["label"], "CONFIDENCE:", result[0]["score"])
