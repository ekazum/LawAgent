import os
from typing import Optional

from psycopg_pool import ConnectionPool

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://lawagent:lawagent@127.0.0.1:5432/lawagent"
)

EMBEDDING_DIM = 768

SCHEMA_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    doc_type TEXT NOT NULL CHECK (doc_type IN ('guideline', 'example', 'precedent')),
    mime_type TEXT,
    chunk_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    document_id INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    section TEXT,
    content TEXT NOT NULL,
    embedding vector({EMBEDDING_DIM}) NOT NULL
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    owner TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id INT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS messages_conversation_idx
    ON messages (conversation_id, id);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS case_number TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS court TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS parties TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS decision_date TEXT;

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS owner TEXT;
CREATE INDEX IF NOT EXISTS conversations_owner_idx ON conversations (owner);

CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

INSERT INTO categories (name)
SELECT unnest(ARRAY[
    'שעות נוספות ושעות עבודה',
    'פיטורים ופיצויי פיטורים',
    'שימוע',
    'שכר והלנת שכר',
    'הטרדה ואפליה',
    'יחסי עובד-מעביד',
    'חופשה, מחלה והבראה',
    'הסכמים קיבוציים',
    'סודיות ואי-תחרות',
    'כללי'
])
WHERE NOT EXISTS (SELECT 1 FROM categories);
"""

_pool: Optional[ConnectionPool] = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, open=True)
    return _pool


def init_schema() -> None:
    with get_pool().connection() as conn:
        conn.execute(SCHEMA_SQL)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


DOCUMENT_COLUMNS = (
    "id, name, doc_type, chunk_count, created_at, "
    "category, case_number, court, parties, decision_date"
)


def _document_row_to_dict(row) -> dict:
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
            "INSERT INTO documents "
            "(name, doc_type, mime_type, chunk_count, category, case_number, court, parties, decision_date) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {DOCUMENT_COLUMNS}",
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
        document_id = row[0]
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO chunks (document_id, chunk_index, section, content, embedding) "
                "VALUES (%s, %s, %s, %s, %s::vector)",
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
    where = "WHERE category = %s" if category else ""
    params = (category,) if category else ()
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT {DOCUMENT_COLUMNS} FROM documents {where} ORDER BY created_at DESC",
            params,
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
    set_clause = ", ".join(f"{key} = %s" for key in updates)
    with get_pool().connection() as conn:
        row = conn.execute(
            f"UPDATE documents SET {set_clause} WHERE id = %s RETURNING {DOCUMENT_COLUMNS}",
            (*updates.values(), document_id),
        ).fetchone()
    return _document_row_to_dict(row) if row else None


def delete_document(document_id: int) -> bool:
    with get_pool().connection() as conn:
        row = conn.execute(
            "DELETE FROM documents WHERE id = %s RETURNING id", (document_id,)
        ).fetchone()
    return row is not None


def search_chunks(
    query_embedding: list[float],
    top_k: int = 5,
    doc_types: Optional[list[str]] = None,
    category: Optional[str] = None,
) -> list[dict]:
    conditions = []
    params: list = [_vector_literal(query_embedding)]
    if doc_types:
        conditions.append("d.doc_type = ANY(%s)")
        params.append(doc_types)
    if category:
        conditions.append("d.category = %s")
        params.append(category)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(top_k)
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT d.name, d.doc_type, c.chunk_index, c.section, c.content, "
            "       c.embedding <=> %s::vector AS distance "
            f"FROM chunks c JOIN documents d ON d.id = c.document_id {where} "
            "ORDER BY distance ASC LIMIT %s",
            params,
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
        rows = conn.execute("SELECT id, name FROM categories ORDER BY id").fetchall()
    return [{"id": row[0], "name": row[1]} for row in rows]


def add_category(name: str) -> Optional[dict]:
    with get_pool().connection() as conn:
        row = conn.execute(
            "INSERT INTO categories (name) VALUES (%s) "
            "ON CONFLICT (name) DO NOTHING RETURNING id, name",
            (name,),
        ).fetchone()
    return {"id": row[0], "name": row[1]} if row else None


def delete_category(category_id: int) -> bool:
    with get_pool().connection() as conn:
        row = conn.execute(
            "DELETE FROM categories WHERE id = %s RETURNING name", (category_id,)
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            "UPDATE documents SET category = NULL WHERE category = %s", (row[0],)
        )
    return True


def create_conversation(title: str, owner: str) -> dict:
    with get_pool().connection() as conn:
        row = conn.execute(
            "INSERT INTO conversations (title, owner) VALUES (%s, %s) "
            "RETURNING id, created_at",
            (title, owner),
        ).fetchone()
    return {"id": row[0], "title": title, "updated_at": row[1].isoformat()}


def list_conversations(owner: str) -> list[dict]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT id, title, updated_at FROM conversations "
            "WHERE owner = %s ORDER BY updated_at DESC",
            (owner,),
        ).fetchall()
    return [
        {"id": row[0], "title": row[1], "updated_at": row[2].isoformat()}
        for row in rows
    ]


def delete_conversation(conversation_id: int, owner: str) -> bool:
    with get_pool().connection() as conn:
        row = conn.execute(
            "DELETE FROM conversations WHERE id = %s AND owner = %s RETURNING id",
            (conversation_id, owner),
        ).fetchone()
    return row is not None


def get_conversation_messages(
    conversation_id: int, owner: str
) -> Optional[list[dict]]:
    with get_pool().connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM conversations WHERE id = %s AND owner = %s",
            (conversation_id, owner),
        ).fetchone()
        if exists is None:
            return None
        rows = conn.execute(
            "SELECT role, content FROM messages "
            "WHERE conversation_id = %s ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
    return [{"role": row[0], "content": row[1]} for row in rows]


def add_message(conversation_id: int, role: str, content: str) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            (conversation_id, role, content),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = now() WHERE id = %s",
            (conversation_id,),
        )
