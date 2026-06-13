import os
from typing import Optional, cast

from psycopg_pool import ConnectionPool

import queries

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://lawagent:lawagent@127.0.0.1:5432/lawagent"
)

_pool: Optional[ConnectionPool] = None


def get_pool() -> ConnectionPool:
    global _pool
    pool = _pool
    if pool is None:
        pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, open=True)
        _pool = pool
    return pool


def init_schema() -> None:
    with get_pool().connection() as conn:
        conn.execute(queries.SCHEMA)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


def _document_row_to_dict(row: tuple) -> dict:
    return {
        "id": row[0],
        "name": row[1],
        "doc_type": row[2],
        "chunk_count": row[3],
        "created_at": row[4].isoformat(),
        "category": row[5],
        "case_number": row[6],
        "court": row[7],
        "parties": row[8],
        "decision_date": row[9],
    }


def insert_document(
    name: str,
    doc_type: str,
    mime_type: str,
    chunks: list[dict],
    category: Optional[str] = None,
    case_number: Optional[str] = None,
    court: Optional[str] = None,
    parties: Optional[str] = None,
    decision_date: Optional[str] = None,
) -> dict:
    with get_pool().connection() as conn:
        row = conn.execute(
            queries.INSERT_DOCUMENT,
            (
                name,
                doc_type,
                mime_type,
                len(chunks),
                category,
                case_number,
                court,
                parties,
                decision_date,
            ),
        ).fetchone()
        row = cast(tuple, row)  # INSERT ... RETURNING always yields a row
        document_id = row[0]
        with conn.cursor() as cursor:
            cursor.executemany(
                queries.INSERT_CHUNK,
                [
                    (
                        document_id,
                        chunk["index"],
                        chunk.get("section"),
                        chunk["content"],
                        _vector_literal(chunk["embedding"]),
                    )
                    for chunk in chunks
                ],
            )
    return _document_row_to_dict(row)


def list_documents(category: Optional[str] = None) -> list[dict]:
    params = (category,) if category else ()
    with get_pool().connection() as conn:
        rows = conn.execute(
            queries.select_documents(bool(category)), params
        ).fetchall()
    return [_document_row_to_dict(row) for row in rows]


UPDATABLE_DOCUMENT_FIELDS = (
    "doc_type",
    "category",
    "case_number",
    "court",
    "parties",
    "decision_date",
)


def update_document(document_id: int, fields: dict) -> Optional[dict]:
    updates = {
        key: value
        for key, value in fields.items()
        if key in UPDATABLE_DOCUMENT_FIELDS
    }
    if not updates:
        return None
    with get_pool().connection() as conn:
        row = conn.execute(
            queries.update_document(updates.keys()),
            (*updates.values(), document_id),
        ).fetchone()
    if row is None:
        return None
    return _document_row_to_dict(cast(tuple, row))


def delete_document(document_id: int) -> bool:
    with get_pool().connection() as conn:
        row = conn.execute(queries.DELETE_DOCUMENT, (document_id,)).fetchone()
    return row is not None


def search_chunks(
    query_embedding: list[float],
    top_k: int = 5,
    doc_types: Optional[list[str]] = None,
    category: Optional[str] = None,
) -> list[dict]:
    params: list = [_vector_literal(query_embedding)]
    if doc_types:
        params.append(doc_types)
    if category:
        params.append(category)
    params.append(top_k)
    with get_pool().connection() as conn:
        rows = conn.execute(
            queries.search_chunks(bool(doc_types), bool(category)), params
        ).fetchall()
    return [
        {
            "document_name": row[0],
            "doc_type": row[1],
            "chunk_index": row[2],
            "section": row[3],
            "content": row[4],
            "distance": float(row[5]),
        }
        for row in rows
    ]


def list_categories() -> list[dict]:
    with get_pool().connection() as conn:
        rows = conn.execute(queries.SELECT_CATEGORIES).fetchall()
    return [{"id": row[0], "name": row[1]} for row in rows]


def add_category(name: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        row = conn.execute(queries.INSERT_CATEGORY, (name,)).fetchone()
    if row is None:
        return None
    row = cast(tuple, row)
    return {"id": row[0], "name": row[1]}


def delete_category(category_id: int) -> bool:
    with get_pool().connection() as conn:
        row = conn.execute(queries.DELETE_CATEGORY, (category_id,)).fetchone()
        if row is None:
            return False
        row = cast(tuple, row)
        conn.execute(queries.CLEAR_DOCUMENTS_CATEGORY, (row[0],))
    return True


def create_conversation(title: str, owner: str) -> dict:
    with get_pool().connection() as conn:
        row = conn.execute(queries.INSERT_CONVERSATION, (title, owner)).fetchone()
    row = cast(tuple, row)  # INSERT ... RETURNING always yields a row
    return {"id": row[0], "title": title, "updated_at": row[1].isoformat()}


def list_conversations(owner: str) -> list[dict]:
    with get_pool().connection() as conn:
        rows = conn.execute(queries.SELECT_CONVERSATIONS, (owner,)).fetchall()
    return [
        {"id": row[0], "title": row[1], "updated_at": row[2].isoformat()}
        for row in rows
    ]


def delete_conversation(conversation_id: int, owner: str) -> bool:
    with get_pool().connection() as conn:
        row = conn.execute(
            queries.DELETE_CONVERSATION, (conversation_id, owner)
        ).fetchone()
    return row is not None


def get_conversation_messages(
    conversation_id: int, owner: str
) -> Optional[list[dict]]:
    with get_pool().connection() as conn:
        exists = conn.execute(
            queries.CONVERSATION_EXISTS, (conversation_id, owner)
        ).fetchone()
        if exists is None:
            return None
        rows = conn.execute(queries.SELECT_MESSAGES, (conversation_id,)).fetchall()
    return [{"role": row[0], "content": row[1]} for row in rows]


def add_message(conversation_id: int, role: str, content: str) -> None:
    with get_pool().connection() as conn:
        conn.execute(queries.INSERT_MESSAGE, (conversation_id, role, content))
        conn.execute(queries.TOUCH_CONVERSATION, (conversation_id,))
