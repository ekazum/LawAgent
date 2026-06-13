CHAT_MODEL = "claude-sonnet-4-6"
MAX_RESPONSE_TOKENS = 32000
MAX_TOOL_ITERATIONS = 8

# Embedding vector dimension (intfloat/multilingual-e5-base); used by the
# DB schema (vector(N)) and validated in ingestion.
EMBEDDING_DIM = 768

DOC_TYPES = ("guideline", "example", "precedent")
DOC_TYPE_LABELS = {
    "guideline": "הנחיה",
    "example": "מסמך לדוגמה",
    "precedent": "תקדים",
}

IMAGE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")

# Upload size caps (raw decoded bytes). Caddy enforces a 40MB body ceiling
# upstream; these give per-path limits with friendly messages.
MAX_DOCUMENT_UPLOAD_BYTES = 25 * 1024 * 1024  # knowledge-base document
MAX_CHAT_FILE_BYTES = 10 * 1024 * 1024  # single chat attachment
MAX_CHAT_FILES_TOTAL_BYTES = 25 * 1024 * 1024  # all attachments in one message
