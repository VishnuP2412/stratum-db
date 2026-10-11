from pathlib import Path

from fastapi.testclient import TestClient

from ui.app import create_app


def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "data"))


def test_put_get_round_trip(tmp_path):
    response = client(tmp_path).put("/api/put", json={"key": "alpha", "value": "one"})
    assert response.status_code == 200
    response = client(tmp_path).get("/api/get", params={"key": "alpha"})
    assert response.json()["value"]["value"] == "one"


def test_get_miss(tmp_path):
    response = client(tmp_path).get("/api/get", params={"key": "missing"})
    assert response.status_code == 200
    assert response.json()["found"] is False


def test_delete_and_inclusive_scan(tmp_path):
    test_client = client(tmp_path)
    for key in ("a", "b", "c"):
        test_client.put("/api/put", json={"key": key, "value": key})
    test_client.post("/api/delete", json={"key": "b"})
    response = test_client.get("/api/scan", params={"start": "a", "end": "c"})
    assert [item["key"]["value"] for item in response.json()["items"]] == ["a", "c"]


def test_empty_key_returns_400(tmp_path):
    response = client(tmp_path).put("/api/put", json={"key": "", "value": "value"})
    assert response.status_code == 400
    assert "must not be empty" in response.json()["detail"]


def test_limit_cap(tmp_path):
    response = client(tmp_path).get("/api/scan", params={"start": "a", "end": "z", "limit": 1001})
    assert response.status_code == 400
    assert "1000" in response.json()["detail"]


def test_compact_then_scan_consistency(tmp_path):
    test_client = client(tmp_path)
    test_client.put("/api/put", json={"key": "keep", "value": "v"})
    test_client.put("/api/put", json={"key": "remove", "value": "v"})
    test_client.post("/api/delete", json={"key": "remove"})
    assert test_client.post("/api/compact").status_code == 200
    response = test_client.get("/api/scan", params={"start": "a", "end": "z"})
    assert [item["key"]["value"] for item in response.json()["items"]] == ["keep"]


def test_page_does_not_use_innerhtml():
    page = (Path(__file__).parents[1] / "static" / "index.html").read_text()
    assert "innerHTML" not in page
