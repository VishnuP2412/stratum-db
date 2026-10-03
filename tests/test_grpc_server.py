from concurrent import futures

import grpc
import pytest

from stratum.engine import Engine
from stratum.grpc import stratum_pb2, stratum_pb2_grpc
from stratum.grpc.server import StratumServicer


@pytest.fixture
def grpc_client(tmp_path):
    engine = Engine(tmp_path)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    stratum_pb2_grpc.add_StratumServicer_to_server(StratumServicer(engine), server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()

    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    grpc.channel_ready_future(channel).result(timeout=5)
    try:
        yield engine, channel, stratum_pb2_grpc.StratumStub(channel)
    finally:
        channel.close()
        server.stop(0).wait()


def test_put_then_get_round_trip(grpc_client):
    _, _, stub = grpc_client

    response = stub.Put(stratum_pb2.PutRequest(key=b"key", value=b"value"))

    assert response.success
    assert stub.Get(stratum_pb2.GetRequest(key=b"key")) == stratum_pb2.GetResponse(
        value=b"value", found=True
    )


def test_get_missing_key_returns_not_found_result(grpc_client):
    _, _, stub = grpc_client

    response, call = stub.Get.with_call(stratum_pb2.GetRequest(key=b"missing"))

    assert call.code() == grpc.StatusCode.OK
    assert response.found is False
    assert response.value == b""


def test_put_empty_key_returns_invalid_argument(grpc_client):
    _, _, stub = grpc_client

    with pytest.raises(grpc.RpcError) as error:
        stub.Put(stratum_pb2.PutRequest(value=b"value"))

    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert error.value.details() == "key must not be empty"


def test_get_empty_key_returns_invalid_argument(grpc_client):
    _, _, stub = grpc_client

    with pytest.raises(grpc.RpcError) as error:
        stub.Get(stratum_pb2.GetRequest())

    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert error.value.details() == "key must not be empty"


def test_scan_returns_multiple_results_in_key_order(grpc_client):
    _, _, stub = grpc_client
    for key in (b"c", b"a", b"b"):
        stub.Put(stratum_pb2.PutRequest(key=key, value=key.upper()))

    results = list(
        stub.Scan(stratum_pb2.ScanRequest(start_key=b"a", end_key=b"c"))
    )

    assert [(result.key, result.value) for result in results] == [
        (b"a", b"A"),
        (b"b", b"B"),
        (b"c", b"C"),
    ]


def test_scan_empty_range_returns_no_results(grpc_client):
    _, _, stub = grpc_client
    stub.Put(stratum_pb2.PutRequest(key=b"a", value=b"A"))
    stub.Put(stratum_pb2.PutRequest(key=b"c", value=b"C"))

    assert list(
        stub.Scan(stratum_pb2.ScanRequest(start_key=b"b", end_key=b"b"))
    ) == []


def test_scan_start_after_end_returns_no_results(grpc_client):
    _, _, stub = grpc_client

    assert list(
        stub.Scan(stratum_pb2.ScanRequest(start_key=b"z", end_key=b"a"))
    ) == []


@pytest.mark.parametrize("scan_request", [
    stratum_pb2.ScanRequest(end_key=b"z"),
    stratum_pb2.ScanRequest(start_key=b"a"),
])
def test_scan_empty_bound_returns_invalid_argument(grpc_client, scan_request):
    _, _, stub = grpc_client

    with pytest.raises(grpc.RpcError) as error:
        list(stub.Scan(scan_request))

    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_scan_omits_tombstoned_key(grpc_client):
    engine, _, stub = grpc_client
    engine.put(b"deleted", b"old-value")
    engine.write_table()
    engine.delete(b"deleted")
    engine.write_table()

    assert list(
        stub.Scan(stratum_pb2.ScanRequest(start_key=b"deleted", end_key=b"deleted"))
    ) == []


def test_malformed_wire_request_returns_internal_status(grpc_client):
    _, channel, _ = grpc_client
    raw_get = channel.unary_unary(
        "/stratum.Stratum/Get",
        request_serializer=lambda payload: payload,
        response_deserializer=stratum_pb2.GetResponse.FromString,
    )

    with pytest.raises(grpc.RpcError) as error:
        raw_get(b"\x00")

    assert error.value.code() == grpc.StatusCode.INTERNAL


def test_non_bytes_request_field_is_rejected_before_rpc():
    with pytest.raises(TypeError):
        stratum_pb2.GetRequest(key="not-bytes")