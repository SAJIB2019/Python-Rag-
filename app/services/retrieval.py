import asyncio
import re

from app.core.telemetry import span
from app.schemas import BuiltContext, ContextSource, HybridResult, QueryDebug, QueryResponse


def merge_hybrid_results(vector_results, keyword_results, limit: int = 5):
    merged = {}
    for source, results in (("vector", vector_results), ("keyword", keyword_results)):
        for rank, result in enumerate(results, 1):
            key = (result.documentId, result.chunkIndex)
            score = 1 / (60 + rank)
            if key in merged:
                merged[key].hybridScore += score
                if source not in merged[key].sources:
                    merged[key].sources.append(source)
            else:
                merged[key] = HybridResult(
                    **result.model_dump(), sources=[source], hybridScore=score
                )
    return sorted(merged.values(), key=lambda r: -r.hybridScore)[:limit]


def build_context(results, max_characters: int = 3000) -> BuiltContext:
    parts, sources = [], []
    used = 0
    for result in results:
        source_id = len(sources) + 1
        formatted = f"[source:{source_id}] {result.content}"
        if parts and used + len(formatted) > max_characters:
            break
        parts.append(formatted)
        used += len(formatted)
        snippet = re.sub(r"\s+", " ", result.content).strip()
        sources.append(
            ContextSource(
                sourceId=source_id,
                documentId=result.documentId,
                filename=result.filename,
                chunkIndex=result.chunkIndex,
                snippet=snippet[:240] + ("..." if len(snippet) > 240 else ""),
            )
        )
    return BuiltContext(text="\n\n".join(parts), sources=sources)


class QueryService:
    def __init__(self, search, embeddings, llm):
        self.search, self.embeddings, self.llm = search, embeddings, llm

    async def query(self, question: str) -> QueryResponse:
        with span("rag.query"):
            with span("rag.embed"):
                embedding = await self.embeddings.embed(question)
            with span("rag.retrieve"):
                vector, keyword = await asyncio.gather(
                    self.search.vector_search(embedding), self.search.keyword_search(question)
                )
                results = merge_hybrid_results(vector, keyword)
                context = build_context(results)
            with span("rag.generate"):
                answer = await self.llm.generate(question, context.text)
            return QueryResponse(
                question=question,
                answer=answer,
                sources=context.sources,
                debug=QueryDebug(results=results, context=context),
            )
