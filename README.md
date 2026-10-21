# RAG From Zero with FastAPI

Python rewrite of the sibling Nest.js service. It preserves `/api` routes, camelCase
JSON fields, document status values, reciprocal-rank fusion, source citations, and
the original fake-provider responses.

## Run locally

Python 3.12+ and Docker Desktop are required. Run these commands in this folder:

```bash
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e '.[dev]'
docker compose up -d postgres redis
python -m app.migrate
python -m app
```

In a second terminal, from this folder:

```bash
source .venv/bin/activate
arq app.worker.WorkerSettings
```

Interactive API docs: <http://localhost:8000/docs>. Health:
<http://localhost:8000/api/health>. The worker must be running to process documents.
`python -m app` reads `PORT`; alternatively use
`uvicorn app.main:app --reload --port 8000` for development.

Defaults use fake embedding/LLM providers so no paid API calls are needed. The fake
LLM returns a placeholder answer, not a factual generated answer. To use your real
provider, configure `EMBEDDING_PROVIDER` and `LLM_PROVIDER` as `openai-compatible`,
set `OPENAI_COMPATIBLE_BASE_URL` (including `/v1` where required),
`OPENAI_COMPATIBLE_API_KEY`, and the model names. Choose `EMBEDDING_DIMENSIONS`
before migrating, matching your provider. Reingest documents when changing the
embedding model; embeddings from different models are not interchangeable.

## Try the pipeline

```bash
curl -X POST http://localhost:8000/api/documents \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: local-development-key' \
  -d '{"filename":"policy.md","mimeType":"text/markdown","content":"Customers may request refunds within 30 days."}'

# Use the returned ID; wait until status is completed.
curl http://localhost:8000/api/documents/DOCUMENT_ID \
  -H 'x-api-key: local-development-key'

curl -X POST http://localhost:8000/api/query \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: local-development-key' \
  -d '{"question":"What is the refund policy?"}'

curl -X POST http://localhost:8000/api/documents/upload \
  -H 'x-api-key: local-development-key' \
  -F 'file=@/path/to/document.pdf' -F 'source=manual-upload'
```

Uploads support PDF, DOCX, XLSX, CSV, TXT, Markdown, JSON, and HTML. Scanned PDFs
need OCR before uploading. Binary parsing and LlamaIndex tokenization run in
worker threads so they do not block the async event loop.

## Project structure

```text
app/
  main.py                 FastAPI app factory and lifespan
  __main__.py             Local API launch command
  resources.py            Shared clients and service dependency wiring
  core/
    config.py             Environment settings and validation
    exceptions.py         Shared HTTP error handlers
    middleware.py         Body limits, request IDs, metrics and logs
    telemetry.py          Optional OpenTelemetry spans
  api/
    dependencies.py       Service injection, authentication and rate limits
    routes/               Document, query, health and metrics endpoints
  schemas/
    base.py               Shared input validation configuration
    documents.py          Document request and response models
    query.py              Query, retrieval and citation models
  db/
    repository.py         Parameterized PostgreSQL operations
  integrations/
    providers.py          Embedding and LLM provider implementations
  services/
    documents.py          Document creation, upload and queue dispatch
    ingestion.py          File extraction, cleaning and chunking
    retrieval.py          RAG pipeline, fusion and citation context
    search.py             PostgreSQL or external hybrid search
  workers/
    ingestion.py          ARQ jobs, retries and queued-row recovery
  worker.py               Stable ARQ launch entry point
  migrate.py              Transactional SQL migration command
  reindex.py              External search rebuild command
migrations/               Dedicated PostgreSQL/pgvector schema
tests/                    Unit, API and real-service integration tests
requirements.lock         Pinned runtime dependencies
docker-compose.yml        Isolated development services, API and worker
Dockerfile                Non-root Python application image
```

Routes validate HTTP input and call services. Services implement the document and
query workflows; repositories handle SQL, and integrations handle provider calls.
`resources.py` constructs these dependencies once per process and closes them at
shutdown. Worker jobs share the same services and clients. Add new routes under
`api/routes`, models under `schemas`, and business workflows under `services`.

## Editor imports

Select **Python: Select Interpreter → .venv/bin/python** in VS Code, then reload
the window. Run commands from the project root; launch with `python -m app`,
not `python app/main.py`. Install the project and development tools into that same
interpreter:

```bash
.venv/bin/python -m ensurepip --upgrade
.venv/bin/python -m pip install -r requirements.lock -e '.[dev]'
.venv/bin/python -m pip check
```

Installing the project in editable mode makes `app` importable by command-line
and editor tools. Dependencies must be installed; changing import search paths
alone does not install FastAPI, Pydantic, or LlamaIndex.

## Routes

| Method | Route | Behavior |
| --- | --- | --- |
| POST | `/api/documents` | Store text, queue ingestion; 201 |
| POST | `/api/documents/upload` | Extract uploaded file and queue ingestion; 201 |
| GET | `/api/documents/{id}` | Document metadata and processing status |
| POST | `/api/query` | Hybrid retrieval and answer with sources; 201 |
| GET | `/api/health` | Public liveness |
| GET | `/api/health/ready` | Public dependency readiness; 503 when unavailable |
| GET | `/api/metrics` | Prometheus metrics, separate metrics key |

Document/query routes require `x-api-key` when `API_KEY` is nonempty. Metrics accept
`x-metrics-api-key` or `Authorization: Bearer ...`. Validation errors return 400,
matching the Nest.js API. Clients can use the generated OpenAPI schema at
`/openapi.json`.

## Optional external search

PostgreSQL/pgvector is the default. To use the original alternative retrieval stack:

```bash
docker compose --profile rag up -d postgres redis qdrant elasticsearch
# Wait for Elasticsearch to finish starting, then set in .env:
# SEARCH_BACKEND=qdrant-elasticsearch
python -m app.reindex
```

Restart the API and worker after configuration changes. PostgreSQL remains the
source of truth; external hits are checked against completed documents and current
chunk IDs. Reindex copies existing embeddings; it does not regenerate them.

## Run everything in Docker

```bash
cp .env.example .env  # only if .env does not exist yet
docker compose --profile app up --build -d
```

For external search, start the `rag` services first and wait for them to be ready,
then use `docker compose --profile rag --profile app up --build -d`.
The one-shot migration service runs before API/worker startup. Development database
credentials are local defaults; provide deployment-specific secrets and TLS for production.

This stack uses PostgreSQL `55433`, Redis `6380`, Qdrant `6334`, Elasticsearch `9201`,
and API `8000`, with separate `rag-fastapi` Docker volumes. It does not use the
original Nest.js project's database or queue.

## Verification

```bash
ruff check app tests
ruff format --check app tests
pytest -q

# Use only the dedicated FastAPI development/test database.
RUN_INTEGRATION=1 pytest -q -m integration
# Optional external search integration (after starting rag services):
SEARCH_BACKEND=qdrant-elasticsearch RUN_INTEGRATION=1 pytest -q -m integration
```

Integration tests create and remove their own documents and use a separate queue.
Real LLM/embedding credentials are not required for the tests. To refresh pinned
runtime dependencies, use `uv pip compile pyproject.toml --universal -o requirements.lock`.

Set `OTEL_ENABLED=true` and an OTLP HTTP trace endpoint to export RAG spans. HTTP
Prometheus counters/histograms use route templates to avoid unbounded labels. Run
one Uvicorn process per container for these process-local metrics; scale containers.

Framework references: [FastAPI dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/),
[FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/),
and [ARQ jobs and retries](https://arq-docs.helpmanual.io/).
