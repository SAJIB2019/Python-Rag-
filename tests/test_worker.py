from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from arq import Retry

from app.workers.ingestion import process_document


@pytest.mark.parametrize("attempt", [1, 3])
async def test_failed_ingestion_retries_then_stays_failed(attempt):
    connection = AsyncMock()
    connection.fetchval.return_value = True
    connection.fetchrow.return_value = {"status": "queued", "raw_text": "some content"}

    @asynccontextmanager
    async def acquire():
        yield connection

    resources = SimpleNamespace(
        pool=SimpleNamespace(acquire=acquire),
        repository=AsyncMock(),
        embeddings=AsyncMock(),
        search=AsyncMock(),
    )
    resources.embeddings.embed.side_effect = RuntimeError("provider unavailable")
    document_id = uuid4()
    with pytest.raises(Retry if attempt < 3 else RuntimeError):
        await process_document({"resources": resources, "job_try": attempt}, str(document_id))
    assert resources.repository.set_status.call_args_list[-1].args == (document_id, "failed")
    resources.repository.replace_chunks.assert_not_called()
    resources.search.sync_document.assert_not_called()
    assert "pg_advisory_unlock" in connection.execute.call_args.args[0]
