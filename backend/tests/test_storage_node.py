import hashlib

from fastapi.testclient import TestClient

from storage_node import app as node_app


def test_atomic_fragment_write_read_and_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(node_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(node_app, "TOKEN", "test-secret")
    client = TestClient(node_app.app)
    body = b"binary\x00fragment\xff"
    headers = {"X-Internal-Token": "test-secret", "X-Fragment-SHA256": hashlib.sha256(body).hexdigest()}
    written = client.put("/internal/fragments/stripe-1", content=body, headers=headers)
    assert written.status_code == 200
    assert written.json()["sha256"] == hashlib.sha256(body).hexdigest()
    assert client.get("/internal/fragments/stripe-1", headers=headers).content == body
    assert client.head("/internal/fragments/stripe-1", headers=headers).status_code == 200
    assert client.delete("/internal/fragments/stripe-1", headers=headers).status_code == 200
    assert client.get("/internal/fragments/stripe-1", headers=headers).status_code == 404


def test_storage_node_rejects_bad_token_checksum_and_path(tmp_path, monkeypatch):
    monkeypatch.setattr(node_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(node_app, "TOKEN", "test-secret")
    client = TestClient(node_app.app)
    body = b"fragment"
    assert client.put("/internal/fragments/valid", content=body,
                      headers={"X-Internal-Token": "wrong"}).status_code == 401
    bad_checksum = {"X-Internal-Token": "test-secret", "X-Fragment-SHA256": "0" * 64}
    rejected = client.put("/internal/fragments/valid", content=body, headers=bad_checksum)
    assert rejected.status_code == 422
    assert not (tmp_path / "valid").exists()
    traversal = client.put("/internal/fragments/%2e%2e%2fescape", content=body,
                           headers={"X-Internal-Token": "test-secret"})
    assert traversal.status_code in (400, 404)
    assert not (tmp_path.parent / "escape").exists()
