from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.integrations.providers import FakeEmbeddingProvider, FakeLlmProvider
from app.main import create_app
from app.schemas import DocumentResponse
from app.services.documents import DocumentsService
from app.services.retrieval import QueryService


@pytest.fixture
def client():
    settings = Settings(
        _env_file=None,
        api_key="test-key",
        metrics_api_key="metrics-key",
        upload_max_file_bytes=1024,
    )
    repository, redis, pool, search = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    redis.eval.return_value = 1
    search.enabled = False
    search.vector_search.return_value = []
    search.keyword_search.return_value = []
    stored = {}

    async def create(filename, mime_type, content, source):
        now = datetime.now(UTC)
        doc = DocumentResponse(
            id=uuid4(),
            status="queued",
            filename=filename,
            mimeType=mime_type,
            source=source,
            createdAt=now,
            updatedAt=now,
        )
        stored[doc.id] = doc
        return doc

    async def find(key):
        return stored.get(key)

    repository.create.side_effect = create
    repository.find.side_effect = find
    resources = SimpleNamespace(
        pool=pool,
        redis=redis,
        search=search,
        documents=DocumentsService(repository, redis, settings),
        query=QueryService(search, FakeEmbeddingProvider(8), FakeLlmProvider()),
    )

    @asynccontextmanager
    async def factory(settings):
        yield resources

    with TestClient(create_app(settings, factory)) as test_client:
        test_client.headers["x-api-key"] = "test-key"
        test_client.resources = resources
        yield test_client


def test_health_and_auth(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/health/ready").status_code == 200
    assert (
        client.post(
            "/api/query", headers={"x-api-key": "wrong"}, json={"question": "hi"}
        ).status_code
        == 401
    )


def test_create_get_upload_and_query(client):
    response = client.post(
        "/api/documents",
        json={"filename": "a.txt", "mimeType": "text/plain", "content": "Refunds within 30 days"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "queued"
    assert client.get("/api/documents/" + response.json()["id"]).json() == response.json()
    response = client.post(
        "/api/documents/upload",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"source": " test "},
    )
    assert response.status_code == 201 and response.json()["source"] == "test"
    response = client.post("/api/query", json={"question": " Refund? "})
    assert response.status_code == 201 and response.json()["question"] == "Refund?"
    assert response.json()["sources"] == []
    assert response.headers["x-request-id"]


def test_validation_and_missing_documents(client):
    assert client.get("/api/documents/not-a-uuid").status_code == 400
    assert client.get(f"/api/documents/{uuid4()}").status_code == 404
    assert client.post("/api/query", json={"question": " "}).status_code == 400
    assert client.post("/api/documents/upload").status_code == 400
    assert (
        client.post("/api/documents/upload", files={"file": ("a.txt", b"a" * 1025)}).status_code
        == 400
    )
    assert (
        client.post("/api/documents/upload", files={"file": ("a.txt", b"a" * 70000)}).status_code
        == 413
    )


def test_rate_limit_metrics_and_readiness(client):
    client.resources.redis.eval.return_value = 61
    assert client.post("/api/query", json={"question": "hi"}).status_code == 429
    assert client.get("/api/metrics").status_code == 401
    response = client.get("/api/metrics", headers={"authorization": "Bearer metrics-key"})
    assert response.status_code == 200 and "rag_http_requests_total" in response.text
    client.resources.pool.fetchval.side_effect = RuntimeError("private connection detail")
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert "private connection detail" not in response.text


def test_queue_outage_leaves_durable_queued_document(client):
    client.resources.redis.enqueue_job.side_effect = ConnectionError("offline")
    response = client.post(
        "/api/documents", json={"filename": "a.txt", "mimeType": "text/plain", "content": "text"}
    )
    assert response.status_code == 201 and response.json()["status"] == "queued"


def test_cors_preflight(client):
    response = client.options(
        "/api/query",
        headers={"origin": "http://localhost:3000", "access-control-request-method": "POST"},
    )
    assert response.status_code == 200 and response.headers["access-control-allow-origin"] == "*"
