import hashlib
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from app.services.documents import DocumentsService
from app.services.retrieval import QueryService

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)


def get_documents(request: Request) -> DocumentsService:
    return request.app.state.resources.documents


def get_query(request: Request) -> QueryService:
    return request.app.state.resources.query


async def authorize(
    request: Request, supplied_key: Annotated[str | None, Security(api_key_header)]
):
    settings = request.app.state.settings
    provided = supplied_key or ""
    if settings.api_key and not secrets.compare_digest(
        provided.encode(), settings.api_key.encode()
    ):
        raise HTTPException(401, "Invalid or missing API key")
    ip = request.client.host if request.client else "unknown"
    route = request.scope["route"].path
    key = hashlib.sha256(f"{ip}:{request.method}:{route}".encode()).hexdigest()
    # One atomic operation; expiry cannot be lost between increment and expire.
    count = await request.app.state.resources.redis.eval(
        """
        local count = redis.call('INCR', KEYS[1])
        if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
        return count
    """,
        1,
        f"rag-fastapi:rate:{key}",
        settings.throttle_ttl_seconds,
    )
    if count > settings.throttle_limit:
        raise HTTPException(
            429, "Too many requests", headers={"Retry-After": str(settings.throttle_ttl_seconds)}
        )


Documents = Annotated[DocumentsService, Depends(get_documents)]
Query = Annotated[QueryService, Depends(get_query)]
