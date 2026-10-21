import json
from uuid import UUID, uuid4

from app.schemas import DocumentResponse, RetrievedChunk


def document_response(row) -> DocumentResponse:
    return DocumentResponse(
        id=row["id"],
        filename=row["filename"],
        mimeType=row["mime_type"],
        source=row["source"],
        status=row["status"],
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


def retrieved(row, score=None) -> RetrievedChunk:
    return RetrievedChunk(
        documentId=str(row["document_id"]),
        filename=row["filename"],
        chunkIndex=row["chunk_index"],
        content=row["content"],
        score=float(row["score"] if score is None else score),
    )


class Repository:
    def __init__(self, pool):
        self.pool = pool

    async def create(self, filename: str, mime_type: str, content: str, source: str | None):
        row = await self.pool.fetchrow(
            """
            INSERT INTO documents (id, filename, mime_type, raw_text, source, status)
            VALUES ($1, $2, $3, $4, $5, 'queued') RETURNING *
        """,
            uuid4(),
            filename,
            mime_type,
            content,
            source,
        )
        return document_response(row)

    async def find(self, document_id: UUID):
        row = await self.pool.fetchrow("SELECT * FROM documents WHERE id=$1", document_id)
        return document_response(row) if row else None

    async def set_status(self, document_id: UUID, status: str):
        await self.pool.execute(
            "UPDATE documents SET status=$2, updated_at=now() WHERE id=$1", document_id, status
        )

    async def queued_ids(self):
        return await self.pool.fetch(
            "SELECT id FROM documents WHERE status='queued' ORDER BY created_at LIMIT 1000"
        )

    async def replace_chunks(self, conn, document_id: UUID, chunks: list[dict]):
        async with conn.transaction():
            await conn.execute("DELETE FROM document_chunks WHERE document_id=$1", document_id)
            await conn.executemany(
                """
                INSERT INTO document_chunks (id, document_id, chunk_index, content, token_count, embedding)
                VALUES ($1,$2,$3,$4,$5,$6::vector)
            """,
                [
                    (
                        uuid4(),
                        document_id,
                        c["chunk_index"],
                        c["content"],
                        c["token_count"],
                        json.dumps(c["embedding"]),
                    )
                    for c in chunks
                ],
            )

    async def vector_search(self, embedding, limit=10):
        rows = await self.pool.fetch(
            """
            SELECT dc.document_id, d.filename, dc.chunk_index, dc.content,
                   dc.embedding <=> $1::vector AS score
            FROM document_chunks dc JOIN documents d ON d.id=dc.document_id
            WHERE dc.embedding IS NOT NULL AND d.status='completed'
            ORDER BY dc.embedding <=> $1::vector LIMIT $2
        """,
            json.dumps(embedding),
            limit,
        )
        return [retrieved(r) for r in rows]

    async def keyword_search(self, question, limit=10):
        rows = await self.pool.fetch(
            """
            SELECT dc.document_id, d.filename, dc.chunk_index, dc.content,
                   ts_rank_cd(dc.search_vector, websearch_to_tsquery('english',$1)) AS score
            FROM document_chunks dc JOIN documents d ON d.id=dc.document_id
            WHERE dc.search_vector @@ websearch_to_tsquery('english',$1) AND d.status='completed'
            ORDER BY score DESC LIMIT $2
        """,
            question,
            limit,
        )
        return [retrieved(r) for r in rows]

    async def hydrate(self, hits: list[tuple[str, float]], limit: int):
        if not hits:
            return []
        rows = await self.pool.fetch(
            """
            SELECT dc.id, dc.document_id, d.filename, dc.chunk_index, dc.content
            FROM document_chunks dc JOIN documents d ON d.id=dc.document_id
            WHERE dc.id=ANY($1::uuid[]) AND d.status='completed'
        """,
            [UUID(hit[0]) for hit in hits],
        )
        by_id = {str(r["id"]): r for r in rows}
        return [retrieved(by_id[key], score) for key, score in hits if key in by_id][:limit]

    async def indexed_chunks(self, document_id: UUID):
        return await self.pool.fetch(
            """
            SELECT id, content, embedding::text AS embedding FROM document_chunks
            WHERE document_id=$1 ORDER BY chunk_index
        """,
            document_id,
        )
