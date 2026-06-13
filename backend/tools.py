import logging
from typing import Optional

from db import database
from constants import DOC_TYPE_LABELS, DOC_TYPES
from ingestion import chunk_text, embed_documents, embed_query
from prompts import KB_EMPTY_MESSAGE, KB_UNAVAILABLE_MESSAGE

logger = logging.getLogger("lawagent")


def build_search_tool(categories: list[str]) -> dict:
    category_hint = (
        " קטגוריות קיימות במאגר: " + ", ".join(categories) + "."
        if categories
        else ""
    )
    return {
        "name": "search_legal_database",
        "description": (
            "מחפש במאגר הידע הפנימי של המשרד — הנחיות, מסמכים לדוגמה ותקדימים — "
            "בתחום דיני העבודה הישראלי. יש להפעיל כלי זה לפני מתן כל תשובה משפטית "
            "מהותית. הכלי מחזיר קטעי מקור רלוונטיים עם שם המסמך וסוגו, לצורך ביסוס "
            "התשובה וציטוט המקורות. ניתן למקד את החיפוש לפי קטגוריה וסוג מסמך — "
            "השתמש במיקוד כאשר השאלה נוגעת לתחום מובהק." + category_hint
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "שאילתת חיפוש חופשית (עברית או אנגלית) המתארת את הסוגיה המשפטית.",
                },
                "category": {
                    "type": "string",
                    "description": "אופציונלי: שם קטגוריה מהרשימה הקיימת, למיקוד החיפוש.",
                },
                "doc_type": {
                    "type": "string",
                    "enum": list(DOC_TYPES),
                    "description": "אופציונלי: הגבלת החיפוש לסוג מסמך — guideline (הנחיה), example (מסמך לדוגמה), precedent (תקדים/פסיקה).",
                },
            },
            "required": ["query"],
        },
    }


SAVE_PRECEDENT_TOOL = {
    "name": "save_precedent",
    "description": (
        "שומר פסק דין (או קטעים נבחרים ממנו) אל מאגר הידע הפנימי של המשרד כתקדים, "
        "לשימוש עתידי בניסוח מסמכים. יש להפעיל כאשר המשתמש מבקש לשמור פסיקה שנמצאה, "
        "או לאחר אישור המשתמש להצעה לשמור."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "שם מזהה לפסק הדין, כולל מספר ההליך והצדדים "
                    "(למשל: ע\"ע 300/97 פלוני נ' אלמוני)"
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "הקטעים הרלוונטיים מפסק הדין בציטוט מדויק, כולל פרטי ההליך, "
                    "הערכאה ותאריך ההחלטה, וכתובת המקור (URL)."
                ),
            },
            "category": {
                "type": "string",
                "description": "אופציונלי: קטגוריה מהרשימה הקיימת במאגר.",
            },
            "case_number": {
                "type": "string",
                "description": "אופציונלי: מספר ההליך (למשל ע\"ע 300/97).",
            },
            "court": {
                "type": "string",
                "description": "אופציונלי: הערכאה (למשל בית הדין הארצי לעבודה).",
            },
            "parties": {
                "type": "string",
                "description": "אופציונלי: שמות הצדדים.",
            },
            "decision_date": {
                "type": "string",
                "description": "אופציונלי: תאריך ההחלטה.",
            },
        },
        "required": ["name", "content"],
    },
}

# 20260209 versions add dynamic filtering (Sonnet/Opus only — not Haiku).
WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 8,
}

WEB_FETCH_TOOL = {
    "type": "web_fetch_20260209",
    "name": "web_fetch",
    "max_uses": 5,
    "citations": {"enabled": True},
    "max_content_tokens": 40000,
}

SERVER_TOOL_STATUS = {
    "web_search": "מחפש פסיקה ומקורות ברשת...",
    "web_fetch": "קורא מסמך מהרשת...",
}

