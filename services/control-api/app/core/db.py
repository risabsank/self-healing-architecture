from collections.abc import Generator

from psycopg import Connection
from psycopg.rows import dict_row

from app.core.config import settings


def get_connection() -> Generator[Connection, None, None]:
    with Connection.connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn


def open_connection() -> Connection:
    return Connection.connect(settings.database_url, row_factory=dict_row)


def execute_schema_bootstrap() -> None:
    with Connection.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.commit()
