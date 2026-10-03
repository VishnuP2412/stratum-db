from concurrent import futures
from pathlib import Path
import grpc

from stratum.grpc import stratum_pb2,stratum_pb2_grpc
from stratum.engine import Engine

class StratumServicer(stratum_pb2_grpc.StratumServicer):
    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def _require_key(key, context, field_name):
        if not key:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"{field_name} must not be empty",
            )

    def Get(self, request, context):
        self._require_key(request.key, context, "key")
        value = self.engine.get(request.key)
        if value is None:
            return stratum_pb2.GetResponse(found = False)
        return stratum_pb2.GetResponse(value=value, found=True)

    def Put(self, request, context):
        self._require_key(request.key, context, "key")
        self.engine.put(request.key, request.value)
        return stratum_pb2.PutResponse(success=True)

    def Scan(self, request, context):
        self._require_key(request.start_key, context, "start_key")
        self._require_key(request.end_key, context, "end_key")
        for key, value in self.engine.scan(request.start_key, request.end_key):
            yield stratum_pb2.KVPair(key=key, value=value)

def serve(data_dir, table_dir=None, port=50051):
    engine = Engine(data_dir = data_dir, table_dir= table_dir)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    stratum_pb2_grpc.add_StratumServicer_to_server(StratumServicer(engine), server)
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    print(f"gRPC server running on port {port}")
    server.wait_for_termination()