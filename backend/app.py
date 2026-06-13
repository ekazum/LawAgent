"""FastAPI application: app object, middleware, and all route handlers.

Run with `uvicorn app:app` (Docker) or `python main.py` (local CLI).
Non-routing logic lives in chat_service.py, classification.py, and
dependencies.py.
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import auth
import db
from chat_service import b64_decoded_size, chat_stream
from classification import classify_document
from constants import (
    DOC_TYPES,
    MAX_CHAT_FILE_BYTES,
    MAX_CHAT_FILES_TOTAL_BYTES,
    MAX_DOCUMENT_UPLOAD_BYTES,
)
from dependencies import RATE_LIMIT_DETAIL, client_ip, current_user, resolve_api_key
from ingestion import UnsupportedFileError, chunk_text, embed_documents, extract_text
from ratelimit import login_global_limiter, login_ip_limiter
from schemas import (
    CategoryCreate,
    CategoryInfo,
    ChatMessage,
    ChatRequest,
    ConversationInfo,
    DocumentInfo,
    DocumentUpdate,
    LoginRequest,
    TemplateInfo,
)
from templates import TEMPLATES

logger = logging.getLogger("lawagent")


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

# Open endpoints: login itself, the auth probe, and /health (docker healthcheck).
_AUTH_EXEMPT_PATHS = {"/api/login", "/api/auth/status"}


@app.middleware("http")
async def require_session(request: Request, call_next):
    path = request.url.path
    if (
        auth.auth_required()
        and path.startswith("/api")
        and path not in _AUTH_EXEMPT_PATHS
    ):
        token = request.headers.get("X-Session-Token", "")
        if auth.verify_token(token) is None:
            return JSONResponse({"detail": "נדרשת התחברות"}, status_code=401)
    return await call_next(request)


# noinspection PyTypeChecker
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/auth/status")
def auth_status() -> dict[str, bool]:
    return {"required": auth.auth_required()}


@app.post("/api/login")
async def login(http_request: Request, credentials: LoginRequest) -> dict[str, str]:
    now = time.time()
    ip = client_ip(http_request)
    # Atomic per-IP + global rate limiting — caps attempts regardless of
    # concurrency, so parallel brute-force can't outrun the lockout.
    if not login_ip_limiter.allow(ip, now):
        raise HTTPException(
            status_code=429, detail=RATE_LIMIT_DETAIL, headers={"Retry-After": "300"}
        )
    if not login_global_limiter.allow("*", now):
        raise HTTPException(
            status_code=429, detail=RATE_LIMIT_DETAIL, headers={"Retry-After": "60"}
        )
    if not auth.verify_credentials(credentials.username, credentials.password):
        await asyncio.sleep(1)  # extra friction on the (capped) failed attempts
        raise HTTPException(status_code=401, detail="שם משתמש או סיסמה שגויים")
    login_ip_limiter.reset(ip)  # a successful login clears the IP's counter
    return {"token": auth.issue_token(credentials.username)}


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

    # Reject oversized uploads before reading the whole file into memory when
    # the multipart size is known; len(data) is the backstop otherwise.
    if file.size is not None and file.size > MAX_DOCUMENT_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="הקובץ גדול מדי — מקסימום 25MB.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="הקובץ שהועלה ריק.")
    if len(data) > MAX_DOCUMENT_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="הקובץ גדול מדי — מקסימום 25MB.")

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
def get_conversations(user: str = Depends(current_user)) -> List[ConversationInfo]:
    try:
        return [ConversationInfo(**item) for item in db.list_conversations(user)]
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error


@app.get(
    "/api/conversations/{conversation_id}/messages",
    response_model=List[ChatMessage],
)
def get_conversation(
    conversation_id: int, user: str = Depends(current_user)
) -> List[ChatMessage]:
    try:
        messages = db.get_conversation_messages(conversation_id, user)
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error
    if messages is None:
        raise HTTPException(status_code=404, detail="השיחה לא נמצאה.")
    return [ChatMessage(**message) for message in messages]


@app.delete("/api/conversations/{conversation_id}", status_code=204)
def remove_conversation(
    conversation_id: int, user: str = Depends(current_user)
) -> None:
    try:
        deleted = db.delete_conversation(conversation_id, user)
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"מסד הנתונים אינו זמין: {error}"
        ) from error
    if not deleted:
        raise HTTPException(status_code=404, detail="השיחה לא נמצאה.")


@app.post("/api/chat")
def chat(
    req: ChatRequest,
    x_api_key: Optional[str] = Header(default=None),
    user: str = Depends(current_user),
) -> StreamingResponse:
    api_key = resolve_api_key(x_api_key)
    if req.template and req.template not in TEMPLATES:
        raise HTTPException(status_code=400, detail=f"תבנית לא מוכרת: {req.template}")
    total_attached = 0
    for attached in req.all_files:
        size = b64_decoded_size(attached.data_base64)
        if size > MAX_CHAT_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"הקובץ '{attached.name or 'ללא שם'}' גדול מדי — מקסימום 10MB לקובץ.",
            )
        total_attached += size
    if total_attached > MAX_CHAT_FILES_TOTAL_BYTES:
        raise HTTPException(
            status_code=413, detail="סך הקבצים המצורפים גדול מדי — מקסימום 25MB."
        )
    return StreamingResponse(
        chat_stream(req, api_key, user),
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
