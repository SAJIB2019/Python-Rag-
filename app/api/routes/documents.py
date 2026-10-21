from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.dependencies import Documents, authorize
from app.schemas import CreateDocument, DocumentResponse

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(authorize)])


@router.post("", response_model=DocumentResponse, status_code=201)
async def create_document(body: CreateDocument, service: Documents):
    return await service.create(body.filename, body.mimeType, body.content, body.source)


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    service: Documents,
    file: Annotated[UploadFile, File()],
    source: Annotated[str | None, Form(max_length=2048)] = None,
):
    return await service.upload(file, source.strip() if source else source)


@router.get("/{document_id}", response_model=DocumentResponse)
async def find_document(document_id: UUID, service: Documents):
    return await service.find(document_id)
