import pytest

from config import PipelineConfig
from models import Classification, InboundEmail, PipelineResult
from server import create_app


class FakePipeline:
    def __init__(self):
        self.calls = []

    def process_email(self, email: InboundEmail, persist: bool = True) -> PipelineResult:
        self.calls.append((email, persist))
        return PipelineResult(email=email, classification=Classification.JUNK)


@pytest.fixture
def client(base_config):
    app = create_app(base_config, FakePipeline())
    app.config["TESTING"] = True
    return app.test_client()


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_ingest_requires_secret(client):
    r = client.post("/ingest", json={"body_plain": "hi", "message_id": "m1"})
    assert r.status_code == 401
    r = client.post("/ingest", json={"body_plain": "hi"}, headers={"X-Webhook-Secret": "wrong"})
    assert r.status_code == 401


def test_ingest_with_secret_processes(client):
    r = client.post("/ingest", json={"body_plain": "hi", "sender_email": "a@b.com"}, headers={"X-Webhook-Secret": "s3cret"})
    assert r.status_code == 200
    assert r.get_json()["classification"] == "JUNK"


def test_demo_does_not_persist(base_config):
    fake = FakePipeline()
    app = create_app(base_config, fake)
    c = app.test_client()
    r = c.post("/demo/classify", json={"body": "hello"}, headers={"X-Webhook-Secret": "s3cret"})
    assert r.status_code == 200
    assert fake.calls[0][1] is False


def test_auth_check(client):
    assert client.get("/auth/check").status_code == 401
    assert client.get("/auth/check", headers={"X-Webhook-Secret": "s3cret"}).status_code == 200


def test_fails_closed_without_secret():
    app = create_app(PipelineConfig(openai_api_key="k"), FakePipeline())
    c = app.test_client()
    r = c.post("/ingest", json={"body_plain": "hi"}, headers={"X-Webhook-Secret": ""})
    assert r.status_code == 503


def test_root_serves_ui(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Plexa" in r.data


def test_non_ascii_secret_is_401_not_500(client):
    r = client.post("/ingest", json={"body_plain": "hi", "sender_email": "a@b.com"}, headers={"X-Webhook-Secret": "s\u00e9cret"})
    assert r.status_code == 401


def test_ingest_rejects_list_body(client):
    r = client.post("/ingest", json=[{"sender_email": "a@b.com"}], headers={"X-Webhook-Secret": "s3cret"})
    assert r.status_code == 400
    assert r.get_json() == {"error": "sender_email required"}


def test_ingest_requires_sender_email(client):
    r = client.post("/ingest", json={"body_plain": "hi"}, headers={"X-Webhook-Secret": "s3cret"})
    assert r.status_code == 400
    assert r.get_json() == {"error": "sender_email required"}


def test_health_reports_ai_provider_and_host():
    cfg = PipelineConfig(opencode_api_key="oc", webhook_secret="s")
    app = create_app(cfg, FakePipeline())
    body = app.test_client().get("/health").get_json()
    assert body["ai"] == {"provider": "opencode", "base_url": "https://opencode.ai/inference/go/v1"}

    body = create_app(PipelineConfig(openai_api_key="k"), FakePipeline()).test_client().get("/health").get_json()
    assert body["ai"] == {"provider": "openai", "base_url": None}
