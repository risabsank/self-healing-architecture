from collections.abc import Generator
from pathlib import Path

from psycopg import Connection
from psycopg.rows import dict_row

from app.core.config import settings


MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def get_connection() -> Generator[Connection, None, None]:
    with Connection.connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn


def open_connection() -> Connection:
    return Connection.connect(settings.database_url, row_factory=dict_row)


def execute_schema_bootstrap() -> None:
    with Connection.connect(settings.database_url) as conn:
        run_migrations(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.commit()


def run_migrations(conn: Connection) -> None:
    migration_dir = migration_directory()
    with conn.cursor() as cur:
        cur.execute(MIGRATION_TABLE_SQL)
        if not migration_dir.exists():
            return
        for migration in sorted(migration_dir.glob("*.sql")):
            apply_migration(cur, migration)


def migration_directory() -> Path:
    docker_path = Path(settings.repair_repo_root) / "infra" / "postgres" / "migrations"
    if docker_path.exists():
        return docker_path
    return Path(__file__).resolve().parents[4] / "infra" / "postgres" / "migrations"


def apply_migration(cur, migration: Path) -> None:
    version = migration.stem
    cur.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (version,))
    if cur.fetchone():
        return
    cur.execute(migration.read_text())
    cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
