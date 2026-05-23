"""Run pending SQL migration files in order.

Each file is applied in its own transaction. Filenames are recorded in
schema_migrations so subsequent runs skip files already applied.
"""
import asyncio
import asyncpg
import sys
from pathlib import Path

# Allow running from project root: python -m migrations.run_migrations
sys.path.insert(0, str(Path(__file__).parent.parent))
from collector.config import settings


async def _ensure_tracking_table(conn: asyncpg.Connection) -> None:
    """Create the schema_migrations table if it doesn't yet exist.

    Needed because the first migration is itself responsible for creating it,
    but we need to read from it before running anything. So we create it
    defensively first; the migration file's IF NOT EXISTS is then a no-op.
    """
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


async def _already_applied(conn: asyncpg.Connection, filename: str) -> bool:
    row = await conn.fetchrow(
        "SELECT 1 FROM schema_migrations WHERE filename = $1",
        filename,
    )
    return row is not None


async def run_migrations(db_url: str | None = None) -> None:
    url = db_url or settings.database_url
    conn = await asyncpg.connect(dsn=url)
    try:
        await _ensure_tracking_table(conn)

        migrations_dir = Path(__file__).parent
        sql_files = sorted(migrations_dir.glob("*.sql"))
        if not sql_files:
            print("No migration files found.")
            return

        for migration_file in sql_files:
            name = migration_file.name
            if await _already_applied(conn, name):
                print(f"Skipping {name} (already applied)")
                continue

            print(f"Running {name}...")
            sql = migration_file.read_text()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES ($1) "
                    "ON CONFLICT (filename) DO NOTHING",
                    name,
                )
            print(f"  [done]")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
