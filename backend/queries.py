"""All SQL for the database layer, kept out of db.py.

Every statement here is built only from literals and whitelisted
identifiers (never user input); values are always bound via %s
placeholders. _literal() marks the strings as LiteralString so psycopg's
type stubs accept them.
"""

from typing import TYPE_CHECKING, Iterable, cast

from constants import EMBEDDING_DIM

if TYPE_CHECKING:
    from typing import LiteralString


def _literal(query: str) -> "LiteralString":
    return cast("LiteralString", query)


# Columns returned for a document row, in the order _document_row_to_dict expects.
_DOCUMENT_COLUMNS = (
    "id, name, doc_type, chunk_count, created_at, "
    "category, case_number, court, parties, decision_date"
)


SCHEMA = _literal(
    f"""
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
)

# --- documents ---

INSERT_DOCUMENT = _literal(
    "INSERT INTO documents "
    "(name, doc_type, mime_type, chunk_count, category, case_number, court, parties, decision_date) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
    f"RETURNING {_DOCUMENT_COLUMNS}"
)

INSERT_CHUNK = _literal(
    "INSERT INTO chunks (document_id, chunk_index, section, content, embedding) "
    "VALUES (%s, %s, %s, %s, %s::vector)"
)

DELETE_DOCUMENT = _literal("DELETE FROM documents WHERE id = %s RETURNING id")


def select_documents(filter_by_category: bool) -> "LiteralString":
    where = "WHERE category = %s" if filter_by_category else ""
    return _literal(
        f"SELECT {_DOCUMENT_COLUMNS} FROM documents {where} ORDER BY created_at DESC"
    )


def update_document(field_names: Iterable[str]) -> "LiteralString":
    # field_names are whitelisted in db.UPDATABLE_DOCUMENT_FIELDS before reaching here.
    set_clause = ", ".join(f"{name} = %s" for name in field_names)
    return _literal(
        f"UPDATE documents SET {set_clause} WHERE id = %s RETURNING {_DOCUMENT_COLUMNS}"
    )


def search_chunks(by_doc_types: bool, by_category: bool) -> "LiteralString":
    conditions = []
    if by_doc_types:
        conditions.append("d.doc_type = ANY(%s)")
    if by_category:
        conditions.append("d.category = %s")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return _literal(
        "SELECT d.name, d.doc_type, c.chunk_index, c.section, c.content, "
        "       c.embedding <=> %s::vector AS distance "
        f"FROM chunks c JOIN documents d ON d.id = c.document_id {where} "
        "ORDER BY distance ASC LIMIT %s"
    )


# --- categories ---

SELECT_CATEGORIES = _literal("SELECT id, name FROM categories ORDER BY id")

INSERT_CATEGORY = _literal(
    "INSERT INTO categories (name) VALUES (%s) "
    "ON CONFLICT (name) DO NOTHING RETURNING id, name"
)

DELETE_CATEGORY = _literal("DELETE FROM categories WHERE id = %s RETURNING name")

CLEAR_DOCUMENTS_CATEGORY = _literal(
    "UPDATE documents SET category = NULL WHERE category = %s"
)


# --- conversations & messages ---

INSERT_CONVERSATION = _literal(
    "INSERT INTO conversations (title, owner) VALUES (%s, %s) "
    "RETURNING id, created_at"
)

SELECT_CONVERSATIONS = _literal(
    "SELECT id, title, updated_at FROM conversations "
    "WHERE owner = %s ORDER BY updated_at DESC"
)

DELETE_CONVERSATION = _literal(
    "DELETE FROM conversations WHERE id = %s AND owner = %s RETURNING id"
)

CONVERSATION_EXISTS = _literal(
    "SELECT 1 FROM conversations WHERE id = %s AND owner = %s"
)

SELECT_MESSAGES = _literal(
    "SELECT role, content FROM messages "
    "WHERE conversation_id = %s ORDER BY id ASC"
)

INSERT_MESSAGE = _literal(
    "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)"
)

TOUCH_CONVERSATION = _literal(
    "UPDATE conversations SET updated_at = now() WHERE id = %s"
)
