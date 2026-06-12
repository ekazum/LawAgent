import argparse
import base64
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Iterator, List, Optional

import anthropic
import uvicorn
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

import db
from constants import (
    CHAT_MODEL,
    DOC_TYPES,
    IMAGE_MEDIA_TYPES,
    MAX_RESPONSE_TOKENS,
    MAX_TOOL_ITERATIONS,
)
from ingestion import UnsupportedFileError, chunk_text, embed_documents, extract_text
from prompts import SYSTEM_INSTRUCTION
from schemas import (
    CategoryCreate,
    CategoryInfo,
    ChatMessage,
    ChatRequest,
    ConversationInfo,
    DocumentClassification,
    DocumentInfo,
    DocumentUpdate,
    FileInput,
    TemplateInfo,
)
from templates import TEMPLATES, template_context
from tools import (
    CLIENT_TOOL_STATUS,
    SERVER_TOOL_STATUS,
    build_chat_tools,
    collect_web_sources,
    run_client_tool,
)

logger = logging.getLogger("lawagent")


def classify_document(
    api_key: str, filename: str, text: str, categories: list[str]
) -> Optional[DocumentClassification]:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        f"סווג את המסמך המשפטי הבא (שם הקובץ: {filename}).\n"
        f"קטגוריות זמינות: {', '.join(categories) or 'אין'}.\n"
        "קבע האם זהו פסק דין או החלטה שיפוטית, ובחר קטגוריה אחת מהרשימה בלבד "
        "(אם אף אחת אינה מתאימה בחר 'כללי' אם קיימת, אחרת השאר ריק). "
        "אם זהו פסק דין, חלץ גם: מספר הליך, ערכאה, שמות הצדדים ותאריך ההחלטה.\n\n"
        f"--- תחילת המסמך ---\n{text[:6000]}"
    )
    classification_messages: list[Any] = [{"role": "user", "content": prompt}]
    try:
        response = client.messages.parse(
            model=CHAT_MODEL,
            max_tokens=1024,
            messages=classification_messages,
            output_format=DocumentClassification,
        )
        classification = response.parsed_output
        if classification and classification.category not in categories:
            classification.category = None
        return classification
    except Exception as error:
        logger.warning("document classification failed: %s", error)
        return None


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        db.init_schema()
        logger.info("database schema ready")
    except Exception as error:
        logger.warning(
            "database unavailable, knowledge base features disabled: %s", error
        )
    yield
    db.close_pool()


app = FastAPI(lifespan=lifespan)

# noinspection PyTypeChecker
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_api_key(x_api_key: Optional[str]) -> str:
    api_key = (x_api_key or os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail=(
                "לא הוגדר מפתח API של Anthropic. הגדר את משתנה הסביבה "
                "ANTHROPIC_API_KEY בשרת או הזן מפתח בממשק."
            ),
        )
    return api_key


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/templates", response_model=List[TemplateInfo])
def get_templates() -> List[TemplateInfo]:
    return [
        TemplateInfo(key=key, label=value["label"], description=value["description"])
        for key, value in TEMPLATES.items()
    ]


@app.post("/api/documents", response_model=DocumentInfo, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    category: str = Form(default=""),
    x_api_key: Optional[str] = Header(default=None),
) -> DocumentInfo:
    if doc_type != "auto" and doc_type not in DOC_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"סוג מסמך לא חוקי: {doc_type}. ערכים חוקיים: auto, {', '.join(DOC_TYPES)}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="הקובץ שהועלה ריק.")

    try:
        text = extract_text(file.filename or "", file.content_type or "", data)
    except UnsupportedFileError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="לא נמצא טקסט במסמך.")

    final_type = doc_type if doc_type in DOC_TYPES else None
    final_category = category.strip() or None
    metadata: dict = {}

    if final_type is None or final_category is None:
        api_key = (x_api_key or os.getenv("ANTHROPIC_API_KEY") or "").strip()
        if api_key:
            # noinspection PyBroadException
            try:
                category_names = [item["name"] for item in db.list_categories()]
            except Exception:
                category_names = []
            classification = classify_document(
                api_key, file.filename or "", text, category_names
            )
            if classification:
                if final_type is None:
                    final_type = (
                        "precedent"
                        if classification.is_court_decision
                        else "guideline"
                    )
                if final_category is None:
                    final_category = classification.category
                if classification.is_court_decision:
                    metadata = {
                        "case_number": classification.case_number,
                        "court": classification.court,
                        "parties": classification.parties,
                        "decision_date": classification.decision_date,
                    }
        if final_type is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "סיווג אוטומטי אינו זמין (אין מפתח API או שהסיווג נכשל) — "
                    "בחר סוג מסמך ידנית."
                ),
            )

    try:
        embeddings = embed_documents([chunk["content"] for chunk in chunks])
    except Exception as error:
        raise HTTPException(
            status_code=500, detail=f"שגיאה ביצירת הטמעות (embeddings): {error}"
        ) from error
    for chunk, embedding in zip(chunks, embeddings):
        chunk["embedding"] = embedding

    try:
        document = db.insert_document(
            name=file.filename or "ללא שם",
            doc_type=final_type,
            mime_type=file.content_type or "application/octet-stream",
            chunks=chunks,
            category=final_category,
            **metadata,
        )
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error

    return DocumentInfo(**document)


