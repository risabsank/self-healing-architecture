from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from app.core.db import get_connection
from app.memory import list_memories, search_memories

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/incidents")
def list_incident_memories(
    limit: int = Query(default=50, ge=1, le=200),
    conn: Connection = Depends(get_connection),
):
    return {"memories": list_memories(conn, limit)}


@router.get("/search")
def search_incident_memories(
    query: str,
    limit: int = Query(default=10, ge=1, le=50),
    conn: Connection = Depends(get_connection),
):
    return {"memories": search_memories(conn, query, limit)}
