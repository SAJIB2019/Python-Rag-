import asyncio
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["operations"])


@router.get("/health")
async def health(request: Request):
    return {
        "status": "ok",
        "service": "rag-from-zero",
        "environment": request.app.state.settings.node_env,
    }


async def measure(operation):
    start = time.monotonic()
    try:
        async with asyncio.timeout(2):
            await operation()
        status = "up"
    except Exception:
        status = "down"
    return {"status": status, "latencyMs": round((time.monotonic() - start) * 1000)}


@router.get("/health/ready")
async def ready(request: Request):
    resources = request.app.state.resources
    operations = {
        "postgres": lambda: resources.pool.fetchval("SELECT 1"),
        "redis": resources.redis.ping,
    }
    if resources.search.enabled:
        operations["search"] = resources.search.check_readiness
    results = await asyncio.gather(*(measure(op) for op in operations.values()))
    checks = dict(zip(operations, results, strict=True))
    ok = all(check["status"] == "up" for check in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "error", "checks": checks}, status_code=200 if ok else 503
    )


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request):
    expected = request.app.state.settings.metrics_api_key
    bearer = request.headers.get("authorization", "")
    supplied = request.headers.get("x-metrics-api-key", "") or (
        bearer[7:] if bearer.startswith("Bearer ") else ""
    )
    if expected and not secrets.compare_digest(expected.encode(), supplied.encode()):
        raise HTTPException(401, "Invalid or missing metrics API key")
    return Response(
        generate_latest(request.app.state.metrics_registry),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )
