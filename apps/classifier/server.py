from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
import classifier_pb
import grpc
from concurrent import futures


class ClassifierServicer(classifier_pb.ClassifierServicer):
    def __init__(self) -> None:
        super().__init__()
        self.model = AutoModelForSequenceClassification.from_pretrained(
            "intent-classifier/checkpoint-150",
            id2label={0: "talk", 1: "think"},
            label2id={"talk": 0, "think": 1},
        )
        self.tokenizer = AutoTokenizer.from_pretrained("distilbert-base-uncased")

        self.classifier = pipeline(
            "text-classification", model=self.model, tokenizer=self.tokenizer
        )

    def Classify(self, request, context):
        response = self.classifier(request.prompt)
        return classifier_pb.BertResponse(label=response[0]["label"])


# model = AutoModelForSequenceClassification.from_pretrained(
#     "intent-classifier/checkpoint-150",
#     id2label={0: "talk", 1: "think"},
#     label2id={"talk": 0, "think": 1},
# )
# tokenizer = AutoTokenizer.from_pretrained("distilbert-base-uncased")
#
# classifier = pipeline("text-classification", model=model, tokenizer=tokenizer)
#
#
# result = classifier("Cuantas tareas me faltan?")
# print("RESULT:", result[0]["label"])
#
server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
classifier_pb.add_ClassifierServicer_to_server(ClassifierServicer(), server)
server.add_insecure_port("[::]:50053")
server.start()
server.wait_for_termination()
