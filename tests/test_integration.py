import os
from uuid import UUID, uuid4

import httpx
import pytest
from arq import create_pool
from arq.worker import Worker

from app.core.config import Settings
from app.main import create_app
from app.workers.ingestion import dispatch_queued, process_document

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1",
        reason="Set RUN_INTEGRATION=1 with dedicated test services",
    ),
]


async def test_database_queue_worker_and_retrieval():
    settings = Settings(
        api_key="integration-key",
        throttle_limit=10000,
        queue_name="rag-fastapi:test:" + str(uuid4()),
    )
    app = create_app(settings)
    document_ids = []
    async with app.router.lifespan_context(app):
        resources = app.state.resources
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"x-api-key": "integration-key"},
        ) as client:
            try:
                response = await client.post(
                    "/api/documents",
                    json={
                        "filename": "integration-policy.txt",
                        "mimeType": "text/plain",
                        "content": "Customers can request refunds within 30 days. Keep your receipt.",
                    },
                )
                assert response.status_code == 201, response.text
                document_id = UUID(response.json()["id"])
                document_ids.append(document_id)
                upload = await client.post(
                    "/api/documents/upload",
                    files={
                        "file": ("terms.md", b"Payment is due within 15 days.", "text/markdown")
                    },
                )
                assert upload.status_code == 201
                document_ids.append(UUID(upload.json()["id"]))
                worker = Worker(
                    functions=[process_document],
                    redis_pool=await create_pool(settings.redis_settings()),
                    queue_name=settings.queue_name,
                    burst=True,
                    handle_signals=False,
                    ctx={"resources": resources, "settings": settings},
                    keep_result=0,
                )
                try:
                    await worker.async_run()
                finally:
                    await worker.close()
                assert worker.jobs_complete == 2 and worker.jobs_failed == 0
                document = await client.get(f"/api/documents/{document_id}")
                assert document.json()["status"] == "completed"
                response = await client.post(
                    "/api/query", json={"question": "When can customers request refunds?"}
                )
                assert response.status_code == 201, response.text
                assert any(s["documentId"] == str(document_id) for s in response.json()["sources"])
                chunks_before = await resources.pool.fetchval(
                    "SELECT count(*) FROM document_chunks WHERE document_id=$1", document_id
                )
                await process_document({"resources": resources}, str(document_id))
                assert (
                    await resources.pool.fetchval(
                        "SELECT count(*) FROM document_chunks WHERE document_id=$1", document_id
                    )
                    == chunks_before
                )
                assert (await client.get("/api/health/ready")).status_code == 200
                # A committed queued row survives an enqueue failure; dispatcher recovers it.
                pending = await resources.repository.create(
                    "pending.txt", "text/plain", "Recovered policy", None
                )
                document_ids.append(pending.id)
                await dispatch_queued({"resources": resources, "settings": settings})
                assert (
                    await resources.redis.zscore(settings.queue_name, f"document:{pending.id}")
                    is not None
                )
            finally:
                await resources.pool.execute(
                    "DELETE FROM documents WHERE id=ANY($1::uuid[])", document_ids
                )
                for document_id in document_ids:
                    if resources.search.enabled:
                        await resources.search.sync_document(document_id)
                    await resources.redis.delete(f"arq:job:document:{document_id}")
                await resources.redis.delete(settings.queue_name)
