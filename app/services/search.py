import asyncio
import json

import httpx

from app.integrations.providers import validate_vector


class SearchService:
    """PostgreSQL is authoritative for both retrieval backends."""

    def __init__(self, settings, repository, client: httpx.AsyncClient):
        self.settings, self.repository, self.client = settings, repository, client
        self.enabled = settings.search_backend == "qdrant-elasticsearch"
        self.qpath = f"/collections/{settings.qdrant_collection}"
        self.epath = f"/{settings.elasticsearch_index}"
        self._lock = asyncio.Lock()
        self._initialized = False

    async def request(self, target, method, path, **kwargs):
        if target == "q":
            base = self.settings.qdrant_url
            headers = (
                {"api-key": self.settings.qdrant_api_key} if self.settings.qdrant_api_key else {}
            )
        else:
            base = self.settings.elasticsearch_url
            headers = (
                {"Authorization": f"ApiKey {self.settings.elasticsearch_api_key}"}
                if self.settings.elasticsearch_api_key
                else {}
            )
        headers.update(kwargs.pop("headers", {}))
        response = await self.client.request(
            method, base.rstrip("/") + path, headers=headers, **kwargs
        )
        return response

    async def json_request(self, target, method, path, **kwargs):
        response = await self.request(target, method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def ensure_indexes(self):
        if not self.enabled or self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            response = await self.request("q", "GET", self.qpath)
            if response.status_code == 404:
                created = await self.request(
                    "q",
                    "PUT",
                    self.qpath,
                    json={
                        "vectors": {
                            "size": self.settings.embedding_dimensions,
                            "distance": "Cosine",
                        }
                    },
                )
                if created.status_code not in (200, 201, 409):
                    created.raise_for_status()
            info = await self.json_request("q", "GET", self.qpath)
            vectors = info["result"]["config"]["params"]["vectors"]
            if (
                vectors.get("size") != self.settings.embedding_dimensions
                or vectors.get("distance") != "Cosine"
            ):
                raise ValueError("Qdrant dimensions/distance do not match configuration")
            response = await self.request("e", "HEAD", self.epath)
            if response.status_code == 404:
                created = await self.request(
                    "e",
                    "PUT",
                    self.epath,
                    json={
                        "mappings": {
                            "properties": {
                                "documentId": {"type": "keyword"},
                                "content": {"type": "text", "analyzer": "english"},
                            }
                        }
                    },
                )
                if created.is_error:
                    # Another process may have created the index concurrently.
                    check = await self.request("e", "HEAD", self.epath)
                    check.raise_for_status()
            else:
                response.raise_for_status()
            self._initialized = True

    async def check_readiness(self):
        if self.enabled:
            await asyncio.gather(
                self.json_request("q", "GET", self.qpath), self.json_request("e", "GET", self.epath)
            )

    async def sync_document(self, document_id):
        if not self.enabled:
            return
        await self.ensure_indexes()
        chunks = await self.repository.indexed_chunks(document_id)
        points = [
            {
                "id": str(c["id"]),
                "vector": validate_vector(
                    json.loads(c["embedding"]) if c["embedding"] else None,
                    self.settings.embedding_dimensions,
                ),
                "payload": {"documentId": str(document_id)},
            }
            for c in chunks
        ]
        await self.json_request(
            "q",
            "POST",
            self.qpath + "/points/delete?wait=true",
            json={
                "filter": {"must": [{"key": "documentId", "match": {"value": str(document_id)}}]}
            },
        )
        deleted = await self.json_request(
            "e",
            "POST",
            self.epath + "/_delete_by_query?refresh=true",
            json={"query": {"term": {"documentId": str(document_id)}}},
        )
        if deleted.get("timed_out") or deleted.get("failures"):
            raise RuntimeError("Elasticsearch cleanup failed")
        for offset in range(0, len(chunks), 100):
            await self.json_request(
                "q",
                "PUT",
                self.qpath + "/points?wait=true",
                json={"points": points[offset : offset + 100]},
            )
            operations = []
            for chunk in chunks[offset : offset + 100]:
                operations.extend(
                    [
                        {
                            "index": {
                                "_index": self.settings.elasticsearch_index,
                                "_id": str(chunk["id"]),
                            }
                        },
                        {"documentId": str(document_id), "content": chunk["content"]},
                    ]
                )
            body = "\n".join(json.dumps(op) for op in operations) + "\n"
            result = await self.json_request(
                "e",
                "POST",
                "/_bulk?refresh=wait_for",
                content=body,
                headers={"Content-Type": "application/x-ndjson"},
            )
            if result.get("errors"):
                raise RuntimeError("Elasticsearch bulk indexing failed")

    async def vector_search(self, embedding, limit=10):
        if not self.enabled:
            return await self.repository.vector_search(embedding, limit)
        result = await self.json_request(
            "q",
            "POST",
            self.qpath + "/points/query",
            json={"query": embedding, "limit": limit * 3, "with_payload": False},
        )
        return await self.repository.hydrate(
            [(str(p["id"]), 1 - p["score"]) for p in result["result"]["points"]], limit
        )

    async def keyword_search(self, question, limit=10):
        if not self.enabled:
            return await self.repository.keyword_search(question, limit)
        result = await self.json_request(
            "e",
            "POST",
            self.epath + "/_search",
            json={"size": limit * 3, "query": {"match": {"content": question}}, "_source": False},
        )
        return await self.repository.hydrate(
            [(h["_id"], h.get("_score") or 0) for h in result["hits"]["hits"]], limit
        )
