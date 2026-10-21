"""ARQ command entry point: arq app.worker.WorkerSettings."""

from app.workers.ingestion import WorkerSettings

__all__ = ["WorkerSettings"]
