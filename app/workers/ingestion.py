import asyncio
import logging
from uuid import UUID

from arq import Retry, cron

from app.core.config import Settings
from app.core.telemetry import span
from app.resources import open_resources
from app.services.ingestion import chunk_text, clean_text

logger = logging.getLogger(__name__)


async def dispatch_queued(ctx):
    resources, settings = ctx["resources"], ctx["settings"]
    for row in await resources.repository.queued_ids():
        await resources.redis.enqueue_job(
            "process_document",
            str(row["id"]),
            _job_id=f"document:{row['id']}",
            _queue_name=settings.queue_name,
        )


async def process_document(ctx, document_id: str):
    resources = ctx["resources"]
    document_uuid = UUID(document_id)
    # A session lock serializes retries and duplicate jobs across workers.
    async with resources.pool.acquire() as conn:
        locked = await conn.fetchval(
            "SELECT pg_try_advisory_lock(hashtextextended($1,0))", document_id
        )
        if not locked:
            raise Retry(defer=5)
        try:
            row = await conn.fetchrow(
                "SELECT status, raw_text FROM documents WHERE id=$1", document_uuid
            )
            if row is None or row["status"] == "completed":
                return
            await resources.repository.set_status(document_uuid, "processing")
            with span("rag.ingest"):
                chunks = await asyncio.to_thread(chunk_text, clean_text(row["raw_text"] or ""))
                if not chunks:
                    raise ValueError("Document contains no indexable text")
                for chunk in chunks:
                    chunk["embedding"] = await resources.embeddings.embed(chunk["content"])
                await resources.repository.replace_chunks(conn, document_uuid, chunks)
                with span("rag.index"):
                    await resources.search.sync_document(document_uuid)
                await resources.repository.set_status(document_uuid, "completed")
        except asyncio.CancelledError:
            # ARQ retries interrupted jobs when the worker resumes.
            raise
        except Exception as exc:
            await resources.repository.set_status(document_uuid, "failed")
            logger.exception("Document processing failed: %s", document_id)
            if ctx.get("job_try", 1) < 3:
                raise Retry(defer=2 ** ctx.get("job_try", 1)) from exc
            raise
        finally:
            await conn.execute("SELECT pg_advisory_unlock(hashtextextended($1,0))", document_id)


async def startup(ctx):
    ctx["settings"] = Settings()
    ctx["resource_context"] = open_resources(ctx["settings"])
    ctx["resources"] = await ctx["resource_context"].__aenter__()
    try:
        await dispatch_queued(ctx)
    except BaseException:
        await ctx["resource_context"].__aexit__(None, None, None)
        raise


async def shutdown(ctx):
    await ctx["resource_context"].__aexit__(None, None, None)


class WorkerSettings:
    functions = [process_document]
    cron_jobs = [cron(dispatch_queued, second={0, 30}, keep_result=0)]
    redis_settings = Settings().redis_settings()
    queue_name = Settings().queue_name
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 4
    max_tries = 3
    job_timeout = 900
    keep_result = 0
    health_check_interval = 30
