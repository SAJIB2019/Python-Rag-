import asyncio
import logging

from fastapi import HTTPException

from app.services.ingestion import extract_file

logger = logging.getLogger(__name__)


class DocumentsService:
    def __init__(self, repository, redis, settings):
        self.repository, self.redis, self.settings = repository, redis, settings

    async def create(self, filename, mime_type, content, source=None):
        document = await self.repository.create(filename, mime_type, content, source)
        try:
            await self.redis.enqueue_job(
                "process_document",
                str(document.id),
                _job_id=f"document:{document.id}",
                _queue_name=self.settings.queue_name,
            )
        except Exception:
            # The queued database row is durable; the worker's periodic dispatcher retries it.
            logger.exception("Queue unavailable; document %s awaits dispatch", document.id)
        return document

    async def upload(self, file, source):
        try:
            data = await file.read(self.settings.upload_max_file_bytes + 1)
        finally:
            await file.close()
        if len(data) > self.settings.upload_max_file_bytes:
            raise HTTPException(400, "Uploaded file is too large")
        filename = (file.filename or "upload").strip()
        if len(filename) > 255 or not filename:
            raise HTTPException(400, "Filename must contain 1 to 255 characters")
        try:
            content, mime_type = await asyncio.to_thread(
                extract_file, data, filename, file.content_type or ""
            )
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise HTTPException(400, str(exc)) from exc
            raise HTTPException(400, "Could not parse the uploaded file") from exc
        return await self.create(filename, mime_type, content, source)

    async def find(self, document_id):
        document = await self.repository.find(document_id)
        if document is None:
            raise HTTPException(404, f"Document {document_id} not found")
        return document
