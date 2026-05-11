from concurrent import futures
from typing import Callable, Generator
import grpc
import manager_pb
from modules.core.product_owner_server import ProductOwnerServicer


class Manager(manager_pb.ManagerServicer):
    def __init__(
        self, PromptFunction: Callable[..., Generator[manager_pb.PromptResponse]]
    ) -> None:
        super().__init__()
        self.PromptFunction = PromptFunction

    def Prompt(self, request, context):
        print("Got Request:", request)
        return self.PromptFunction(request, context)

    def start(self):
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
        manager_pb.add_ManagerServicer_to_server(self, self.server)
        manager_pb.add_ProductOwnerServicer_to_server(
            ProductOwnerServicer(), self.server
        )
        self.server.add_insecure_port("[::]:50051")
        self.server.add_insecure_port("127.0.0.1:50051")
        self.server.start()

    def stop(self):
        self.server.stop(0)

    def serve(self):
        self.start()
        self.server.wait_for_termination()
