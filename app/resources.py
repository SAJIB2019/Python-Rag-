from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

import asyncpg
import httpx
from arq import create_pool

from app.core.telemetry import configure
from app.db.repository import Repository
from app.integrations.providers import (
    FakeEmbeddingProvider,
    FakeLlmProvider,
    OpenAICompatibleProvider,
)
from app.services.documents import DocumentsService
from app.services.retrieval import QueryService
from app.services.search import SearchService


@dataclass
class Resources:
    pool: object
    redis: object
    repository: Repository
    search: SearchService
    embeddings: object
    documents: DocumentsService
    query: QueryService


@asynccontextmanager
async def open_resources(settings):
    async with AsyncExitStack() as stack:
        pool = await asyncpg.create_pool(
            settings.database_url, min_size=1, max_size=20, command_timeout=30, timeout=5
        )
        stack.push_async_callback(pool.close)
        redis = await create_pool(settings.redis_settings(), default_queue_name=settings.queue_name)
        stack.push_async_callback(redis.aclose)
        client = await stack.enter_async_context(
            httpx.AsyncClient(
                timeout=settings.openai_compatible_timeout_ms / 1000,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            )
        )
        telemetry = configure(settings)
        if telemetry:
            stack.callback(telemetry.shutdown)
        repository = Repository(pool)
        remote = OpenAICompatibleProvider(settings, client)
        embeddings = (
            remote
            if settings.embedding_provider == "openai-compatible"
            else FakeEmbeddingProvider(settings.embedding_dimensions)
        )
        llm = remote if settings.llm_provider == "openai-compatible" else FakeLlmProvider()
        search = SearchService(settings, repository, client)
        await search.ensure_indexes()
        yield Resources(
            pool,
            redis,
            repository,
            search,
            embeddings,
            DocumentsService(repository, redis, settings),
            QueryService(search, embeddings, llm),
        )
