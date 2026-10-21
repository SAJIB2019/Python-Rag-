from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.base import InputModel


class QueryInput(InputModel):
    question: str = Field(min_length=1, max_length=2000)


class RetrievedChunk(BaseModel):
    documentId: str
    filename: str
    chunkIndex: int
    content: str
    score: float


class HybridResult(RetrievedChunk):
    sources: list[Literal["vector", "keyword"]]
    hybridScore: float


class ContextSource(BaseModel):
    sourceId: int
    documentId: str
    filename: str
    chunkIndex: int
    snippet: str


class BuiltContext(BaseModel):
    text: str
    sources: list[ContextSource]


class QueryDebug(BaseModel):
    results: list[HybridResult]
    context: BuiltContext


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[ContextSource]
    debug: QueryDebug
