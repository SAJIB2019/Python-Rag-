# Nest.js → FastAPI migration

| Nest.js component | Python implementation |
| --- | --- |
| Controllers and decorators | `APIRouter`, route decorators, typed parameters |
| DTOs / class-validator | Pydantic v2 models; whitespace trimming and `extra="forbid"` |
| Providers and modules | Service classes wired in lifespan; injected with `Depends` |
| Prisma and pg | `asyncpg` connection pool with parameterized SQL |
| BullMQ worker | ARQ worker with a separate Redis queue namespace |
| LangChain RunnableLambda pipeline | Native async service composition and `asyncio.gather` |
| LlamaIndex SentenceSplitter | Python LlamaIndex `SentenceSplitter`, 200 tokens / 30 overlap |
| fetch OpenAI-compatible requests | Shared HTTPx AsyncClient, timeouts, response validation |
| Qdrant + Elasticsearch clients | Async HTTPx requests to their REST APIs |
| Guards | Dependencies for auth and Redis-backed rate limits |
| Exception filter | FastAPI exception handlers with Nest-style errors |
| Prometheus and OpenTelemetry | Python instrumentation and optional OTLP exporter |

## Preserved behavior

- Production routes retain the `/api` prefix and camelCase response fields.
- POST operations, including `/api/query`, return 201 as in Nest.js.
- The JSON document endpoint accepts already-extracted text, including when
  `mimeType=application/pdf`. Use the upload endpoint for binary PDF contents.
- Retrieval runs vector and keyword searches concurrently, requests ten candidates
  per modality, merges with reciprocal rank fusion (`k=60`), and returns five results.
- Context uses `[source:n]` markers, 240-character snippets, and the original
  approximate 3,000-character budget. Like the original, the first chunk is always
  included, and separator lengths are not included in the budget calculation.
- Query responses retain `question`, `answer`, `sources`, and `debug`.
- Fake embeddings use the original UTF-16 character-bucket algorithm. Fake LLM
  responses are development placeholders.

## Deliberate differences

- The Python pipeline uses native async composition instead of LangChain. No
  LangChain dependency is needed for this straight-line orchestration.
- Rate limits are shared through Redis, rather than an in-process map. Forwarded
  IPs must be handled by a trusted reverse proxy/Uvicorn configuration; arbitrary
  `x-forwarded-for` values are not read by the application.
- Document creation commits `queued` before enqueueing, preventing a fast worker's
  completed status from being overwritten by the request handler. If enqueueing
  fails, a periodic worker dispatcher retries durable queued rows every 30 seconds.
- Workers retry failures up to three attempts. Database advisory locks serialize
  processing for each document. Re-running completed jobs is a no-op. Chunk rows
  and vectors are replaced transactionally; external indexing finishes before the
  document becomes searchable. Final failures remain `failed` for inspection.
- Readiness checks PostgreSQL, Redis, and the configured external search indexes.
  It does not guarantee a worker is consuming jobs; monitor ARQ worker health and
  queued-document age separately.
- `DATABASE_URL` replaces the separate `POSTGRES_*` connection settings. Configure
  PostgreSQL SSL using the URL. `REQUEST_BODY_LIMIT_BYTES` is an integer replacing
  the original `REQUEST_BODY_LIMIT=1mb`. Other environment fields are documented
  in `.env.example`; unused Nest.js fields are ignored.
- The SQL schema uses a generated full-text column instead of an update trigger.
- Python parsing/tokenization may differ slightly from the JavaScript libraries.
  DOCX extraction also includes tables. No OCR is performed.
- Original dashboards, proxy configuration, backup scripts, load tests and the
  separate RAGAS evaluation tooling are not automatically deployed by this port.
  The HTTP contract is retained for evaluation clients; point them at port 8000.

## Data and rollout

The default setup intentionally creates a **new database** and separate index
names. No original documents, secrets, embeddings, Redis jobs, or environment
files are copied. The migration runner will fail rather than silently adopt an
existing Nest.js schema. Do not point it at the Nest.js database.

For an initial migration, upload the source documents to this service and allow
its worker to rebuild embeddings/indexes. A database-level data import requires
an explicit, separately planned migration. BullMQ jobs cannot be consumed by ARQ.

Changing embedding dimensions requires a fresh schema/reingestion; the migration
runner checks the existing vector column dimension. pgvector HNSW storage here
supports up to 2,000 dimensions. Production settings reject fake providers, short
API/metrics keys and wildcard CORS. Use a reverse proxy for TLS and request
timeouts. Uploaded office archives can expand substantially during parsing;
enforce deployment memory/CPU limits appropriate to untrusted uploads.
