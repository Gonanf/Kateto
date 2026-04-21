from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline

model = AutoModelForSequenceClassification.from_pretrained("intent-classifier/checkpoint-150",
    id2label={0: "talk", 1: "think"},
    label2id={"talk": 0, "think": 1},)
tokenizer = AutoTokenizer.from_pretrained("distilbert-base-uncased")

classifier = pipeline("text-classification", model=model, tokenizer=tokenizer)

result = classifier("Cuantas tareas me faltan?")
print(result)
