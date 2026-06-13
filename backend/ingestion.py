import io
import re
import threading

from constants import EMBEDDING_DIM

# Multilingual local embedding model (Hebrew included), 768-dim — matches the
# pgvector schema. Downloaded from Hugging Face on first use (~1GB), then cached.
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"

MAX_CHUNK_CHARS = 3500
MIN_CHUNK_CHARS = 200

# Short line without sentence-ending punctuation — likely a heading in legal docs
# (e.g. "פרק ג': שעות נוספות" or "3. טענות הצדדים").
_HEADING_RE = re.compile(r"^.{1,80}$")
_SENTENCE_END_RE = re.compile(r"[.!?;,]\s*$")


class UnsupportedFileError(ValueError):
    pass


def _ocr_pdf(data: bytes) -> str:
    """OCR a scanned (text-layerless) PDF locally with Tesseract (heb+eng).

    Renders each page at 300 DPI via poppler and runs Tesseract. CPU-bound and
    slower than text extraction, so it only runs when pypdf finds no text.
    """
    import pytesseract
    from pdf2image import convert_from_bytes

    images = convert_from_bytes(data, dpi=300)
    parts = [pytesseract.image_to_string(image, lang="heb+eng") for image in images]
    return "\n\n".join(part.strip() for part in parts if part.strip()).strip()


def extract_text(filename: str, mime_type: str, data: bytes) -> str:
    name = (filename or "").lower()

    if name.endswith(".pdf") or mime_type == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(pages).strip()
        if text:
            return text
        # No text layer — a scanned PDF. OCR it locally (Hebrew + English).
        text = _ocr_pdf(data)
        if not text:
            raise UnsupportedFileError(
                "לא ניתן לחלץ טקסט מקובץ ה-PDF, גם לאחר OCR. ודא שהסריקה ברורה."
            )
        return text

    if name.endswith(".docx") or mime_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        from docx import Document

        document = Document(io.BytesIO(data))
        return "\n\n".join(
            paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()
        )

    if name.endswith((".txt", ".md")) or (mime_type or "").startswith("text/"):
        for encoding in ("utf-8", "cp1255"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise UnsupportedFileError("קידוד הטקסט אינו נתמך (נסה UTF-8).")

    raise UnsupportedFileError(
        f"סוג קובץ לא נתמך: {filename}. נתמכים: PDF, DOCX, TXT, MD."
    )


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    return (
        bool(stripped)
        and _HEADING_RE.match(stripped) is not None
        and _SENTENCE_END_RE.search(stripped) is None
        and "\n" not in stripped
    )


def chunk_text(text: str) -> list[dict]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: list[dict] = []
    current_parts: list[str] = []
    current_len = 0
    current_section: str | None = None
    pending_section: str | None = None

    def flush() -> None:
        nonlocal current_parts, current_len
        content = "\n\n".join(current_parts).strip()
        if content:
            chunks.append(
                {
                    "index": len(chunks),
                    "section": current_section,
                    "content": content,
                }
            )
        # Overlap: carry the last paragraph into the next chunk for continuity.
        carry = current_parts[-1] if current_parts else None
        current_parts = [carry] if carry and len(carry) < 800 else []
        current_len = sum(len(part) for part in current_parts)

    for paragraph in paragraphs:
        if _is_heading(paragraph):
            pending_section = paragraph.strip()
            if current_len >= MIN_CHUNK_CHARS:
                flush()
                current_parts = []
                current_len = 0
            current_section = pending_section

        if current_len + len(paragraph) > MAX_CHUNK_CHARS and current_len > 0:
            flush()

        current_parts.append(paragraph)
        current_len += len(paragraph)

    if current_len > 0:
        flush()

    return chunks


_model = None
_model_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _embed(texts: list[str]) -> list[list[float]]:
    vectors = _get_model().encode(texts, normalize_embeddings=True)
    embeddings = [vector.tolist() for vector in vectors]
    if embeddings and len(embeddings[0]) != EMBEDDING_DIM:
        raise RuntimeError(
            f"Embedding dimension {len(embeddings[0])} does not match schema "
            f"({EMBEDDING_DIM})."
        )
    return embeddings


# E5 models expect "passage: " / "query: " prefixes for asymmetric retrieval.
def embed_documents(texts: list[str]) -> list[list[float]]:
    return _embed([f"passage: {text}" for text in texts])


def embed_query(text: str) -> list[float]:
    return _embed([f"query: {text}"])[0]
