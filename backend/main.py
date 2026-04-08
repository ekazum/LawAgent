import argparse
import base64
import os
from typing import List, Literal, Optional

import google.generativeai as genai
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("GEMINI_API_KEY is not set")

genai.configure(api_key=api_key)

SYSTEM_INSTRUCTION = (
    "You are an expert Israeli Employment Law Attorney and Senior Litigator. "
    "Your role is to assist legal professionals in drafting pleadings, analyzing evidentiary documents, "
    "preparing cross-examinations, and formulating legal summations. "
    "Your expertise is strictly confined to Israeli Labor Law. "
    "Never hallucinate legal facts. "
    "Always respond in high-level, formal Hebrew legal terminology unless requested otherwise."
)


def search_legal_database(query: str) -> str:
    normalized_query = query.lower()

    if "overtime" in normalized_query or "שעות נוספות" in normalized_query:
        return (
            "תקדים מדומה: בית הדין הארצי לעבודה קבע כי אי-תשלום גמול שעות נוספות "
            "בניגוד לחוק שעות עבודה ומנוחה מזכה את העובד בהפרשי שכר, פיצויי הלנה "
            "והוצאות משפט, בכפוף להוכחת היקף השעות ונטל הרישום החל על המעסיק."
        )

    if "severance" in normalized_query or "פיצויי פיטורים" in normalized_query:
        return (
            "תקדים מדומה: נפסק כי עובד שפוטר לאחר שנת עבודה מלאה זכאי לפיצויי פיטורים "
            "מלאים לפי חוק פיצויי פיטורים, אלא אם המעסיק הוכיח חריג סטטוטורי ברור "
            "המצדיק שלילה או הפחתה."
        )

    return (
        "תקדים מדומה: בתי הדין לעבודה מדגישים כי יש לבחון את מכלול נסיבות יחסי העבודה, "
        "חובת תום הלב, והמסגרת הראייתית לפני קביעת זכויות כספיות וסעדים."
    )


model = genai.GenerativeModel(
    model_name="gemini-1.5-pro",
    system_instruction=SYSTEM_INSTRUCTION,
    tools=[search_legal_database],
)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class FileInput(BaseModel):
    mime_type: str = "application/octet-stream"
    data_base64: str
    name: Optional[str] = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: List[ChatMessage] = Field(default_factory=list)
    file: Optional[FileInput] = None


class ChatResponse(BaseModel):
    response: str
    history: List[ChatMessage]


app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _to_gemini_history(history: List[ChatMessage]) -> list[dict]:
    return [
        {
            "role": "model" if item.role == "assistant" else "user",
            "parts": [{"text": item.content}],
        }
        for item in history
    ]


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        chat_session = model.start_chat(
            history=_to_gemini_history(req.history),
            enable_automatic_function_calling=True,
        )

        payload: list = [req.message]
        if req.file:
            payload.append(
                {
                    "mime_type": req.file.mime_type or "application/octet-stream",
                    "data": base64.b64decode(req.file.data_base64),
                }
            )

        response = chat_session.send_message(payload)
        response_text = (response.text or "").strip()
        assistant_message = (
            response_text or "לא התקבלה תשובה מהמודל. אנא נסה שנית."
        )

        updated_history = [
            *req.history,
            ChatMessage(role="user", content=req.message),
            ChatMessage(role="assistant", content=assistant_message),
        ]

        return ChatResponse(response=assistant_message, history=updated_history)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"שגיאה במהלך השיחה: {error}") from error


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = parser.parse_args()
    uvicorn.run("main:app", host=args.host, port=args.port, reload=False)
