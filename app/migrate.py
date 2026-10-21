"""Explicit, transactional migrations for a dedicated FastAPI database."""

import asyncio
from pathlib import Path

import asyncpg

from app.core.config import Settings

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def read_migrations():
    return [(path.name, path.read_text()) for path in sorted(MIGRATIONS.glob("*.sql"))]


async def migrate():
    settings = Settings()
    migrations = await asyncio.to_thread(read_migrations)
    conn = await asyncpg.connect(settings.database_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(72401933)")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS fastapi_schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())"
            )
            for name, content in migrations:
                if await conn.fetchval(
                    "SELECT 1 FROM fastapi_schema_migrations WHERE name=$1", name
                ):
                    continue
                sql = content.replace("__DIMENSIONS__", str(settings.embedding_dimensions))
                await conn.execute(sql)
                await conn.execute("INSERT INTO fastapi_schema_migrations(name) VALUES($1)", name)
                print(f"Applied {name}")
            dimensions = await conn.fetchval("""
                SELECT atttypmod FROM pg_attribute
                WHERE attrelid='document_chunks'::regclass AND attname='embedding'
            """)
            if dimensions != settings.embedding_dimensions:
                raise ValueError(
                    "Existing vector column dimensions differ from EMBEDDING_DIMENSIONS; create a new database and reingest"
                )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
