CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE documents (
    id uuid PRIMARY KEY,
    filename text NOT NULL,
    mime_type text NOT NULL,
    source text,
    status text NOT NULL CHECK (status IN ('uploaded','queued','processing','completed','failed')),
    raw_text text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX documents_status_index ON documents(status);
CREATE INDEX documents_created_at_index ON documents(created_at);
CREATE TABLE document_chunks (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    token_count integer NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    embedding vector(__DIMENSIONS__),
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    UNIQUE(document_id, chunk_index)
);
CREATE INDEX document_chunks_embedding_hnsw_index ON document_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX document_chunks_search_vector_index ON document_chunks USING gin(search_vector);
