import asyncio

from app.core.config import Settings
from app.resources import open_resources


async def reindex():
    settings = Settings()
    if settings.search_backend != "qdrant-elasticsearch":
        raise SystemExit("Set SEARCH_BACKEND=qdrant-elasticsearch to rebuild external indexes")
    async with open_resources(settings) as resources:
        last_id = None
        while True:
            rows = await resources.pool.fetch(
                """
                SELECT id FROM documents WHERE status='completed' AND ($1::uuid IS NULL OR id>$1)
                ORDER BY id LIMIT 100
            """,
                last_id,
            )
            if not rows:
                break
            for row in rows:
                await resources.search.sync_document(row["id"])
            last_id = rows[-1]["id"]
            print(f"Indexed {len(rows)} documents")


if __name__ == "__main__":
    asyncio.run(reindex())
