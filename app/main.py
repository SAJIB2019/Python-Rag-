from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CollectorRegistry, Counter, Histogram
from starlette.middleware.gzip import GZipMiddleware

from app.api.routes import documents, health, query
from app.core.config import Settings
from app.core.exceptions import register_exception_handlers
from app.core.middleware import RequestMiddleware
from app.resources import open_resources


def create_app(settings: Settings | None = None, resource_factory=open_resources) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        async with resource_factory(settings) as resources:
            app.state.resources = resources
            yield

    app = FastAPI(title="RAG From Zero — FastAPI", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    registry = CollectorRegistry()
    app.state.metrics_registry = registry
    counter = Counter(
        "rag_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=registry
    )
    histogram = Histogram(
        "rag_http_request_duration_seconds", "HTTP latency", ["method", "route"], registry=registry
    )
    app.add_middleware(RequestMiddleware, settings=settings, counter=counter, histogram=histogram)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[s.strip() for s in settings.cors_origin.split(",")],
        allow_methods=["GET", "POST"],
        allow_headers=[
            "content-type",
            "x-api-key",
            "x-request-id",
            "x-metrics-api-key",
            "authorization",
        ],
        expose_headers=["x-request-id"],
    )

    register_exception_handlers(app)

    for router in (documents.router, query.router, health.router):
        app.include_router(router, prefix="/api")
    return app


app = create_app()