@app.get("/api/documents", response_model=List[DocumentInfo])
def get_documents(category: Optional[str] = None) -> List[DocumentInfo]:
    try:
        return [
            DocumentInfo(**document) for document in db.list_documents(category)
        ]
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error


@app.patch("/api/documents/{document_id}", response_model=DocumentInfo)
def patch_document(document_id: int, update: DocumentUpdate) -> DocumentInfo:
    fields = update.model_dump(exclude_unset=True)
    if "doc_type" in fields and fields["doc_type"] not in DOC_TYPES:
        raise HTTPException(status_code=400, detail="סוג מסמך לא חוקי.")
    if not fields:
        raise HTTPException(status_code=400, detail="לא סופקו שדות לעדכון.")
    try:
        document = db.update_document(document_id, fields)
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error
    if document is None:
        raise HTTPException(status_code=404, detail="המסמך לא נמצא.")
    return DocumentInfo(**document)


@app.delete("/api/documents/{document_id}", status_code=204)
def remove_document(document_id: int) -> None:
    try:
        deleted = db.delete_document(document_id)
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error
    if not deleted:
        raise HTTPException(status_code=404, detail="המסמך לא נמצא.")


@app.get("/api/categories", response_model=List[CategoryInfo])
def get_categories() -> List[CategoryInfo]:
    try:
        return [CategoryInfo(**item) for item in db.list_categories()]
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error


@app.post("/api/categories", response_model=CategoryInfo, status_code=201)
def create_category(payload: CategoryCreate) -> CategoryInfo:
    try:
        created = db.add_category(payload.name.strip())
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error
    if created is None:
        raise HTTPException(status_code=409, detail="קטגוריה בשם זה כבר קיימת.")
    return CategoryInfo(**created)


@app.delete("/api/categories/{category_id}", status_code=204)
def remove_category(category_id: int) -> None:
    try:
        deleted = db.delete_category(category_id)
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error
    if not deleted:
        raise HTTPException(status_code=404, detail="הקטגוריה לא נמצאה.")


@app.get("/api/conversations", response_model=List[ConversationInfo])
def get_conversations() -> List[ConversationInfo]:
    try:
        return [ConversationInfo(**item) for item in db.list_conversations()]
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error


@app.get("/api/conversations/{conversation_id}/messages", response_model=List[ChatMessage])
def get_conversation(conversation_id: int) -> List[ChatMessage]:
    try:
        messages = db.get_conversation_messages(conversation_id)
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error
    if messages is None:
        raise HTTPException(status_code=404, detail="השיחה לא נמצאה.")
    return [ChatMessage(**message) for message in messages]


@app.delete("/api/conversations/{conversation_id}", status_code=204)
def remove_conversation(conversation_id: int) -> None:
    try:
        deleted = db.delete_conversation(conversation_id)
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error
    if not deleted:
        raise HTTPException(status_code=404, detail="השיחה לא נמצאה.")


