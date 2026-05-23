"""Run all SQL migration files in order. Safe to re-run (IF NOT EXISTS throughout)."""
import asyncio
import asyncpg
import sys
from pathlib import Path

# Allow running from project root: python -m migrations.run_migrations
sys.path.insert(0, str(Path(__file__).parent.parent))
from collector.config import settings


async def run_migrations(db_url: str | None = None) -> None:
    url = db_url or settings.database_url
    conn = await asyncpg.connect(dsn=url)
    try:
        migrations_dir = Path(__file__).parent
        sql_files = sorted(migrations_dir.glob("*.sql"))
        if not sql_files:
            print("No migration files found.")
            return
        for migration_file in sql_files:
            print(f"Running {migration_file.name}...")
            sql = migration_file.read_text()
            await conn.execute(sql)
            print(f"  ✓ Done")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
