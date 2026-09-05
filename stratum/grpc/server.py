from concurrent import futures
from pathlib import Path
import grpc

from stratum.grpc import stratum_pb2,stratum_pb2_grpc
from stratum.engine import Engine

class StratumServicer(stratum_pb2_grpc.StratumServicer):
    def __init__(self, engine):
        self.engine = engine

    def Get(self, request, context):
        value = self.engine.get(request.key)
        if value is None:
            return stratum_pb2.GetResponse(found = False)
        return stratum_pb2.GetResponse(value=value, found=True)

    def Put(self, request, context):
        self.engine.put(request.key, request.value)
        return stratum_pb2.PutResponse(success=True)


def serve():
    engine = Engine(Path('./data'))
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    stratum_pb2_grpc.add_StratumServicer_to_server(StratumServicer(engine), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("gRPC server running on port 50051")
    server.wait_for_termination()



if __name__ == "__main__":
    serve()