def _file_content_block(file: FileInput) -> dict:
    media_type = (file.mime_type or "application/octet-stream").lower()

    if media_type in IMAGE_MEDIA_TYPES:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": file.data_base64,
            },
        }

    if media_type == "application/pdf":
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": file.data_base64,
            },
        }

    if media_type.startswith("text/"):
        text = base64.b64decode(file.data_base64).decode("utf-8", errors="replace")
        name = file.name or "קובץ מצורף"
        return {"type": "text", "text": f"--- תוכן הקובץ המצורף ({name}) ---\n{text}"}

    raise UnsupportedFileError(
        f"סוג קובץ לא נתמך בצ'אט: {media_type}. נתמכים: PDF, תמונות, טקסט."
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chat_stream(req: ChatRequest, api_key: str) -> Iterator[str]:
    template = TEMPLATES.get(req.template) if req.template else None
    if template is not None:
        template_label: Optional[str] = template["label"]
        template_instruction: Optional[str] = template["instruction"]
        template_doc_types: list[str] = template["doc_types"]
    else:
        template_label = None
        template_instruction = None
        template_doc_types = []

    # Resolve conversation + history. If the DB is down, chat still works
    # statelessly — the conversation just isn't persisted.
    history: list[dict] = []
    conversation_id = req.conversation_id
    persist = True
    try:
        if conversation_id is not None:
            stored = db.get_conversation_messages(conversation_id)
            if stored is None:
                yield _sse({"type": "error", "detail": "השיחה לא נמצאה."})
                return
            history = stored
        else:
            prefix = f"[{template_label}] " if template_label else ""
            title = (prefix + req.message).strip()[:80]
            conversation_id = db.create_conversation(title)["id"]
    except Exception as error:
        logger.warning("conversation persistence unavailable: %s", error)
        persist = False
        conversation_id = None

    yield _sse({"type": "start", "conversation_id": conversation_id})

    user_blocks: list[dict] = []
    if template_instruction is not None:
        yield _sse({"type": "status", "text": "שולף מקורות רלוונטיים מהמאגר..."})
        context = template_context(req.message, template_doc_types)
        instruction = template_instruction
        if context:
            instruction += "\n\nמקורות רלוונטיים שאותרו במאגר הידע:\n\n" + context
        user_blocks.append({"type": "text", "text": instruction})
    user_blocks.append({"type": "text", "text": req.message})
    if req.file:
        try:
            user_blocks.append(_file_content_block(req.file))
        except UnsupportedFileError as error:
            yield _sse({"type": "error", "detail": str(error)})
            return

    messages: list[Any] = [
        {"role": item["role"], "content": item["content"]} for item in history
    ]
    messages.append({"role": "user", "content": user_blocks})

    client = anthropic.Anthropic(api_key=api_key)
    # noinspection PyBroadException
    try:
        category_names = [item["name"] for item in db.list_categories()]
    except Exception:
        category_names = []
    chat_tools: list[Any] = build_chat_tools(category_names)

    collected: list[str] = []
    response = None
    seen_sources: set = set()
    sources: list[dict] = []
    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            with client.messages.stream(
                model=CHAT_MODEL,
                max_tokens=MAX_RESPONSE_TOKENS,
                system=SYSTEM_INSTRUCTION,
                tools=chat_tools,
                messages=messages,
            ) as stream:
                for event in stream:
                    if (
                        event.type == "content_block_start"
                        and event.content_block.type == "server_tool_use"
                    ):
                        status = SERVER_TOOL_STATUS.get(event.content_block.name)
                        if status:
                            yield _sse({"type": "status", "text": status})
                    elif (
                        event.type == "content_block_delta"
                        and event.delta.type == "text_delta"
                    ):
                        collected.append(event.delta.text)
                        yield _sse({"type": "delta", "text": event.delta.text})
                response = stream.get_final_message()

            collect_web_sources(response, seen_sources, sources)

            if response.stop_reason == "pause_turn":
                # Server-side tool loop paused mid-turn; resend to resume.
                messages.append({"role": "assistant", "content": response.content})
                continue

            if response.stop_reason != "tool_use":
                break

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    yield _sse(
                        {
                            "type": "status",
                            "text": CLIENT_TOOL_STATUS.get(block.name, "מפעיל כלי..."),
                        }
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": run_client_tool(block.name, block.input or {}),
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
    except anthropic.AuthenticationError:
        yield _sse({"type": "error", "detail": "מפתח ה-API של Anthropic אינו תקין."})
        return
    except anthropic.RateLimitError:
        yield _sse(
            {
                "type": "error",
                "detail": "חריגה ממגבלת הקצב של Anthropic. נסה שוב בעוד רגע.",
            }
        )
        return
    except anthropic.APIError as error:
        yield _sse({"type": "error", "detail": f"שגיאה משירות Anthropic: {error.message}"})
        return
    except Exception as error:
        logger.exception("chat stream failed")
        yield _sse({"type": "error", "detail": f"שגיאה במהלך השיחה: {error}"})
        return

    if sources:
        sources_text = "\n\n**מקורות (פסיקה ורשת):**\n" + "\n".join(
            f"- [{item['title']}]({item['url']})" for item in sources
        )
        collected.append(sources_text)
        yield _sse({"type": "delta", "text": sources_text})

    final_text = "".join(collected).strip()
    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason == "refusal" and not final_text:
        final_text = "הבקשה נדחתה משיקולי בטיחות. נסח את הפנייה מחדש."
        yield _sse({"type": "delta", "text": final_text})
    if not final_text:
        final_text = "לא התקבלה תשובה מהמודל. אנא נסה שנית."
        yield _sse({"type": "delta", "text": final_text})

    if persist and conversation_id is not None:
        stored_user = req.message
        if template_label:
            stored_user = f"[{template_label}]\n{stored_user}"
        if req.file and req.file.name:
            stored_user += f"\n[צורף קובץ: {req.file.name}]"
        try:
            db.add_message(conversation_id, "user", stored_user)
            db.add_message(conversation_id, "assistant", final_text)
        except Exception as error:
            logger.warning("failed to persist conversation: %s", error)

    yield _sse({"type": "done", "conversation_id": conversation_id})


@app.post("/api/chat")
def chat(
    req: ChatRequest, x_api_key: Optional[str] = Header(default=None)
) -> StreamingResponse:
    api_key = _resolve_api_key(x_api_key)
    if req.template and req.template not in TEMPLATES:
        raise HTTPException(status_code=400, detail=f"תבנית לא מוכרת: {req.template}")
    return StreamingResponse(
        _chat_stream(req, api_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Serve the built frontend when present (Docker image copies it to ./static).
# Mounted last so API routes above always win; absent in dev mode.
_static_dir = Path(os.getenv("FRONTEND_DIST") or Path(__file__).parent / "static")
if _static_dir.is_dir():
    app.mount(
        "/", StaticFiles(directory=str(_static_dir), html=True), name="frontend"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, reload=False)