CLIENT_TOOL_STATUS = {
    "search_legal_database": "מחפש במאגר הידע...",
    "save_precedent": "שומר תקדים במאגר הידע...",
}


def build_chat_tools(categories: list[str]) -> list[dict]:
    return [
        build_search_tool(categories),
        SAVE_PRECEDENT_TOOL,
        WEB_SEARCH_TOOL,
        WEB_FETCH_TOOL,
    ]


def format_chunks(results: list[dict]) -> str:
    sections = []
    for position, result in enumerate(results, start=1):
        label = DOC_TYPE_LABELS.get(result["doc_type"], result["doc_type"])
        section_suffix = (
            f" | סעיף: {result['section']}" if result.get("section") else ""
        )
        sections.append(
            f"[מקור {position}: {result['document_name']} ({label}){section_suffix}]\n"
            f"{result['content']}"
        )
    return "\n\n---\n\n".join(sections)


def run_search(
    query: str,
    doc_type: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    doc_types = [doc_type] if doc_type in DOC_TYPES else None
    try:
        query_embedding = embed_query(query)
        results = database.search_chunks(
            query_embedding, top_k=5, doc_types=doc_types, category=category or None
        )
    except Exception as error:
        logger.warning("knowledge base search failed: %s", error)
        return KB_UNAVAILABLE_MESSAGE

    if not results:
        if doc_types or category:
            # Filtered search found nothing — retry unfiltered before giving up.
            return run_search(query)
        return KB_EMPTY_MESSAGE
    return format_chunks(results)


def coerce_category(value: Optional[str]) -> Optional[str]:
    candidate = (value or "").strip()
    if not candidate:
        return None
    try:
        names = [item["name"] for item in database.list_categories()]
    except Exception:
        return None
    if candidate in names:
        return candidate
    for name in names:
        if candidate in name or name in candidate:
            return name
    return None


def save_precedent(tool_input: dict) -> str:
    name = (tool_input.get("name") or "").strip()
    content = (tool_input.get("content") or "").strip()
    if not name or not content:
        return "שגיאה: יש לספק שם ותוכן לשמירת התקדים."
    try:
        chunks = chunk_text(content)
        if not chunks:
            return "שגיאה: לא נמצא טקסט לשמירה."
        embeddings = embed_documents([chunk["content"] for chunk in chunks])
        for chunk, embedding in zip(chunks, embeddings):
            chunk["embedding"] = embedding
        document = database.insert_document(
            name=name[:200],
            doc_type="precedent",
            mime_type="text/plain",
            chunks=chunks,
            category=coerce_category(tool_input.get("category")),
            case_number=(tool_input.get("case_number") or "").strip() or None,
            court=(tool_input.get("court") or "").strip() or None,
            parties=(tool_input.get("parties") or "").strip() or None,
            decision_date=(tool_input.get("decision_date") or "").strip() or None,
        )
        return (
            f"פסק הדין נשמר במאגר הידע כתקדים "
            f"(מסמך מס' {document['id']}, {document['chunk_count']} קטעים)."
        )
    except Exception as error:
        logger.warning("save_precedent failed: %s", error)
        return f"שמירת התקדים נכשלה: {error}"


def run_client_tool(name: str, tool_input: dict) -> str:
    if name == "search_legal_database":
        return run_search(
            tool_input.get("query", ""),
            doc_type=tool_input.get("doc_type"),
            category=tool_input.get("category"),
        )
    if name == "save_precedent":
        return save_precedent(tool_input)
    return f"כלי לא מוכר: {name}"


def collect_web_sources(response, seen: set, sources: list[dict]) -> None:
    for block in response.content:
        if block.type != "text":
            continue
        for citation in getattr(block, "citations", None) or []:
            url = getattr(citation, "url", None)
            if url and url not in seen:
                seen.add(url)
                sources.append(
                    {"url": url, "title": getattr(citation, "title", None) or url}
                )
