from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.base import InputModel


class CreateDocument(InputModel):
    filename: str = Field(min_length=1, max_length=255)
    mimeType: Literal["application/pdf", "text/plain", "text/markdown"]
    content: str = Field(min_length=1, max_length=200000)
    source: str | None = Field(default=None, max_length=2048)


class DocumentResponse(BaseModel):
    id: UUID
    status: Literal["uploaded", "queued", "processing", "completed", "failed"]
    filename: str
    mimeType: str
    source: str | None
    createdAt: datetime
    updatedAt: datetime
